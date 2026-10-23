"""Chroma 客户端（b2be2）：懒初始化单例，全项目仅本模块 import chromadb。

集合名 = ``product_vectors`` + ``CHROMA_COLLECTION_SUFFIX``（worktree 隔离），
度量 ``cosine``（需求「Chroma 集合」节）。懒初始化语义与 ``redis_client``/
``mongo_client`` 一致：``get_collection()`` 首次调用才建连接与集合，失败
由调用方按降级语义处理（搜索 LIKE 降级、推荐全随机 + degraded）。
"""

from __future__ import annotations

from typing import Any

from flask import current_app

# 懒初始化单例：HttpClient、其建连签名与集合句柄（配置变化时重建）
_client: Any = None
_signature: tuple[str, int, str] | None = None
_collection: Any = None


def _collection_name(suffix: str) -> str:
    """Chroma 集合名：基础名 + worktree 隔离后缀（主仓后缀为空）。"""
    return f"product_vectors{suffix}"


def get_collection() -> Any:
    """返回商品向量集合（``get_or_create``，需在应用上下文内调用）。

    metadata 固定 ``{"hnsw:space": "cosine"}``——余弦距离是画像与搜索
    的一致性口径（需求：画像 L2 归一化后与 Chroma 余弦距离同构）。
    测试经 monkeypatch 本函数注入内存桩（见 tests/conftest.py）。
    """
    global _client, _signature, _collection
    config = current_app.config
    signature = (
        config["CHROMA_HOST"],
        config["CHROMA_PORT"],
        config["CHROMA_COLLECTION_SUFFIX"],
    )
    if _client is None or _signature != signature:
        import chromadb

        _client = chromadb.HttpClient(host=signature[0], port=signature[1])
        _signature = signature
        _collection = None
    if _collection is None:
        _collection = _client.get_or_create_collection(
            name=_collection_name(signature[2]),
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def delete_collection() -> None:
    """删除商品向量集合（rebuild_all 重建与收尾清理用；未初始化则静默）。"""
    global _collection
    if _client is None or _signature is None:
        return
    _client.delete_collection(name=_collection_name(_signature[2]))
    _collection = None
