"""MongoDB 客户端（b2be2）：懒初始化单例，全项目仅本模块 import pymongo。

其他模块一律经 ``get_db()`` 取 ``Database`` 句柄（``user_profiles`` /
``user_behaviors`` / ``product_vectors`` 三集合所在库）。懒初始化语义与
``redis_client`` 一致：本函数不触网，首次真实命令才建连接，超时由
``serverSelectionTimeoutMS=2000`` 兜底，调用方按各自降级语义处理失败
（向量同步进重试队列、推荐降级全随机）。
"""

from __future__ import annotations

from flask import current_app
from pymongo import MongoClient
from pymongo.database import Database

# Mongo 服务端选择超时（毫秒）：本机容器应毫秒级应答，2s 足够且防挂死
_SERVER_SELECTION_TIMEOUT_MS = 2000

# 懒初始化单例：连接与其建连签名（配置变化时重建）
_client: MongoClient | None = None
_signature: tuple[str, str] | None = None


def get_db() -> Database:
    """返回配置库名对应的 ``Database``（需在应用上下文内调用，读 app.config）。

    同签名复用已建连接；Mongo 不可用时首次真实命令抛异常，由调用方
    降级。测试经 monkeypatch 本函数注入内存桩（见 tests/conftest.py）。
    """
    global _client, _signature
    config = current_app.config
    signature = (config["MONGO_URI"], config["MONGO_DB"])
    if _client is None or _signature != signature:
        _client = MongoClient(
            signature[0], serverSelectionTimeoutMS=_SERVER_SELECTION_TIMEOUT_MS
        )
        _signature = signature
    return _client[signature[1]]
