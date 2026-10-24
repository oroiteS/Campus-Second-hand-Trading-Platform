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
import time

from src.services import behavior_service, events, vector_service

logger = logging.getLogger(__name__)

# 编辑 changed 集合中出现即重建向量（模板文本组成字段）；否则仅 metadata
_TEMPLATE_FIELDS = {"title", "description", "category_id", "condition"}

# 索引补建重试最小间隔（S-3）：请求路径兜底不得每请求打 Mongo
_INDEX_RETRY_INTERVAL_S = 60.0

_registered = False
# 索引「待补建」标记：初始化失败时置位，由请求路径/补偿线程重试（S-3/S-5）
_indexes_pending = False
# 上一次补建尝试的 monotonic 时刻（双闸之一：60s 内不重复尝试）
_last_index_attempt = 0.0


def ensure_indexes() -> bool:
    """Mongo 三集合索引幂等初始化（任务卡：随 register_all 执行）。

    - user_profiles.user_id 唯一；product_vectors.product_id 唯一；
    - user_behaviors (user_id, created_at) 复合与 product_id 单列。
    Mongo 不可用时仅告警不阻断启动，并置「待补建」标记——订阅注册与索引
    初始化解耦：事件不会因 Mongo down 丢失，索引由请求路径兜底与补偿
    线程补建（S-3/S-5）。

    返回是否成功（``True`` 成功 / ``False`` 失败待补建）。
    """
    global _indexes_pending
    from src.common import mongo_client

    try:
        database = mongo_client.get_db()
        database["user_profiles"].create_index("user_id", unique=True)
        database["product_vectors"].create_index("product_id", unique=True)
        database["user_behaviors"].create_index(["user_id", "created_at"])
        database["user_behaviors"].create_index("product_id")
    except Exception as exc:  # noqa: BLE001 - 索引失败不阻断应用启动
        _indexes_pending = True
        logger.warning("Mongo 索引初始化失败（待补偿线程补建）: %s", exc)
        return False
    _indexes_pending = False
    return True


def indexes_pending() -> bool:
    """索引是否仍处于「待补建」状态（补偿线程与测试用）。"""
    return _indexes_pending


def ensure_indexes_if_pending() -> bool:
    """按需补建：**双闸**——未 pending 立即返回；距上次尝试 <60s 也跳过。

    由请求路径（``app.before_request``，S-3）与补偿线程（S-5）共用：
    ``VECTOR_RETRY_WORKER=0`` 时启动失败的索引仍能在首个请求补建，同时
    不会每个请求都打 Mongo。返回是否处于「已建好」状态。
    """
    global _last_index_attempt
    if not _indexes_pending:
        return True
    now = time.monotonic()
    if now - _last_index_attempt < _INDEX_RETRY_INTERVAL_S:
        return False
    _last_index_attempt = now
    return ensure_indexes()


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
    """幂等注册全部订阅并初始化 Mongo 索引（b3 扩展点）。

    订阅先注册（事件不因索引失败丢失），索引失败仅标记待补建。
    """
    global _registered
    if _registered:
        return
    events.subscribe(events.PRODUCT_PUBLISHED, _on_published)
    events.subscribe(events.PRODUCT_UPDATED, _on_updated)
    events.subscribe(events.PRODUCT_DELETED, _on_deleted)
    events.subscribe(events.PRODUCT_STATUS_CHANGED, _on_status_changed)
    events.subscribe(events.PRODUCT_VIEWED, _on_viewed)
    events.subscribe(events.FAVORITE_CHANGED, _on_favorite_changed)
    ensure_indexes()
    _registered = True
    logger.info("b2be2 事件订阅注册完成（6 事件）")


def _reset_for_tests() -> None:
    """仅供测试：清空注册态、待补建标记、重试时刻与订阅表。"""
    global _registered, _indexes_pending, _last_index_attempt
    _registered = False
    _indexes_pending = False
    _last_index_attempt = 0.0
    events._HANDLERS.clear()
