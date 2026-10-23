"""向量同步服务（b2be2）：模板文本、Mongo 权威副本与 Chroma 索引双写。

一致性约定（需求「向量一致性」节，任务卡钉死）：先写 Mongo
``product_vectors``（权威副本）再 upsert Chroma（派生索引）；任一步失败
→ Redis ``queue:vector:retry``（**系统库 offset=3**，任务卡指定）RPUSH
``{"product_id", "ts"}`` + error 日志，**绝不影响发布/编辑/收藏的 200**。
维度与 ``EMBEDDING_DIM`` 不符 → 拒写 + error 日志（切模型须重建，不得混
维，不进重试队列——重试无法修复维度错误）。

模板文本照需求原文四行（标题/分类/成色/描述）；``成色`` 取契约枚举原值
（``excellent`` 等——模型多语混合语料，枚举原值与中文标签语义等价且
判重更稳定）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timedelta, timezone

from flask import current_app

from src.common import chroma_client, embedding_client, mongo_client, redis_client
from src.common.redis_client import SYSTEM_DB_OFFSET
from src.model import Product, db

logger = logging.getLogger(__name__)

# 向量重试队列键与所在库偏移（系统库 offset=3，任务卡「向量同步」节）
VECTOR_RETRY_QUEUE_KEY = "queue:vector:retry"
# 重试消息最长存活：超过即丢弃 + error 日志（防死信堆积）
RETRY_MAX_AGE_S = 24 * 3600

# 统一东八区（与 model.py 时间口径一致）
_CST = timezone(timedelta(hours=8))


class VectorDimMismatch(ValueError):
    """embedding 返回维度与 EMBEDDING_DIM 不符（拒写，不进重试队列）。"""


def _now() -> datetime:
    return datetime.now(_CST)


def build_text(product: Product, category_name: str) -> str:
    """固定模板四行拼接（需求「商品向量化」节原文）。"""
    return (
        f"标题：{product.title}\n"
        f"分类：{category_name}\n"
        f"成色：{product.condition}\n"
        f"描述：{product.description}"
    )


def text_hash(text: str) -> str:
    """模板文本 SHA-256（编辑判变：未变跳过重建）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _category_name(product: Product) -> str:
    category = product.category
    return category.name if category is not None else ""


def _product_metadata(product: Product) -> dict:
    """Chroma metadata（需求「Chroma 集合」节六字段）。

    campus_id 可空而 Chroma metadata 不接受 None，空值落哨兵 0（仅作
    过滤/展示辅助，不参与业务语义）。
    """
    return {
        "school_id": int(product.school_id),
        "campus_id": int(product.campus_id) if product.campus_id is not None else 0,
        "category_id": int(product.category_id),
        "price": float(product.price),
        "status": product.status,
        "seller_id": int(product.seller_id),
    }


def _enqueue_retry(product_id: int) -> None:
    """失败向量任务进重试队列（系统库 offset=3；队列写入失败仅日志兜底）。"""
    message = json.dumps({"product_id": int(product_id), "ts": int(time.time())})
    try:
        redis_client.get_redis(SYSTEM_DB_OFFSET).rpush(VECTOR_RETRY_QUEUE_KEY, message)
    except Exception as exc:  # noqa: BLE001 - 队列不可用：日志兜底，不再上抛
        logger.error("向量重试队列写入失败 product_id=%s: %s", product_id, exc)


def attempt_sync(product: Product) -> None:
    """严格同步：失败上抛（worker 重放与 rebuild_all 用，便于计数/保龄）。

    流程：模板文本 → text_hash 与 Mongo 存量比对（未变且 metadata 未变
    跳过，不调 embedding）→ embed_texts → Mongo upsert → Chroma upsert。
    """
    text = build_text(product, _category_name(product))
    digest = text_hash(text)
    metadata = _product_metadata(product)
    product_id = int(product.id)

    collection = mongo_client.get_db()["product_vectors"]
    existing = collection.find_one({"product_id": product_id})
    if (
        existing is not None
        and existing.get("text_hash") == digest
        and existing.get("metadata") == metadata
    ):
        return  # 文本与 metadata 均未变化：跳过（不调 embedding）

    vector = embedding_client.embed_texts([text])[0]
    dim = current_app.config["EMBEDDING_DIM"]
    if len(vector) != dim:
        # 拒写 + error 日志；不进重试队列（重试无法修复维度错误）
        raise VectorDimMismatch(
            f"向量维度不符（got {len(vector)}, expect {dim}），拒写 product_id={product_id}"
        )
    model = embedding_client.active_model()

    # 先 Mongo（权威副本）后 Chroma（派生索引）
    collection.update_one(
        {"product_id": product_id},
        {
            "$set": {
                "vector": vector,
                "dim": len(vector),
                "model": model,
                "text_hash": digest,
                "school_id": int(product.school_id),
                "status": product.status,
                "metadata": metadata,
                "updated_at": _now(),
            }
        },
        upsert=True,
    )
    chroma_client.get_collection().upsert(
        ids=[str(product_id)],
        embeddings=[vector],
        documents=[text],
        metadatas=[metadata],
    )


def sync_product(product: Product) -> None:
    """事件入口用的安全同步：任何失败转重试队列 + error 日志，不上抛。"""
    try:
        attempt_sync(product)
    except VectorDimMismatch as exc:
        logger.error("%s", exc)
    except Exception as exc:  # noqa: BLE001 - 向量失败绝不影响主流程
        logger.error("向量同步失败，进重试队列 product_id=%s: %s", product.id, exc)
        _enqueue_retry(product.id)


def update_status_metadata(product: Product) -> None:
    """仅状态/价格/校区变化：Chroma metadata 局部 update + Mongo 同步。

    不重算向量（text_hash 未变语义）。Mongo 无存量文档（此前同步整体
    失败、补偿未完成）时退化为全量 attempt_sync。任何失败转重试队列。
    """
    product_id = int(product.id)
    try:
        collection = mongo_client.get_db()["product_vectors"]
        doc = collection.find_one({"product_id": product_id})
        if doc is None:
            attempt_sync(product)
            return
        metadata = _product_metadata(product)
        chroma_client.get_collection().update(
            ids=[str(product_id)], metadata=metadata
        )
        collection.update_one(
            {"product_id": product_id},
            {"$set": {"status": product.status, "metadata": metadata, "updated_at": _now()}},
        )
    except Exception as exc:  # noqa: BLE001 - 与 sync_product 同一降级口径
        logger.error("向量 metadata 更新失败，进重试队列 product_id=%s: %s", product_id, exc)
        _enqueue_retry(product_id)


def remove_product(product_id: int) -> None:
    """Mongo delete + Chroma delete（删除事件的补偿；双删幂等）。"""
    product_id = int(product_id)
    try:
        mongo_client.get_db()["product_vectors"].delete_one({"product_id": product_id})
        chroma_client.get_collection().delete(ids=[str(product_id)])
    except Exception as exc:  # noqa: BLE001 - 失败转重试队列（worker 补删）
        logger.error("向量删除失败，进重试队列 product_id=%s: %s", product_id, exc)
        _enqueue_retry(product_id)


def rebuild_all() -> dict:
    """以 MySQL 为准全量重建（b6 种子脚本与 Chroma 损坏重建降级预案）。

    清空 Chroma 集合与 Mongo ``product_vectors`` 后逐件严格同步；单件
    失败计数并进重试队列，不中断整体。返回 ``{"total", "synced", "failed"}``。
    """
    products = list(
        db.session.execute(
            db.select(Product).where(Product.status != "deleted")
        ).scalars()
    )
    total = len(products)
    mongo_client.get_db()["product_vectors"].delete_many({})
    chroma_client.delete_collection()
    synced = failed = 0
    for product in products:
        try:
            attempt_sync(product)
            synced += 1
        except Exception as exc:  # noqa: BLE001 - 单件失败不中断重建
            failed += 1
            logger.error("向量重建失败 product_id=%s: %s", product.id, exc)
            _enqueue_retry(product.id)
    return {"total": total, "synced": synced, "failed": failed}
