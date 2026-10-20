"""系统服务：依赖健康探测与 OpenAPI 契约文档加载。

探测逻辑全部收敛在 service 层，探针可整体注入（HealthProbes）以便测试
替换；本模块不返回任何 Flask Response。
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import yaml
from flask import current_app
from sqlalchemy import text

from src.model import db

# 统一东八区（契约：时间一律 ISO 8601 含 +08:00 偏移）
_CST = timezone(timedelta(hours=8))

# 探活超时（秒）：本地容器应毫秒级返回，超时仅用于防止挂死
_PROBE_TIMEOUT_S = 3.0
# Embedding 探活超时：云端 5s（对外网络），本地侧车 15s（首次请求可能伴随
# 权重换页，但侧车启动时已预热，稳态毫秒级；超时只用于防止挂死）
_EMBEDDING_TIMEOUT_S = 5.0
_EMBEDDING_LOCAL_TIMEOUT_S = 15.0
# EMBEDDING_MODE 合法取值；config.py 已校验并回退，这里做服务层兜底校验。
_EMBEDDING_MODES = ("local", "cloud", "auto")
# 视为「本机侧车」的主机名：这类地址必须直连，不能被系统代理劫持。
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0"})
_ERROR_SUMMARY_MAX = 200


def _now_iso() -> str:
    """当前时间（秒级精度），形如 ``2026-10-20T11:30:00+08:00``。"""
    return datetime.now(_CST).replace(microsecond=0).isoformat()


def _summarize(exc: Exception) -> str:
    """错误摘要（类型 + 信息，截断），用于 ServiceHealth.error。"""
    summary = f"{type(exc).__name__}: {exc}"
    return summary[:_ERROR_SUMMARY_MAX]


def _service_probe(ping: Callable[[], None]) -> dict:
    """执行一次探测并计时，返回契约 ServiceHealth 结构。"""
    started = time.perf_counter()
    try:
        ping()
    except Exception as exc:  # 探活需吞掉依赖侧一切异常并如实上报
        return {"status": "down", "latency_ms": None, "error": _summarize(exc)}
    latency_ms = round((time.perf_counter() - started) * 1000)
    return {"status": "up", "latency_ms": latency_ms, "error": None}


# ---- 各依赖的真实 ping（慢客户端一律惰性导入，避免拖慢应用启动）----


def _ping_mysql() -> None:
    db.session.execute(text("SELECT 1"))


def _ping_mongodb(uri: str) -> None:
    from pymongo import MongoClient

    client = MongoClient(uri, serverSelectionTimeoutMS=round(_PROBE_TIMEOUT_S * 1000))
    try:
        client.admin.command("ping")
    finally:
        client.close()


def _ping_redis(host: str, port: int, password: str) -> None:
    import redis as redis_lib

    client = redis_lib.Redis(
        host=host,
        port=port,
        password=password or None,
        socket_connect_timeout=_PROBE_TIMEOUT_S,
        socket_timeout=_PROBE_TIMEOUT_S,
    )
    try:
        client.ping()
    finally:
        client.close()


def _ping_chroma(host: str, port: int) -> None:
    # chromadb-client 1.5.9 的 HttpClient 无 timeout 参数，_PROBE_TIMEOUT_S 对其
    # 不生效（走 httpx 默认 5s 超时）；且构造内部会同步完成一次 get_user_identity
    # 真实往返，故构造成功即视为探活成功（耗时由 _service_probe 统一计时上报），
    # 不再额外调用 heartbeat() 造成第二次往返。超时统一问题待 chromadb-client
    # 支持 timeout 参数后跟进，不在本次范围。
    import chromadb

    chromadb.HttpClient(host=host, port=port)


def _is_loopback(base_url: str) -> bool:
    """判断 base_url 是否指向本机回环地址（本地侧车专用判断）。"""
    try:
        host = urlparse(base_url).hostname or ""
    except ValueError:
        return False
    return host in _LOOPBACK_HOSTS


def _embedding_ping(base_url: str, api_key: str, model: str, timeout_s: float) -> None:
    """向 OpenAI 兼容端点真实发一次向量化请求（失败抛异常）。

    复用项目已有 ``openai`` 包，与云端同构；不记录 api_key，异常摘要由
    调用方经 ``_summarize`` 截断后落日志。

    入口再做一次兜底校验：``OpenAI(base_url="")`` 会回落到官方
    ``https://api.openai.com/v1``，若此时 api_key 非空，凭据就会被发到境外
    端点。调用方已提前判空，这里再加一道防线（防御未来新调用点）。

    回环地址（本地侧车）**强制直连、不经系统代理**：macOS 开启全局代理
    （如 Clash）后 ``httpx`` 会读系统代理设置，连 ``127.0.0.1:8010`` 也绕去
    代理——侧车已停时代理会返回 502 并耗时数秒，把「本地探活」这个纯本机
    动作变成对外依赖，也让 ``mode=local`` 模式的耗时不再可控。
    """
    if not base_url or not api_key:
        raise ValueError("embedding base_url/api_key 未配置，拒绝发起请求")

    from openai import DefaultHttpxClient, OpenAI

    direct = _is_loopback(base_url)
    # DefaultHttpxClient 是 openai SDK 自带的 httpx 子类，能确保它与 SDK
    # 内部的 httpx 版本一致（SDK 3.x 已切到 httpx2，混用外部 httpx.Client
    # 有版本错配风险）。
    http_client = (
        DefaultHttpxClient(trust_env=False, timeout=timeout_s) if direct else None
    )
    try:
        client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout_s,
            max_retries=0,
            http_client=http_client,
        )
        client.embeddings.create(input=["ping"], model=model)
    finally:
        if http_client is not None:
            http_client.close()


def _embedding_down(model: str, dim: int) -> dict:
    """Embedding 不可用时的契约结构（``mode`` 必须为 null，不得报 cloud/local）。"""
    return {"mode": None, "model": model, "dim": dim, "status": "down"}


def _probe_cloud(
    *, cloud_base_url: str, cloud_api_key: str, cloud_model: str, dim: int
) -> dict | None:
    """探测云端 OpenAI 兼容端点；不可用（或配置不全）返回 None。

    配置不全时**直接跳过且不发请求**：``OpenAI(base_url="")`` 会隐式回落到
    官方 ``https://api.openai.com/v1``，若 api_key 非空则凭据外泄。
    """
    missing = [
        name
        for name, value in (
            ("EMBEDDING_BASE_URL", cloud_base_url),
            ("EMBEDDING_API_KEY", cloud_api_key),
            ("EMBEDDING_MODEL", cloud_model),
        )
        if not (value or "").strip()
    ]
    if missing:
        # 只报变量名，绝不回显取值（可能含凭据）
        current_app.logger.warning(
            "embedding 云端配置不完整（%s 为空），跳过云端探活", ", ".join(missing)
        )
        return None
    try:
        _embedding_ping(cloud_base_url, cloud_api_key, cloud_model, _EMBEDDING_TIMEOUT_S)
    except Exception as exc:
        current_app.logger.warning("embedding 探活失败（云端不可用）: %s", _summarize(exc))
        return None
    return {"mode": "cloud", "model": cloud_model, "dim": dim, "status": "up"}


def _probe_local(*, local_base_url: str, local_model: str, dim: int) -> dict:
    """探测本地侧车；失败时 ``model`` 报**本地模型名**（云端不参与）。"""
    if not (local_base_url or "").strip() or not (local_model or "").strip():
        current_app.logger.warning("embedding 本地侧车配置缺失（base_url/model 为空）")
        return _embedding_down(local_model, dim)
    try:
        # 本地侧车不校验 api_key，但 OpenAI 客户端要求非空，给占位值
        _embedding_ping(local_base_url, "local", local_model, _EMBEDDING_LOCAL_TIMEOUT_S)
    except Exception as exc:
        current_app.logger.warning("embedding 探活失败（本地侧车不可用）: %s", _summarize(exc))
        return _embedding_down(local_model, dim)
    return {"mode": "local", "model": local_model, "dim": dim, "status": "up"}


def _embedding_health(
    *,
    cloud_base_url: str,
    cloud_api_key: str,
    cloud_model: str,
    dim: int,
    local_base_url: str = "",
    local_model: str = "",
    local_enabled: bool = False,
    mode: str = "local",
) -> dict:
    """Embedding 探活，按 ``EMBEDDING_MODE`` 分派策略，返回契约 EmbeddingHealth。

    三种模式（``mode`` 参数，由 ``app.config["EMBEDDING_MODE"]`` 传入；缺省
    取 ``local``——宁可只探本地，也不允许意外外发请求）：

    - ``local``：**只探本地侧车，绝不发起任何云端请求**（零外发、零 5s 等待）。
      成功 ``mode=local``；失败 ``mode=null`` 且 ``model`` 报本地模型名。
    - ``cloud``：只探云端，失败直接 ``mode=null``（不回落本地），``model``
      报云端模型名。
    - ``auto``：旧行为——云端优先、本地兜底：云端可用 → ``mode=cloud``；
      否则若 ``local_enabled`` 且本地可用 → ``mode=local``；都失败 →
      ``mode=null, model=云端模型``。

    ``mode`` 取值非法时按 ``local`` 处理并落 WARNING。

    云端失败必定落日志（仅原因摘要，不含凭据）。本函数不抛异常，整体
    健康检查因此仍能返回 HTTP 200，由 ``data.status=degraded`` 表达降级。
    云端配置不全（base_url / api_key / model 任一为空）时在 ``auto`` /
    ``cloud`` 下均**直接判为云端不可用且不发请求**（安全短路）。
    """
    normalized = (mode or "").strip().lower()
    if normalized not in _EMBEDDING_MODES:
        current_app.logger.warning("EMBEDDING_MODE 取值非法（%r），按 local 处理", mode)
        normalized = "local"

    if normalized == "local":
        return _probe_local(local_base_url=local_base_url, local_model=local_model, dim=dim)

    cloud = _probe_cloud(
        cloud_base_url=cloud_base_url,
        cloud_api_key=cloud_api_key,
        cloud_model=cloud_model,
        dim=dim,
    )
    if cloud is not None:
        return cloud
    if normalized == "cloud":
        return _embedding_down(cloud_model, dim)

    # ---- auto：云端不可用 → 本地兜底 ----
    if not local_enabled:
        current_app.logger.warning("embedding 本地兜底已禁用（EMBEDDING_LOCAL_ENABLED=false）")
        return _embedding_down(cloud_model, dim)
    local = _probe_local(local_base_url=local_base_url, local_model=local_model, dim=dim)
    if local["status"] == "down":
        # 双失败：契约沿用云端模型名（本地也没真正接管）
        return _embedding_down(cloud_model, dim)
    current_app.logger.info("embedding 已降级到本地侧车：%s", local_base_url)
    return local


@dataclass(frozen=True)
class HealthProbes:
    """五个依赖的探针集合；可整体注入以便测试替换。"""

    mysql: Callable[[], dict]
    mongodb: Callable[[], dict]
    redis: Callable[[], dict]
    chroma: Callable[[], dict]
    embedding: Callable[[], dict]


def build_default_probes() -> HealthProbes:
    """基于当前应用配置构建真实探针（读取 app.config，不直接读环境变量）。"""

    def probe_mysql() -> dict:
        return _service_probe(_ping_mysql)

    def probe_mongodb() -> dict:
        return _service_probe(lambda: _ping_mongodb(current_app.config["MONGO_URI"]))

    def probe_redis() -> dict:
        config = current_app.config
        return _service_probe(
            lambda: _ping_redis(
                config["REDIS_HOST"], config["REDIS_PORT"], config["REDIS_PASSWORD"]
            )
        )

    def probe_chroma() -> dict:
        config = current_app.config
        return _service_probe(lambda: _ping_chroma(config["CHROMA_HOST"], config["CHROMA_PORT"]))

    def probe_embedding() -> dict:
        config = current_app.config
        return _embedding_health(
            cloud_base_url=config["EMBEDDING_BASE_URL"],
            cloud_api_key=config["EMBEDDING_API_KEY"],
            cloud_model=config["EMBEDDING_MODEL"],
            dim=config["EMBEDDING_DIM"],
            local_base_url=config.get("EMBEDDING_LOCAL_BASE_URL", ""),
            local_model=config.get("EMBEDDING_LOCAL_MODEL", ""),
            local_enabled=config.get("EMBEDDING_LOCAL_ENABLED", False),
            # 缺省 local：未配置该键的老配置也绝不外发云端请求
            mode=config.get("EMBEDDING_MODE", "local"),
        )

    return HealthProbes(
        mysql=probe_mysql,
        mongodb=probe_mongodb,
        redis=probe_redis,
        chroma=probe_chroma,
        embedding=probe_embedding,
    )


def check_health(probes: HealthProbes | None = None) -> dict:
    """聚合五个依赖的探测结果，返回契约 HealthData 结构。"""
    active = probes if probes is not None else build_default_probes()
    services = {
        "mysql": active.mysql(),
        "mongodb": active.mongodb(),
        "redis": active.redis(),
        "chroma": active.chroma(),
    }
    embedding = active.embedding()
    down = [name for name, item in services.items() if item["status"] == "down"]
    if embedding["status"] == "down":
        down.append("embedding")
    if down:
        current_app.logger.warning("健康检查降级，不可用依赖: %s", ", ".join(down))
    return {
        "status": "degraded" if down else "ok",
        "checked_at": _now_iso(),
        "services": services,
        "embedding": embedding,
    }


def load_openapi_document() -> dict:
    """读取仓库内 docs/api/openapi.yaml 并加载为可 JSON 化的结构（契约原文）。"""
    path = Path(current_app.config["OPENAPI_YAML_PATH"])
    with path.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)
