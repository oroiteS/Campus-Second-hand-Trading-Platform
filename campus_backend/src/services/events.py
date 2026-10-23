"""进程内事件总线（b2be → b2be2 的接力契约，签名不得偏离任务卡 Interfaces 节）。

全部事件 **先 commit 后 emit**：订阅者拿到的数据已持久化；单个订阅者异常
捕获并 error 日志，绝不影响主流程（事务已完成）。b2be 自身不订阅任何事件
（向量/画像/行为订阅者属 b2be2，未订阅时 emit 安全 no-op）。

事件名常量与载荷（b2be 在下述时点 emit）::

    PRODUCT_PUBLISHED      (product)                    发布 commit 后
    PRODUCT_UPDATED        (product, changed: set[str]) 编辑 commit 后
    PRODUCT_DELETED        (product_id: int)            删除 commit 后
    PRODUCT_STATUS_CHANGED (product, old_status: str)   上下架 commit 后
    PRODUCT_VIEWED         (user_id: int, product)      详情 200 组装前
    FAVORITE_CHANGED       (user_id: int, product, favorited: bool)

``changed`` 为本次编辑实际变化的字段名集合（比对请求与原值）；
``image_ids`` 变化不进该集合——向量订阅方不关心图片。
"""

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

# ---- 事件名常量（b2be2 按名订阅；漂移即阻断级缺陷）----
PRODUCT_PUBLISHED = "product.published"
PRODUCT_UPDATED = "product.updated"
PRODUCT_DELETED = "product.deleted"
PRODUCT_STATUS_CHANGED = "product.status_changed"
PRODUCT_VIEWED = "product.viewed"
FAVORITE_CHANGED = "favorite.changed"

_HANDLERS: dict[str, list[Callable]] = {}


def subscribe(event: str, handler: Callable) -> None:
    """登记订阅者（进程内；按登记顺序调用）。"""
    _HANDLERS.setdefault(event, []).append(handler)


def emit(event: str, *args: object) -> None:
    """逐个调用订阅者；单个订阅者异常捕获并 error 日志，绝不影响主流程
    （事务已完成）。未订阅的事件安全 no-op。"""
    for handler in _HANDLERS.get(event, []):
        try:
            handler(*args)
        except Exception:  # noqa: BLE001 - 订阅者异常隔离是总线契约本身
            logger.exception("事件订阅者异常（event=%s handler=%s）", event, handler)
