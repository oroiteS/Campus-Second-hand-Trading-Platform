"""events_subscribers 测试：6 事件 → 服务函数路由正确；register_all 幂等。"""

import pytest

from src.services import events, events_subscribers, vector_service
from tests.conftest import TestConfig


@pytest.fixture()
def captures(monkeypatch, wired_events):
    """桩捕获各订阅目标的调用参数（wired_events 负责注册与清场）。"""
    calls = {
        "sync": [],
        "metadata": [],
        "remove": [],
        "view": [],
        "favorite": [],
    }
    monkeypatch.setattr(
        vector_service, "sync_product", lambda product: calls["sync"].append(product)
    )
    monkeypatch.setattr(
        vector_service,
        "update_status_metadata",
        lambda product: calls["metadata"].append(product),
    )
    monkeypatch.setattr(
        vector_service, "remove_product", lambda pid: calls["remove"].append(pid)
    )
    from src.services import behavior_service

    monkeypatch.setattr(
        behavior_service,
        "record_view",
        lambda user_id, product: calls["view"].append((user_id, product)),
    )
    monkeypatch.setattr(
        behavior_service,
        "record_favorite",
        lambda user_id, product, favorited: calls["favorite"].append(
            (user_id, product, favorited)
        ),
    )
    return calls


class TestEventRouting:
    def test_published_routes_to_sync(self, captures):
        events.emit(events.PRODUCT_PUBLISHED, "P1")
        assert list(captures["sync"]) == ["P1"]
        assert captures["metadata"] == []

    def test_updated_template_fields_route_to_sync(self, captures):
        events.emit(events.PRODUCT_UPDATED, "P1", {"title", "price"})
        assert captures["sync"] == ["P1"]
        events.emit(events.PRODUCT_UPDATED, "P2", {"description"})
        events.emit(events.PRODUCT_UPDATED, "P3", {"category_id"})
        events.emit(events.PRODUCT_UPDATED, "P4", {"condition"})
        assert list(captures["sync"]) == ["P1", "P2", "P3", "P4"]

    def test_updated_non_template_fields_route_to_metadata(self, captures):
        events.emit(events.PRODUCT_UPDATED, "P1", {"price"})
        events.emit(events.PRODUCT_UPDATED, "P2", {"campus_id"})
        events.emit(events.PRODUCT_UPDATED, "P3", {"original_price", "price"})
        assert captures["sync"] == []
        assert list(captures["metadata"]) == ["P1", "P2", "P3"]

    def test_deleted_routes_to_remove(self, captures):
        events.emit(events.PRODUCT_DELETED, 42)
        assert captures["remove"] == [42]

    def test_status_changed_routes_to_metadata(self, captures):
        events.emit(events.PRODUCT_STATUS_CHANGED, "P1", "on_sale")
        assert captures["metadata"] == ["P1"]
        assert captures["sync"] == []

    def test_viewed_and_favorite_route_to_behavior(self, captures):
        events.emit(events.PRODUCT_VIEWED, 7, "P1")
        events.emit(events.FAVORITE_CHANGED, 7, "P1", True)
        events.emit(events.FAVORITE_CHANGED, 7, "P1", False)
        assert captures["view"] == [(7, "P1")]
        assert captures["favorite"] == [(7, "P1", True), (7, "P1", False)]


class TestIdempotent:
    def test_register_all_twice_no_duplicate(self):
        events_subscribers._reset_for_tests()
        events_subscribers.register_all()
        handlers_first = dict(events._HANDLERS)
        events_subscribers.register_all()  # 重复注册
        assert handlers_first == events._HANDLERS
        assert len(events._HANDLERS[events.PRODUCT_PUBLISHED]) == 1
        events_subscribers._reset_for_tests()

    def test_ensure_indexes_creates_expected_indexes(self, app, fake_mongo):
        with app.app_context():
            events_subscribers.ensure_indexes()
        profiles = fake_mongo["user_profiles"].indexes
        vectors = fake_mongo["product_vectors"].indexes
        behaviors = fake_mongo["user_behaviors"].indexes
        assert any(
            keys == ("user_id",) and dict(kwargs).get("unique")
            for keys, kwargs in profiles
        )
        assert any(
            keys == ("product_id",) and dict(kwargs).get("unique")
            for keys, kwargs in vectors
        )
        assert any(list(keys[0]) == ["user_id", "created_at"] for keys, _kwargs in behaviors)
        assert any(keys == ("product_id",) for keys, _kwargs in behaviors)

    def test_ensure_indexes_failure_does_not_raise(self, app, fake_mongo):
        fake_mongo.fail = True
        with app.app_context():
            events_subscribers.ensure_indexes()  # 不上抛（启动容错）


class TestCreateAppWiring:
    def test_create_app_registers_subscribers_and_indexes(self, fake_mongo):
        """B-1 回归：create_app 执行期（无请求上下文）register_all 真实执行。

        router 以 ``app.app_context()`` 包裹接线，索引建立调用不被
        「Working outside of application context」容错分支吞掉。
        """
        from src.app import create_app

        events_subscribers._reset_for_tests()
        try:
            create_app(TestConfig)
            assert set(events._HANDLERS) == {
                events.PRODUCT_PUBLISHED,
                events.PRODUCT_UPDATED,
                events.PRODUCT_DELETED,
                events.PRODUCT_STATUS_CHANGED,
                events.PRODUCT_VIEWED,
                events.FAVORITE_CHANGED,
            }
            assert fake_mongo["user_profiles"].indexes
            assert fake_mongo["product_vectors"].indexes
            assert fake_mongo["user_behaviors"].indexes
        finally:
            events_subscribers._reset_for_tests()
