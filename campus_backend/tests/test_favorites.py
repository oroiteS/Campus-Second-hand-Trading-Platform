"""收藏域测试：收藏/重复/状态限制/防探测、幂等取消、计数原子性、mine 列表。"""

import pytest

from src.model import Favorite, db
from tests.test_products import PRODUCTS_URL, _verified

FAVORITE_URL = f"{PRODUCTS_URL}/{{pid}}/favorite"
MINE_URL = "/api/favorites/mine"


class TestFavorite:
    def test_favorite_success(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        buyer = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        res = client.post(
            FAVORITE_URL.format(pid=product.id), headers=make_auth_header(buyer["id"])
        )
        assert res.status_code == 200
        data = res.get_json()["data"]
        assert data == {"favorited": True, "favorite_count": 1}
        # 详情联动 is_favorited / favorite_count
        detail = client.get(
            f"{PRODUCTS_URL}/{product.id}", headers=make_auth_header(buyer["id"])
        ).get_json()["data"]
        assert detail["is_favorited"] is True
        assert detail["favorite_count"] == 1

    def test_duplicate_favorite_9003(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        buyer = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        headers = make_auth_header(buyer["id"])
        assert client.post(FAVORITE_URL.format(pid=product.id), headers=headers).status_code == 200
        res = client.post(FAVORITE_URL.format(pid=product.id), headers=headers)
        assert (res.status_code, res.get_json()["code"]) == (409, 9003)
        # 重复收藏未落新记录（事务回滚，uk 兜底）
        assert db.session.query(Favorite).filter_by(user_id=buyer["id"]).count() == 1

    def test_duplicate_favorite_count_not_drifted(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        """uk 兜底：第二次收藏失败后 favorite_count 仍为 1。"""
        from src.model import Product as ProductModel

        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        buyer = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        headers = make_auth_header(buyer["id"])
        client.post(FAVORITE_URL.format(pid=product.id), headers=headers)
        client.post(FAVORITE_URL.format(pid=product.id), headers=headers)
        db.session.expire_all()
        fresh = db.session.get(ProductModel, product.id)
        assert fresh.favorite_count == 1

    @pytest.mark.parametrize("status", ["off_sale", "trading", "sold"])
    def test_favorite_non_on_sale_3001(
        self, status, client, db_create_all, school_fixtures, user_factory,
        category_fixtures, product_factory, make_auth_header,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id, status=status)
        buyer = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        res = client.post(
            FAVORITE_URL.format(pid=product.id), headers=make_auth_header(buyer["id"])
        )
        assert (res.status_code, res.get_json()["code"]) == (409, 3001)

    def test_favorite_other_school_404(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        outsider = _verified(
            user_factory, school_fixtures.single, school_fixtures.main_campus
        )
        res = client.post(
            FAVORITE_URL.format(pid=product.id), headers=make_auth_header(outsider["id"])
        )
        assert (res.status_code, res.get_json()["code"]) == (404, 9002)

    def test_favorite_nonexistent_404(
        self, client, db_create_all, school_fixtures, user_factory, make_auth_header
    ):
        buyer = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        res = client.post(FAVORITE_URL.format(pid=424242), headers=make_auth_header(buyer["id"]))
        assert (res.status_code, res.get_json()["code"]) == (404, 9002)

    def test_favorite_admin_9003(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        admin = user_factory(role="admin")
        res = client.post(
            FAVORITE_URL.format(pid=product.id), headers=make_auth_header(admin["id"])
        )
        assert (res.status_code, res.get_json()["code"]) == (409, 9003)


class TestUnfavorite:
    def test_unfavorite_idempotent_twice_200(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        buyer = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        headers = make_auth_header(buyer["id"])
        client.post(FAVORITE_URL.format(pid=product.id), headers=headers)
        first = client.delete(FAVORITE_URL.format(pid=product.id), headers=headers)
        assert first.status_code == 200
        assert first.get_json()["data"] == {"favorited": False, "favorite_count": 0}
        second = client.delete(FAVORITE_URL.format(pid=product.id), headers=headers)
        assert second.status_code == 200
        assert second.get_json()["data"] == {"favorited": False, "favorite_count": 0}

    def test_unfavorite_after_others_favorite(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        """计数原子性：两人各收藏后一人取消，剩余 1。"""
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        b1 = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        b2 = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        client.post(FAVORITE_URL.format(pid=product.id), headers=make_auth_header(b1["id"]))
        client.post(FAVORITE_URL.format(pid=product.id), headers=make_auth_header(b2["id"]))
        res = client.delete(
            FAVORITE_URL.format(pid=product.id), headers=make_auth_header(b1["id"])
        )
        assert res.get_json()["data"]["favorite_count"] == 1

    def test_unfavorite_off_sale_product_200(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        """收藏列表含 off_sale（前端可取消）→ 取消 off_sale 商品必须成功。"""
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        buyer = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        headers = make_auth_header(buyer["id"])
        client.post(FAVORITE_URL.format(pid=product.id), headers=headers)
        product.status = "off_sale"
        db.session.commit()
        res = client.delete(FAVORITE_URL.format(pid=product.id), headers=headers)
        assert res.status_code == 200

    def test_unfavorite_other_school_404(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        outsider = _verified(
            user_factory, school_fixtures.single, school_fixtures.main_campus
        )
        res = client.delete(
            FAVORITE_URL.format(pid=product.id), headers=make_auth_header(outsider["id"])
        )
        assert (res.status_code, res.get_json()["code"]) == (404, 9002)


class TestMyFavorites:
    def test_mine_includes_off_sale_excludes_deleted_and_orders_by_time(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        cat = category_fixtures.items[0].id
        p_on = product_factory(seller, cat, title="在售")
        p_off = product_factory(seller, cat, title="已下架")  # 先在售，收藏后再下架
        p_del = product_factory(seller, cat, title="已删", status="deleted")
        buyer = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        headers = make_auth_header(buyer["id"])
        # 先在售时收藏（在售 → 后下架那条），再让 p_off 下架
        assert client.post(FAVORITE_URL.format(pid=p_on.id), headers=headers).status_code == 200
        assert client.post(FAVORITE_URL.format(pid=p_off.id), headers=headers).status_code == 200
        p_off.status = "off_sale"
        # 已删商品不可经接口收藏（接口对非在售 3001），直插库内记录验证排除逻辑；
        # 跨校收藏记录经接口不可能产生（收藏时已校验同校），不另造数
        db.session.add(Favorite(user_id=buyer["id"], product_id=p_del.id))
        db.session.commit()
        res = client.get(MINE_URL, headers=headers)
        data = res.get_json()["data"]
        ids = [i["id"] for i in data["items"]]
        # favorited_at 倒序：后收藏的在前（p_off 晚于 p_on；两条直插记录最新但被排除）
        assert ids == [p_off.id, p_on.id]
        items = data["items"]
        assert all("favorited_at" in i and i["favorited_at"].endswith("+08:00") for i in items)
        assert items[0]["status"] == "off_sale"  # 含 off_sale（置灰用）
        assert p_del.id not in ids

    def test_mine_is_own_data_only(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        b1 = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        b2 = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        client.post(FAVORITE_URL.format(pid=product.id), headers=make_auth_header(b1["id"]))
        res = client.get(MINE_URL, headers=make_auth_header(b2["id"]))
        assert res.get_json()["data"]["total"] == 0

    def test_mine_summary_fields_complete(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        """条目为完整 ProductSummary 形态 + favorited_at（概要序列化不缺段）。"""
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id, title="好物")
        buyer = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        headers = make_auth_header(buyer["id"])
        assert client.post(FAVORITE_URL.format(pid=product.id), headers=headers).status_code == 200
        item = client.get(MINE_URL, headers=headers).get_json()["data"]["items"][0]
        assert set(item) >= {
            "id", "title", "price", "original_price", "condition", "status",
            "cover", "favorite_count", "category", "seller", "campus",
            "created_at", "favorited_at",
        }
        assert item["id"] == product.id
        assert item["title"] == "好物"
        assert item["seller"]["id"] == seller["id"]
        assert item["favorited_at"].endswith("+08:00")

    def test_mine_no_n1_and_orders_by_favorited_at(
        self, client, app, db_create_all, school_fixtures, user_factory,
        category_fixtures, product_factory, make_auth_header,
    ):
        """favorited_at 倒序稳定 + 概要序列化无 N+1（SQL 语句数不随条目数线性增长）。"""
        from sqlalchemy import event

        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        cat = category_fixtures.items[0].id
        products = [
            product_factory(seller, cat, title=f"商品{i}") for i in range(5)
        ]
        buyer = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        headers = make_auth_header(buyer["id"])
        # 按顺序收藏 → 列表应为倒序（最后收藏的在前）
        for p in products:
            assert client.post(FAVORITE_URL.format(pid=p.id), headers=headers).status_code == 200

        stmt_count = 0

        def _count(conn, cursor, statement, parameters, context, executemany):
            nonlocal stmt_count
            stmt_count += 1

        engine = app.extensions["sqlalchemy"].engine
        event.listen(engine, "before_cursor_execute", _count)
        try:
            res = client.get(MINE_URL, headers=headers)
        finally:
            event.remove(engine, "before_cursor_execute", _count)

        data = res.get_json()["data"]
        assert data["total"] == 5
        assert [i["id"] for i in data["items"]] == [p.id for p in reversed(products)]
        # N+1 规避：概要序列化所需关联已 selectinload 预载。
        # 语句数上限取经验常数（主查询 + count + 少量固定预载批查），
        # 若逐行懒加载则 ≈ 4N+1 ≥ 21，远超此上限。
        assert stmt_count <= 10

    def test_mine_admin_empty(
        self, client, db_create_all, user_factory, make_auth_header
    ):
        admin = user_factory(role="admin")
        res = client.get(MINE_URL, headers=make_auth_header(admin["id"]))
        assert res.get_json()["data"]["total"] == 0
