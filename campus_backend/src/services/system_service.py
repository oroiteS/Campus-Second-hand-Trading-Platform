"""系统服务：依赖健康探测与 OpenAPI 契约文档加载。

探测逻辑全部收敛在 service 层，探针可整体注入（HealthProbes）以便测试
替换；本模块不返回任何 Flask Response。
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from flask import current_app
from sqlalchemy import text

from src.model import db

# 统一东八区（契约：时间一律 ISO 8601 含 +08:00 偏移）
_CST = timezone(timedelta(hours=8))

# 探活超时（秒）：本地容器应毫秒级返回，超时仅用于防止挂死
_PROBE_TIMEOUT_S = 3.0
_EMBEDDING_TIMEOUT_S = 10.0
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
    import chromadb

    client = chromadb.HttpClient(host=host, port=port)
    client.heartbeat()


def _embedding_health(base_url: str, api_key: str, model: str, dim: int) -> dict:
    """Embedding 端点探活（批次 0 仅云端模式）：真实发一次向量化请求。

    契约 EmbeddingHealth 固定返回 mode/model/dim/status 四字段：云端可用
    mode=cloud；不可用 mode=null 且 status=down（细节落日志，不进响应）。
    """
    try:
        from openai import OpenAI

        client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=_EMBEDDING_TIMEOUT_S,
            max_retries=0,
        )
        client.embeddings.create(input=["ping"], model=model)
    except Exception as exc:
        current_app.logger.warning("embedding 探活失败（云端模式不可用）: %s", _summarize(exc))
        return {"mode": None, "model": model, "dim": dim, "status": "down"}
    return {"mode": "cloud", "model": model, "dim": dim, "status": "up"}


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
            config["EMBEDDING_BASE_URL"],
            config["EMBEDDING_API_KEY"],
            config["EMBEDDING_MODEL"],
            config["EMBEDDING_DIM"],
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
