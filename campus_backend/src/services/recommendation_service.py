"""首页推荐服务（b2be2）：画像召回 32 + 随机补 8，冷启动全随机 40。

流程（契约 §3.5 / 需求「首页推荐」节）：缓存未命中（或 ``refresh=True``）
时计算——① ``user_profiles`` 无文档（冷启动）→ 全随机 40；② 有画像 →
Chroma ``query(user_vector, n_results=90, where 本校+on_sale)`` 召回 →
过滤自己发布 / 非 on_sale（保底）/ 批内 id 去重 → 取前 32 → 随机补足缺
口 → 合并（不足即实际数）；③ 写缓存 ``product:home:{school}:{user}``
（``scoped_key``，商品库 offset=2）TTL 300s。随机路径（冷启动 / 随机
补足 / 降级）均排除自家在售商品（需求「首页推荐排除自己发布」）。

降级矩阵：embedding / chroma / mongo 任一不可用 → 全随机 + ``degraded:
true`` + reason（**Redis 不可用 → 跳过缓存直算，不算 degraded**）；管理
员 → ``{"items": []}``（无推荐语义）。「纯随机冒充推荐」反目标：有画像
用户必经画像向量召回路径，全随机仅出现在冷启动与显式降级。
"""

from __future__ import annotations

import json
import logging

from flask import g

from src.common import chroma_client, embedding_client, mongo_client, redis_client
from src.common.auth import scoped_key
from src.common.redis_client import PRODUCT_DB_OFFSET
from src.model import Product, db
from src.services import product_service

logger = logging.getLogger(__name__)

# 配比常量（AC-07）：画像召回目标 / 总数 / 缓存 TTL / 召回候选数
PROFILE_TARGET = 32
FEED_TOTAL = 40
CACHE_TTL_S = 300
RECALL_LIMIT = 90


def _cache_key(user) -> str:
    """``product:home:{school}:{user}``（scoped_key 含 school 与 user）。"""
    return scoped_key("product:home", g.school_id, user.id)


def _serialize(products: list) -> list[dict]:
    return [p.to_summary_dict() for p in products]


def _own_on_sale_ids(user) -> list[int]:
    """用户全部自家 on_sale 商品 id（随机路径排除自家发布，需求「首页推荐」节）。"""
    rows = db.session.query(Product.id).filter_by(seller_id=user.id, status="on_sale").all()
    return [row[0] for row in rows]


def _random_feed(user, exclude_ids: list[int], limit: int = FEED_TOTAL) -> list:
    return product_service.list_on_sale_random(g.school_id, exclude_ids, limit, scope_all=False)


def _read_cache(user) -> list[dict] | None:
    """读缓存；Redis 不可用返回 None（直算，不算 degraded）。"""
    try:
        raw = redis_client.get_redis(PRODUCT_DB_OFFSET).get(_cache_key(user))
    except Exception as exc:  # noqa: BLE001 - Redis 降级：跳过缓存
        logger.warning("推荐缓存读取失败，直算 key=%s: %s", _cache_key(user), exc)
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("推荐缓存反序列化失败，按未命中处理 key=%s", _cache_key(user))
        return None


def _write_cache(user, items: list[dict]) -> None:
    try:
        redis_client.get_redis(PRODUCT_DB_OFFSET).setex(
            _cache_key(user), CACHE_TTL_S, json.dumps(items, ensure_ascii=False)
        )
    except Exception as exc:  # noqa: BLE001 - 缓存降级：可用性优先
        logger.warning("推荐缓存写入失败 key=%s: %s", _cache_key(user), exc)


def _profile_vector(user_id: int) -> list[float] | None:
    """读画像向量；无文档返回 None（冷启动），故障上抛（降级矩阵处理）。"""
    profile = mongo_client.get_db()["user_profiles"].find_one({"user_id": user_id})
    if profile is None:
        return None
    return list(profile["vector"])


def _recall_by_profile(user, user_vector: list[float]) -> list:
    """画像召回：Chroma where 本校+on_sale → 过滤自己发布/非在售/重复 → 前 32。"""
    where = {"$and": [{"school_id": int(g.school_id)}, {"status": "on_sale"}]}
    response = chroma_client.get_collection().query(
        query_embeddings=[user_vector], n_results=RECALL_LIMIT, where=where
    )
    ids: list[int] = []
    for raw_id in response["ids"][0]:
        product_id = int(raw_id)
        if product_id not in ids:  # 批内 id 去重
            ids.append(product_id)
    products = product_service.get_on_sale_by_ids(g.school_id, ids, scope_all=False)
    filtered = [
        p
        for p in products
        if p.seller_id != user.id and p.status == "on_sale"  # 保底再滤非在售
    ]
    return filtered[:PROFILE_TARGET]


def _degraded_random(user, reason: str, exclude_ids: list[int]) -> dict:
    logger.info("推荐降级 user_id=%s: %s", user.id, reason)
    items = _serialize(_random_feed(user, exclude_ids))
    return {
        "items": items,
        "degraded": True,
        "degraded_reason": reason,
    }


def _compute(user) -> dict:
    """缓存未命中路径的完整计算（含降级矩阵与缓存回写）。"""
    # ---- 降级探测：mongo → embedding/chroma（任一不可用 → 全随机 + degraded）----
    own_ids = _own_on_sale_ids(user)  # 自家 on_sale ⊂ 本校 on_sale，随机路径一并排除
    try:
        user_vector = _profile_vector(user.id)
    except Exception as exc:  # noqa: BLE001 - Mongo 不可用
        return _degraded_random(user, f"画像存储不可用，已降级为随机推荐: {exc}", own_ids)
    if user_vector is None:
        # 冷启动：全随机 40（正常路径，无 degraded 标记）
        items = _serialize(_random_feed(user, own_ids))
    else:
        available, probe_reason = embedding_client.is_available()
        if not available:
            return _degraded_random(
                user, f"embedding 不可用（{probe_reason}），已降级为随机推荐", own_ids
            )
        try:
            recalled = _recall_by_profile(user, user_vector)
        except Exception as exc:  # noqa: BLE001 - Chroma/embedding 真实调用异常
            return _degraded_random(
                user, f"画像召回异常，已降级为随机推荐: {type(exc).__name__}: {exc}", own_ids
            )
        exclude_ids = list({*own_ids, *(p.id for p in recalled)})
        random_fill = product_service.list_on_sale_random(
            g.school_id, exclude_ids, FEED_TOTAL - len(recalled), scope_all=False
        )
        items = _serialize(recalled + random_fill)  # 召回不足随机补齐（含随机 8 池）
    _write_cache(user, items)
    return {"items": items}


def home_feed(user, refresh: bool = False) -> dict:
    """``GET /api/recommendations/home`` 主入口。

    管理员 → 空列表 200（无推荐语义，不查缓存不计算）；学生走缓存 →
    计算（``refresh=True`` 绕过缓存强制重算，「换一批」）。
    """
    if user.role == "admin":
        return {"items": []}
    if not refresh:
        cached = _read_cache(user)
        if cached is not None:
            return {"items": cached}
    return _compute(user)
