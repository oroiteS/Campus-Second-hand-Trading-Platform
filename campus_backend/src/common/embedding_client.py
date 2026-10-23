"""Embedding 业务客户端（b2be2）：批量向量化与可用性探测，OpenAI 兼容端点。

全项目仅本模块（与 system_service 的探活）import openai。与 b0 health
探活的关系（取舍注明）：探活是「单条真实请求」语义（慢超时、计入延迟、
如实上报 mode/latency）；本模块是「批量 + 降级」语义（业务调用前快速
判定、双判定兜底），两者短期并存，不迁移不重构。

端点按 ``EMBEDDING_MODE`` 分派（语义与 config.py 一致）：

- ``local``（默认）：本地侧车（``EMBEDDING_LOCAL_BASE_URL`` / ``_MODEL``，
  api_key 用占位值——侧车不校验）；
- ``cloud``：云端（``EMBEDDING_BASE_URL`` / ``_API_KEY`` / ``_MODEL``）；
- ``auto``：云端配置齐全则云端优先，否则本地侧车。
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

from flask import current_app

# 批量上限（条/次）：超出自动分批（发布单条、rebuild_all 批量共用本入口）
BATCH_SIZE = 32
# 单批请求超时（秒）与失败重试次数（共尝试 1 + RETRIES 次）
TIMEOUT_S = 10.0
RETRIES = 1
# is_available 快速探测的 TCP 连接超时（秒）
_PROBE_TIMEOUT_S = 1.0

logger = logging.getLogger(__name__)


def _is_loopback(base_url: str) -> bool:
    """判断 base_url 是否指向本机回环（与 system_service 同构判定，独立实现——
    common 层禁止反向 import services）。回环端点强制直连、不经系统代理：
    macOS 全局代理会把 127.0.0.1 请求绕去代理，让本地调用不可控。"""
    try:
        host = urlparse(base_url).hostname or ""
    except ValueError:
        return False
    if not host:
        return False
    if host.lower().rstrip(".") == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            packed = socket.inet_aton(host)
        except OSError:
            return False
        return packed[0] == 127
    if address.is_unspecified:
        return True
    if address.version == 6 and address.ipv4_mapped is not None:
        return address.ipv4_mapped.is_loopback
    return address.is_loopback


def _resolve_endpoint() -> tuple[str, str, str]:
    """按 EMBEDDING_MODE 返回 (base_url, api_key, model)；需应用上下文。"""
    config = current_app.config
    mode = config.get("EMBEDDING_MODE", "local")
    if mode == "cloud":
        return (
            config["EMBEDDING_BASE_URL"],
            config["EMBEDDING_API_KEY"],
            config["EMBEDDING_MODEL"],
        )
    if mode == "auto" and all(
        (config.get(key) or "").strip()
        for key in ("EMBEDDING_BASE_URL", "EMBEDDING_API_KEY", "EMBEDDING_MODEL")
    ):
        return (
            config["EMBEDDING_BASE_URL"],
            config["EMBEDDING_API_KEY"],
            config["EMBEDDING_MODEL"],
        )
    return (
        config.get("EMBEDDING_LOCAL_BASE_URL", ""),
        "local",  # 本地侧车不校验 api_key，但 OpenAI 客户端要求非空
        config.get("EMBEDDING_LOCAL_MODEL", ""),
    )


def _embed_batch(base_url: str, api_key: str, model: str, texts: list[str]) -> list[list[float]]:
    """单批向量化（一次真实请求；超时/重试参数见模块常量）。"""
    from openai import DefaultHttpxClient, OpenAI

    direct = _is_loopback(base_url)
    http_client = (
        DefaultHttpxClient(trust_env=False, timeout=TIMEOUT_S) if direct else None
    )
    try:
        client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=TIMEOUT_S,
            max_retries=0,  # SDK 内建重试关闭，重试语义由本模块自行控制
            http_client=http_client,
        )
        response = client.embeddings.create(input=texts, model=model)
        return [item.embedding for item in response.data]
    finally:
        if http_client is not None:
            http_client.close()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量向量化：按 ``BATCH_SIZE`` 自动分批，单批超时 10s 失败重试 1 次。

    任一批最终失败即整体抛异常（调用方按各自语义降级/进重试队列）；
    返回顺序与输入一致。空输入返回空列表（不发请求）。
    """
    if not texts:
        return []
    base_url, api_key, model = _resolve_endpoint()
    if not base_url.strip() or not model.strip():
        raise ValueError("embedding 端点配置不完整（base_url/model 为空）")

    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start : start + BATCH_SIZE]
        last_exc: Exception | None = None
        for attempt in range(RETRIES + 1):
            try:
                vectors.extend(_embed_batch(base_url, api_key, model, batch))
                last_exc = None
                break
            except Exception as exc:  # noqa: BLE001 - 网络类异常统一重试
                last_exc = exc
                if attempt < RETRIES:
                    logger.warning(
                        "embedding 请求失败（第 %s 次重试前）: %s", attempt + 1, exc
                    )
        if last_exc is not None:
            raise last_exc
    return vectors


def is_available() -> tuple[bool, str]:
    """快速探测 embedding 端点可用性，``(ok, reason)`` 供降级判定。

    探测语义：配置完整性检查 + 端点 TCP 可达（``_PROBE_TIMEOUT_S``），
    不发真实向量化请求（与探活的「单条真实请求」语义区分，见模块
    docstring）。探测通过但真实调用仍可能失败——搜索/推荐的降级判定
    是 ``is_available`` + 异常**双判定**，异常路径同样落降级。
    """
    try:
        base_url, _api_key, model = _resolve_endpoint()
    except Exception as exc:  # noqa: BLE001 - 探测吞掉一切异常并如实上报
        return False, f"embedding 配置读取失败: {exc}"
    if not base_url.strip() or not model.strip():
        return False, "embedding 端点配置不完整（base_url/model 为空）"
    parsed = urlparse(base_url)
    host, port = parsed.hostname, parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    try:
        with socket.create_connection((host, port), timeout=_PROBE_TIMEOUT_S):
            pass
    except OSError as exc:
        return False, f"embedding 端点不可达（{host}:{port}）: {exc}"
    return True, "ok"
