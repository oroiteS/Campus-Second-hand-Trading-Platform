"""向量重试补偿线程（b2be2）：60s 周期重放 ``queue:vector:retry``。

重放语义（消息只含 ``product_id``，动作按 MySQL 现状判定，天然幂等）：

- 商品仍存在（非 deleted）→ ``vector_service.attempt_sync`` 严格重放；
  失败且消息龄 > 24h → 丢弃 + error 日志（防死信堆积），否则原样回队
  （**保留原 ts**——龄期不因重放重置，保证超龄消息终被丢弃）；
- 商品已删除/不存在 → ``remove_product`` 补删（双删幂等）。

启动：``create_app()`` 内按 ``VECTOR_RETRY_WORKER``（默认开）条件启动；
TESTING 跳过（app.py 仅 3 行，循环逻辑全部在本模块）。线程自带应用
上下文与异常兜底，任何单轮失败不影响下一轮。
"""

from __future__ import annotations

import json
import logging
import threading
import time

from flask import Flask

from src.common import redis_client
from src.common.redis_client import SYSTEM_DB_OFFSET
from src.services import vector_service
from src.services.product_service import get_active_by_id

logger = logging.getLogger(__name__)

# 重放周期（秒）与单轮批量上限（LPOP 逐条，最多取 limit 条）
INTERVAL_S = 60
BATCH_LIMIT = 100


def process_once(app: Flask, *, limit: int = BATCH_LIMIT) -> dict:
    """单轮重放：返回 ``{"replayed", "dropped", "failed"}``（需应用上下文内
    的 app 引用即可，本函数自建上下文）。"""
    with app.app_context():
        queue = redis_client.get_redis(SYSTEM_DB_OFFSET).lpop
        rpush = redis_client.get_redis(SYSTEM_DB_OFFSET).rpush
        replayed = dropped = failed = 0
        attempted: set[int] = set()  # 本轮已处理 product_id：失败回队消息不再重弹
        for _ in range(limit):
            raw = queue(vector_service.VECTOR_RETRY_QUEUE_KEY)
            if raw is None:
                break
            try:
                message = json.loads(raw)
                product_id = int(message["product_id"])
                ts = int(message.get("ts", 0))
            except (TypeError, ValueError, KeyError):
                dropped += 1
                logger.error("向量重试消息不可解析，丢弃: %r", raw)
                continue
            if product_id in attempted:
                # 本轮失败回队的消息轮到队首：放回并结束本轮（下轮再重放）
                rpush(vector_service.VECTOR_RETRY_QUEUE_KEY, raw)
                break
            product = get_active_by_id(product_id)
            attempted.add(product_id)
            if product is None:
                # 商品已删除/不存在：补偿删除（幂等）
                vector_service.remove_product(product_id)
                replayed += 1
                continue
            try:
                vector_service.attempt_sync(product)
                replayed += 1
            except vector_service.VectorDimMismatch as exc:
                # 维度错误重试无法修复：丢弃 + error 日志
                dropped += 1
                logger.error("%s", exc)
            except Exception:  # noqa: BLE001 - 重放失败按龄期回队或丢弃
                failed += 1
                age = time.time() - ts
                if age > vector_service.RETRY_MAX_AGE_S:
                    dropped += 1
                    logger.error(
                        "向量重试超 24h 仍失败，丢弃 product_id=%s（龄 %.0fs）",
                        product_id,
                        age,
                    )
                else:
                    rpush(
                        vector_service.VECTOR_RETRY_QUEUE_KEY,
                        json.dumps({"product_id": product_id, "ts": ts}),
                    )
        if replayed or dropped or failed:
            logger.info(
                "向量重试轮完成 replayed=%s dropped=%s failed=%s",
                replayed,
                dropped,
                failed,
            )
        return {"replayed": replayed, "dropped": dropped, "failed": failed}


def start_worker(app: Flask) -> threading.Thread:
    """启动 daemon 补偿线程（每 60s 一轮；单轮异常兜底，不影响下一轮）。"""

    def _loop() -> None:
        while True:
            time.sleep(INTERVAL_S)
            try:
                process_once(app)
            except Exception:  # noqa: BLE001 - 线程常驻：单轮失败仅日志
                logger.exception("向量重试补偿线程单轮异常")

    thread = threading.Thread(target=_loop, name="vector-retry-worker", daemon=True)
    thread.start()
    return thread
