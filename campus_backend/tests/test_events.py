"""事件总线测试：签名逐字对齐 Interfaces 节 + 订阅者异常隔离。"""

from src.services import events


class TestEventConstants:
    def test_event_name_constants_match_interface(self):
        """事件名常量与任务卡 Interfaces 节逐字一致（b2be2 依赖）。"""
        assert events.PRODUCT_PUBLISHED == "product.published"
        assert events.PRODUCT_UPDATED == "product.updated"
        assert events.PRODUCT_DELETED == "product.deleted"
        assert events.PRODUCT_STATUS_CHANGED == "product.status_changed"
        assert events.PRODUCT_VIEWED == "product.viewed"
        assert events.FAVORITE_CHANGED == "favorite.changed"


class TestBusBehavior:
    def test_emit_without_subscribers_is_noop(self):
        """未订阅的事件安全 no-op（b2be 内事件恒无订阅者）。"""
        events.emit(events.PRODUCT_PUBLISHED, object())

    def test_subscribe_and_emit_passes_args(self):
        calls: list[tuple] = []
        events.subscribe(events.PRODUCT_DELETED, lambda pid: calls.append(("del", pid)))
        events.emit(events.PRODUCT_DELETED, 42)
        assert calls == [("del", 42)]

    def test_handlers_called_in_subscription_order(self):
        order: list[str] = []
        events.subscribe(events.PRODUCT_VIEWED, lambda *a: order.append("first"))
        events.subscribe(events.PRODUCT_VIEWED, lambda *a: order.append("second"))
        events.emit(events.PRODUCT_VIEWED, 1, object())
        assert order == ["first", "second"]

    def test_subscriber_exception_isolated_and_logged(self, caplog):
        """单个订阅者异常被捕获并 error 日志，不影响后续订阅者。"""
        seen: list[int] = []

        def boom(*args):
            raise RuntimeError("订阅者炸了")

        events.subscribe(events.FAVORITE_CHANGED, boom)
        events.subscribe(events.FAVORITE_CHANGED, lambda uid, p, f: seen.append(uid))
        with caplog.at_level("ERROR", logger="src.services.events"):
            events.emit(events.FAVORITE_CHANGED, 7, object(), True)
        assert seen == [7]  # 后续订阅者照常执行
        assert any("事件订阅者异常" in r.message for r in caplog.records)
