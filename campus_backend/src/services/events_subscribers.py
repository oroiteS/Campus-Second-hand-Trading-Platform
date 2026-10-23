"""b2be 事件总线订阅接线（b2be2）：向量同步、行为画像与 Mongo 索引初始化。

``register_all()`` 幂等（重复调用不重复注册），由 ``router.py`` 末尾
接线（调用点以 ``app.app_context()`` 包裹，保证 ``ensure_indexes`` 读
得 ``app.config``）；b3 订单接入购买行为（w=0.55）时在
此扩展，不动总线。订阅者异常由 ``events.emit`` 隔离，绝不影响主流程
200（b2be 保证先 commit 后 emit）。

事件 → 处理路由（任务卡钉死）：

- PRODUCT_PUBLISHED        → vector_service.sync_product（全量）
- PRODUCT_UPDATED          → changed 含模板字段（title/description/
  category_id/condition）→ sync_product；否则（仅 price/campus_id 等）
  → update_status_metadata（不重算向量）
- PRODUCT_DELETED          → remove_product（双删）
- PRODUCT_STATUS_CHANGED   → update_status_metadata（metadata 局部更新）
- PRODUCT_VIEWED           → behavior_service.record_view
- FAVORITE_CHANGED         → behavior_service.record_favorite
"""

from __future__ import annotations

import logging

from src.services import behavior_service, events, vector_service

logger = logging.getLogger(__name__)

# 编辑 changed 集合中出现即重建向量（模板文本组成字段）；否则仅 metadata
_TEMPLATE_FIELDS = {"title", "description", "category_id", "condition"}

_registered = False


def ensure_indexes() -> None:
    """Mongo 三集合索引幂等初始化（任务卡：随 register_all 执行）。

    - user_profiles.user_id 唯一；product_vectors.product_id 唯一；
    - user_behaviors (user_id, created_at) 复合与 product_id 单列。
    Mongo 不可用时仅告警不阻断启动（索引在补偿线程/首次写入场景由
    运维重建预案兜底）。
    """
    from src.common import mongo_client

    try:
        database = mongo_client.get_db()
        database["user_profiles"].create_index("user_id", unique=True)
        database["product_vectors"].create_index("product_id", unique=True)
        database["user_behaviors"].create_index(["user_id", "created_at"])
        database["user_behaviors"].create_index("product_id")
    except Exception as exc:  # noqa: BLE001 - 索引失败不阻断应用启动
        logger.warning("Mongo 索引初始化失败（启动容错）: %s", exc)


def _on_published(product) -> None:
    vector_service.sync_product(product)


def _on_updated(product, changed: set[str]) -> None:
    if changed & _TEMPLATE_FIELDS:
        vector_service.sync_product(product)
    else:
        vector_service.update_status_metadata(product)


def _on_deleted(product_id: int) -> None:
    vector_service.remove_product(product_id)


def _on_status_changed(product, old_status: str) -> None:
    _ = old_status  # 载荷保留（b3 订单流转可能需要来源态）
    vector_service.update_status_metadata(product)


def _on_viewed(user_id: int, product) -> None:
    behavior_service.record_view(user_id, product)


def _on_favorite_changed(user_id: int, product, favorited: bool) -> None:
    behavior_service.record_favorite(user_id, product, favorited)


def register_all() -> None:
    """幂等注册全部订阅并初始化 Mongo 索引（b3 扩展点）。"""
    global _registered
    if _registered:
        return
    ensure_indexes()
    events.subscribe(events.PRODUCT_PUBLISHED, _on_published)
    events.subscribe(events.PRODUCT_UPDATED, _on_updated)
    events.subscribe(events.PRODUCT_DELETED, _on_deleted)
    events.subscribe(events.PRODUCT_STATUS_CHANGED, _on_status_changed)
    events.subscribe(events.PRODUCT_VIEWED, _on_viewed)
    events.subscribe(events.FAVORITE_CHANGED, _on_favorite_changed)
    _registered = True
    logger.info("b2be2 事件订阅注册完成（6 事件）")


def _reset_for_tests() -> None:
    """仅供测试：清空注册态与订阅表。"""
    global _registered
    _registered = False
    events._HANDLERS.clear()
