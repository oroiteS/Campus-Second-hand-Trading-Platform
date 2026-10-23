"""行为流水与用户画像更新（b2be2）：点击 0.82 / 收藏 0.70，购买 0.55 属 b3。

规则（需求「用户画像更新」节，任务卡钉死）：

1. **流水无条件记录**（``user_behaviors`` 只增不改）；
2. 同一 (user_id, product_id, action) 24h 内第二次起**跳过画像更新**
   （流水照记）；
3. 更新公式 ``new = product_vec × (1-w) + old × w``；无画像时
   ``new = product_vec``（w=0 特例，避免零向量污染）；
4. **L2 归一化**后 upsert ``user_profiles``（模长恒 1，与 Chroma 余弦
   距离同构），``behavior_count`` 递增（用于判断脱离冷启动）。

取消收藏（favorited=False）仅记流水、不更新画像——权重公式只会把画像
拉向商品，没有「拉离」语义（任务卡未定义负向更新，b3 购买接入时再议）。
商品向量缺失时现场 ``embed_texts`` 补算；补算失败则本次画像更新跳过
（向量侧已有重试队列补偿，此处不重复入队）。
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta

from flask import current_app

from src.common import embedding_client, mongo_client
from src.services.vector_service import CST, build_text, now_cst

logger = logging.getLogger(__name__)

# 行为权重（需求「用户画像更新」节；购买 0.55 属 b3 订单接入时扩展）
ACTION_WEIGHTS = {"view": 0.82, "favorite": 0.70}
# 画像去重窗口（小时）：同 (user, product, action) 窗口内只更新一次画像
DEDUP_HOURS = 24


def _collections():
    database = mongo_client.get_db()
    return database["user_behaviors"], database["user_profiles"]


def _product_vector(product) -> list[float] | None:
    """取商品向量：Mongo 权威副本优先，缺失时现场补算（失败返回 None）。"""
    collection = mongo_client.get_db()["product_vectors"]
    doc = collection.find_one({"product_id": int(product.id)})
    if doc is not None:
        return list(doc["vector"])
    try:
        category = product.category
        category_name = category.name if category is not None else ""
        vector = embedding_client.embed_texts([build_text(product, category_name)])[0]
    except Exception as exc:  # noqa: BLE001 - 补算失败：跳过本次画像更新
        logger.warning(
            "商品向量缺失且补算失败，画像更新跳过 product_id=%s: %s", product.id, exc
        )
        return None
    dim = current_app.config["EMBEDDING_DIM"]
    if len(vector) != dim:
        logger.error("商品向量补算维度不符，画像更新跳过 product_id=%s", product.id)
        return None
    return vector


def _l2_normalize(vector: list[float]) -> list[float]:
    """L2 归一化（模长恒 1，AC-08）；零向量防御性原样返回。"""
    norm = math.sqrt(sum(component * component for component in vector))
    if norm == 0:
        return vector
    return [component / norm for component in vector]


def _update_profile(user_id: int, product, weight: float, action: str) -> None:
    """画像更新（调用方已完成去重判定）；向量不可得时静默跳过。"""
    product_vector = _product_vector(product)
    if product_vector is None:
        return
    behaviors, profiles = _collections()
    profile = profiles.find_one({"user_id": user_id})
    if profile is None:
        new_vector = product_vector  # 无画像：new = product_vec（w=0 特例）
        behavior_count = 1
    else:
        old = profile["vector"]
        new_vector = [
            product_component * (1 - weight) + old_component * weight
            for product_component, old_component in zip(
                product_vector, old, strict=False
            )
        ]
        behavior_count = int(profile.get("behavior_count", 0)) + 1
    profiles.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "vector": _l2_normalize(new_vector),
                "dim": current_app.config["EMBEDDING_DIM"],
                "model": embedding_client.active_model(),
                "behavior_count": behavior_count,
                "updated_at": now_cst(),
            }
        },
        upsert=True,
    )


def _record(user_id: int, product, action: str, source: str, favorited: bool = True) -> None:
    """流水无条件记录 + 画像 24h 去重更新（收藏取消仅记流水）。"""
    weight = ACTION_WEIGHTS[action]
    behaviors, _profiles = _collections()
    cutoff = datetime.now(CST) - timedelta(hours=DEDUP_HOURS)
    dedup_hit = (
        behaviors.find_one(
            {
                "user_id": user_id,
                "product_id": int(product.id),
                "action": action,
                "created_at": {"$gte": cutoff},
            }
        )
        is not None
    )
    behaviors.insert_one(
        {
            "user_id": user_id,
            "product_id": int(product.id),
            "action": action,
            "weight": weight,
            "school_id": int(product.school_id),
            "source": source,
            "created_at": now_cst(),
        }
    )
    if dedup_hit:
        logger.info(
            "画像 24h 去重跳过（流水已记）user_id=%s product_id=%s action=%s",
            user_id,
            product.id,
            action,
        )
        return
    if not favorited:
        return  # 取消收藏：仅流水，不更新画像
    _update_profile(user_id, product, weight, action)


def record_view(user_id: int, product) -> None:
    """点击行为（PRODUCT_VIEWED 订阅入口）：流水 + 画像（w=0.82）。"""
    _record(user_id, product, "view", source="detail")


def record_favorite(user_id: int, product, favorited: bool) -> None:
    """收藏/取消行为（FAVORITE_CHANGED 订阅入口）：流水；仅收藏更新画像。"""
    _record(user_id, product, "favorite", source="favorite", favorited=favorited)
