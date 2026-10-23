"""分类域服务：启用分类列表（读侧；维护 CRUD 属批次 5）。

全局表无 school 段，缓存键 ``scoped_key("product:category", "all")`` →
``product:category:all``；TTL 3600s，管理员维护后的失效由 b5 接手。
"""

import json

from flask import current_app

from src.common import redis_client
from src.common.auth import scoped_key
from src.common.redis_client import PRODUCT_DB_OFFSET
from src.model import Category, db

CATEGORY_CACHE_TTL = 3600
_CACHE_KEY = scoped_key("product:category", "all")


def list_enabled() -> list[dict]:
    """全部启用分类（CategoryRef 形态，按 sort_order、id 升序，不分页）。

    返回序列化 dict（缓存一致性：命中路径无 ORM 实体可返）；Redis 故障
    降级直查直算，业务照常。
    """
    try:
        raw = redis_client.get_redis(PRODUCT_DB_OFFSET).get(_CACHE_KEY)
    except Exception as exc:  # noqa: BLE001 - 缓存降级：可用性优先
        current_app.logger.warning("分类缓存读取失败，降级直查: %s", exc)
        raw = None
    if raw is not None:
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            current_app.logger.warning("分类缓存反序列化失败，按未命中处理")
    rows = (
        db.session.query(Category)
        .filter(Category.status == "enabled")
        .order_by(Category.sort_order.asc(), Category.id.asc())
        .all()
    )
    payload = [row.ref_dict() for row in rows]
    try:
        redis_client.get_redis(PRODUCT_DB_OFFSET).setex(
            _CACHE_KEY, CATEGORY_CACHE_TTL, json.dumps(payload, ensure_ascii=False)
        )
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning("分类缓存写入失败: %s", exc)
    return payload
