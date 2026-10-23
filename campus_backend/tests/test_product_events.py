"""事件总线 6 事件点测试：对应动作后按序 emit，订阅桩捕获参数断言。

订阅桩直接挂 ``events._HANDLERS``（进程内全局），用例级 fixture 负责
前后清空，避免跨用例泄漏；订阅者抛异常不影响主流程与 HTTP 200。
"""

import pytest

from src.model import Product, db
from src.services import events
from tests.test_products import PRODUCTS_URL, _payload, _verified

_EVENTS_UNDER_TEST = (
    events.PRODUCT_PUBLISHED,
    events.PRODUCT_UPDATED,
    events.PRODUCT_DELETED,
    events.PRODUCT_STATUS_CHANGED,
    events.PRODUCT_VIEWED,
    events.FAVORITE_CHANGED,
)


@pytest.fixture()
def event_capture():
    """订阅全部 6 事件并捕获 (event, args)；用例结束清空全局订阅表。"""

    def _capture() -> dict[str, list[tuple]]:
        captured: dict[str, list[tuple]] = {}
        for name in _EVENTS_UNDER_TEST:
            def _make_handler(evt):
                def handler(*args):
                    captured.setdefault(evt, []).append(args)

                return handler

            events.subscribe(name, _make_handler(name))
        return captured

    yield _capture
    events._HANDLERS.clear()


class TestProductEvents:
    def test_published_emitted_after_create(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        owned_product_images, make_auth_header, event_capture,
    ):
        captured = event_capture()
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        image_ids = owned_product_images(seller["id"], 1)
        res = client.post(
            PRODUCTS_URL,
            headers=make_auth_header(seller["id"]),
            json=_payload(category_fixtures.items[0].id, image_ids),
        )
        assert res.status_code == 200
        assert list(captured) == [events.PRODUCT_PUBLISHED]  # 仅此一个事件
        (args,) = captured[events.PRODUCT_PUBLISHED]
        (product,) = args
        assert isinstance(product, Product)
        assert product.id == res.get_json()["data"]["id"]
        assert product.status == "on_sale"  # commit 后的持久化状态

    def test_updated_emitted_with_changed_set(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, owned_product_images, make_auth_header, event_capture,
    ):
        """changed 集合 = 实际变化字段；image_ids 变化不进集合。"""
        captured = event_capture()
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(
            seller, category_fixtures.items[0].id, title="旧标题",
            price="100.00", description="旧描述",
        )
        new_images = owned_product_images(seller["id"], 2)  # 与原图不同 → image_ids 变
        res = client.put(
            f"{PRODUCTS_URL}/{product.id}",
            headers=make_auth_header(seller["id"]),
            json=_payload(
                category_fixtures.items[0].id,
                new_images,
                title="新标题",       # 变
                description="旧描述",  # 不变
                price=100.0,           # 不变
            ),
        )
        assert res.status_code == 200
        (args,) = captured[events.PRODUCT_UPDATED]
        product, changed = args
        assert isinstance(changed, set)
        assert changed == {"title"}

    def test_updated_changed_set_multi_fields(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, owned_product_images, make_auth_header, event_capture,
    ):
        captured = event_capture()
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(
            seller, category_fixtures.items[0].id, title="旧标题", price="100.00",
        )
        new_images = owned_product_images(seller["id"], 1)
        res = client.put(
            f"{PRODUCTS_URL}/{product.id}",
            headers=make_auth_header(seller["id"]),
            json=_payload(
                category_fixtures.by_name["图书教材"].id,  # 分类变
                new_images,
                title="旧标题",
                description="测试描述",  # 与工厂默认一致（不变）
                price=250.00,        # 价格变
                condition="good",    # 成色变
            ),
        )
        assert res.status_code == 200
        (_product, changed) = captured[events.PRODUCT_UPDATED][0]
        assert changed == {"price", "category_id", "condition"}

    def test_status_changed_emitted_with_old_status(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header, event_capture,
    ):
        captured = event_capture()
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        res = client.patch(
            f"{PRODUCTS_URL}/{product.id}/status",
            headers=make_auth_header(seller["id"]),
            json={"status": "off_sale"},
        )
        assert res.status_code == 200
        (args,) = captured[events.PRODUCT_STATUS_CHANGED]
        product, old_status = args
        assert old_status == "on_sale"
        assert product.status == "off_sale"

    def test_status_same_state_no_event(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header, event_capture,
    ):
        """幂等同态不 emit（无状态变化）。"""
        captured = event_capture()
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        res = client.patch(
            f"{PRODUCTS_URL}/{product.id}/status",
            headers=make_auth_header(seller["id"]),
            json={"status": "on_sale"},
        )
        assert res.status_code == 200
        assert events.PRODUCT_STATUS_CHANGED not in captured

    def test_deleted_emitted_with_product_id(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header, event_capture,
    ):
        captured = event_capture()
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        res = client.delete(
            f"{PRODUCTS_URL}/{product.id}", headers=make_auth_header(seller["id"])
        )
        assert res.status_code == 200
        (args,) = captured[events.PRODUCT_DELETED]
        (product_id,) = args
        assert product_id == product.id
        assert isinstance(product_id, int)

    def test_viewed_emitted_on_detail(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header, event_capture,
    ):
        captured = event_capture()
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        viewer = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        res = client.get(
            f"{PRODUCTS_URL}/{product.id}", headers=make_auth_header(viewer["id"])
        )
        assert res.status_code == 200
        (args,) = captured[events.PRODUCT_VIEWED]
        user_id, product_arg = args
        assert user_id == viewer["id"]
        assert product_arg.id == product.id
        assert product_arg.view_count == 1  # commit 后

    def test_subscriber_exception_does_not_break_request(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        owned_product_images, make_auth_header, event_capture, caplog,
    ):
        """订阅者抛异常：主流程照常，HTTP 200，后续订阅者仍被调用。"""
        boom_calls: list[str] = []

        def boom(product):
            boom_calls.append("boom")
            raise RuntimeError("订阅者炸了")

        seen: list[int] = []
        events.subscribe(events.PRODUCT_PUBLISHED, boom)
        events.subscribe(events.PRODUCT_PUBLISHED, lambda p: seen.append(p.id))
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        image_ids = owned_product_images(seller["id"], 1)
        with caplog.at_level("ERROR", logger="src.services.events"):
            res = client.post(
                PRODUCTS_URL,
                headers=make_auth_header(seller["id"]),
                json=_payload(category_fixtures.items[0].id, image_ids),
            )
        assert res.status_code == 200
        assert res.get_json()["code"] == 0
        assert boom_calls == ["boom"]
        assert len(seen) == 1  # 异常订阅者之后的订阅者照常执行
        assert any("事件订阅者异常" in r.message for r in caplog.records)
        _ = event_capture  # 本用例不经 capture fixture 订阅（自管）


class TestCacheInvalidation:
    """编辑/状态/删除后 detail 缓存失效（编辑路径覆盖发布+编辑双场景）。"""

    def _warm_cache(self, client, viewer_headers, product_id):
        res = client.get(f"{PRODUCTS_URL}/{product_id}", headers=viewer_headers)
        assert res.status_code == 200

    def test_edit_invalidates_detail_cache(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, owned_product_images, make_auth_header, fake_redis,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id, title="旧标题")
        viewer = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        viewer_headers = make_auth_header(viewer["id"])
        self._warm_cache(client, viewer_headers, product.id)
        key = f"product:detail:{school_fixtures.multi.id}:{product.id}"
        assert key in fake_redis.store

        new_images = owned_product_images(seller["id"], 1)
        res = client.put(
            f"{PRODUCTS_URL}/{product.id}",
            headers=make_auth_header(seller["id"]),
            json=_payload(category_fixtures.items[0].id, new_images, title="新标题"),
        )
        assert res.status_code == 200
        assert key not in fake_redis.store  # 已失效
        # 再次详情拿到新值（重新回填缓存）
        res = client.get(f"{PRODUCTS_URL}/{product.id}", headers=viewer_headers)
        assert res.get_json()["data"]["title"] == "新标题"

    def test_status_change_invalidates_detail_cache(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header, fake_redis,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        viewer = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        self._warm_cache(client, make_auth_header(viewer["id"]), product.id)
        res = client.patch(
            f"{PRODUCTS_URL}/{product.id}/status",
            headers=make_auth_header(seller["id"]),
            json={"status": "off_sale"},
        )
        assert res.status_code == 200
        key = f"product:detail:{school_fixtures.multi.id}:{product.id}"
        assert key not in fake_redis.store
        # 下架后旁观者 404（缓存失效 + 可见性矩阵）
        res = client.get(
            f"{PRODUCTS_URL}/{product.id}", headers=make_auth_header(viewer["id"])
        )
        assert res.status_code == 404

    def test_delete_invalidates_detail_cache(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header, fake_redis,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        viewer = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        self._warm_cache(client, make_auth_header(viewer["id"]), product.id)
        key = f"product:detail:{school_fixtures.multi.id}:{product.id}"
        assert key in fake_redis.store
        res = client.delete(
            f"{PRODUCTS_URL}/{product.id}", headers=make_auth_header(seller["id"])
        )
        assert res.status_code == 200
        assert key not in fake_redis.store

    def test_updated_at_not_bumped_by_view(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        """浏览不改 updated_at（内容时间戳语义，原子自增显式保持）。"""
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        before = product.updated_at
        viewer = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        client.get(f"{PRODUCTS_URL}/{product.id}", headers=make_auth_header(viewer["id"]))
        db.session.refresh(product)
        assert product.updated_at == before


class TestFavoriteEvents:
    def test_favorite_changed_true_and_false(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header, event_capture,
    ):
        """收藏 emit favorited=True；取消 emit favorited=False（仅实际删除时）。"""
        from tests.test_products import PRODUCTS_URL

        captured = event_capture()
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        buyer = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        headers = make_auth_header(buyer["id"])
        res = client.post(f"{PRODUCTS_URL}/{product.id}/favorite", headers=headers)
        assert res.status_code == 200
        (args,) = captured[events.FAVORITE_CHANGED]
        user_id, product_arg, favorited = args
        assert (user_id, favorited) == (buyer["id"], True)
        assert product_arg.id == product.id

        captured.clear()
        res = client.delete(f"{PRODUCTS_URL}/{product.id}/favorite", headers=headers)
        assert res.status_code == 200
        (args,) = captured[events.FAVORITE_CHANGED]
        user_id, product_arg, favorited = args
        assert (user_id, favorited) == (buyer["id"], False)

    def test_unfavorite_idempotent_no_event(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header, event_capture,
    ):
        """幂等取消（无记录）不 emit favorited=False。"""
        from tests.test_products import PRODUCTS_URL

        captured = event_capture()
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        buyer = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        res = client.delete(
            f"{PRODUCTS_URL}/{product.id}/favorite",
            headers=make_auth_header(buyer["id"]),
        )
        assert res.status_code == 200
        assert events.FAVORITE_CHANGED not in captured
