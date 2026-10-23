"""商品域测试（一）：发布 / 详情（可见性与缓存）/ 列表筛选 / 我的商品。

编辑/状态/删除的事件与缓存失效用例见同类追加（test_products.py 第二批）。
"""

import pytest

from src.model import Category, db

PRODUCTS_URL = "/api/products"

_STATUS_LABELS = {
    "on_sale": "上架",
    "trading": "交易中",
    "sold": "已售",
    "off_sale": "已下架",
    "deleted": "已删除",
}


def status_label(status: str) -> str:
    """3001 message 中的状态中文标签断言用。"""
    return _STATUS_LABELS[status]


def _verified(user_factory, school, campus=None, **overrides) -> dict:
    return user_factory(
        school_id=school.id,
        campus_id=campus.id if campus else None,
        auth_status="approved",
        **overrides,
    )


def _payload(category_id: int, image_ids: list[int], **overrides) -> dict:
    base = {
        "title": "罗技 K845 机械键盘",
        "description": "去年购入，自用一年，功能完好。",
        "price": 199.0,
        "category_id": category_id,
        "condition": "excellent",
        "image_ids": image_ids,
    }
    base.update(overrides)
    return base


def _create_via_api(client, headers, payload):
    return client.post(PRODUCTS_URL, headers=headers, json=payload)


# ============================================================
# 发布
# ============================================================


class TestCreateProduct:
    def test_create_success_returns_product_detail(
        self,
        client,
        db_create_all,
        school_fixtures,
        user_factory,
        category_fixtures,
        owned_product_images,
        make_auth_header,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        image_ids = owned_product_images(seller["id"], 2)
        headers = make_auth_header(seller["id"])
        res = _create_via_api(
            client, headers, _payload(category_fixtures.by_name["数码电子"].id, image_ids)
        )
        assert res.status_code == 200
        body = res.get_json()
        assert body["code"] == 0
        data = body["data"]
        assert data["status"] == "on_sale"
        assert data["title"] == "罗技 K845 机械键盘"
        assert data["price"] == 199.0
        assert data["condition"] == "excellent"
        assert data["view_count"] == 0
        assert data["is_favorited"] is False
        assert data["favorite_count"] == 0
        # 图集顺序 = image_ids 数组序；cover = 首图
        assert [img["id"] for img in data["images"]] == image_ids
        assert data["cover"]["id"] == image_ids[0]
        assert data["cover"]["url"] == f"/api/images/{image_ids[0]}"
        # seller / category / campus（缺省取发布者校区）
        assert data["seller"]["id"] == seller["id"]
        assert data["seller"]["display_name"].endswith("(东校区)")
        assert data["category"]["name"] == "数码电子"
        assert data["campus"]["id"] == school_fixtures.east.id
        # 契约时间格式：ISO 8601 含 +08:00
        assert data["created_at"].endswith("+08:00")
        assert data["updated_at"].endswith("+08:00")

    def test_create_with_original_price_and_explicit_campus(
        self,
        client,
        db_create_all,
        school_fixtures,
        user_factory,
        category_fixtures,
        owned_product_images,
        make_auth_header,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        image_ids = owned_product_images(seller["id"], 1)
        res = _create_via_api(
            client,
            make_auth_header(seller["id"]),
            _payload(
                category_fixtures.by_name["图书教材"].id,
                image_ids,
                original_price=399.5,
                campus_id=school_fixtures.west.id,
            ),
        )
        assert res.status_code == 200
        data = res.get_json()["data"]
        assert data["original_price"] == 399.5
        assert data["campus"]["id"] == school_fixtures.west.id

    @pytest.mark.parametrize(
        ("overrides", "field"),
        [
            ({"title": ""}, "title"),
            ({"title": "x" * 51}, "title"),
            ({"description": ""}, "description"),
            ({"description": "x" * 2001}, "description"),
            ({"price": 0}, "price"),
            ({"price": 100000}, "price"),
            ({"price": 199.999}, "price"),
            ({"price": "abc"}, "price"),
            ({"price": None}, "price"),
            ({"original_price": 0}, "original_price"),
            ({"condition": "brand"}, "condition"),
            ({"condition": None}, "condition"),
            ({"category_id": 424242}, "category_id"),
            ({"campus_id": 424242}, "campus_id"),
        ],
        ids=[
            "标题空", "标题超长", "描述空", "描述超长",
            "价格0", "价格超上限", "价格三位小数", "价格非数字", "价格缺失",
            "原价0", "成色非法", "成色缺失", "分类不存在", "校区不存在",
        ],
    )
    def test_create_field_validation_9001(
        self,
        client,
        db_create_all,
        school_fixtures,
        user_factory,
        category_fixtures,
        owned_product_images,
        make_auth_header,
        overrides,
        field,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        image_ids = owned_product_images(seller["id"], 1)
        payload = _payload(category_fixtures.items[0].id, image_ids)
        payload.update(overrides)  # 允许覆盖 category_id 等与形参同名的键
        res = _create_via_api(client, make_auth_header(seller["id"]), payload)
        assert res.status_code == 422
        body = res.get_json()
        assert body["code"] == 9001
        assert field in body["data"]["fields"]

    def test_create_disabled_category_9001(
        self,
        client,
        db_create_all,
        school_fixtures,
        user_factory,
        category_fixtures,
        owned_product_images,
        make_auth_header,
    ):
        disabled = Category(name="停用分类", sort_order=99, status="disabled")
        db.session.add(disabled)
        db.session.commit()
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        image_ids = owned_product_images(seller["id"], 1)
        res = _create_via_api(
            client,
            make_auth_header(seller["id"]),
            _payload(disabled.id, image_ids),
        )
        assert (res.status_code, res.get_json()["code"]) == (422, 9001)
        assert "category_id" in res.get_json()["data"]["fields"]

    @pytest.mark.parametrize(
        ("image_ids_factory", "label"),
        [
            (lambda ids: [], "空数组"),
            (lambda ids: ids[:1] * 10, "10 张"),
            (lambda ids: ids[:2] * 2, "重复"),
        ],
        ids=["0张", "10张", "重复id"],
    )
    def test_create_image_count_violations_9001(
        self,
        client,
        db_create_all,
        school_fixtures,
        user_factory,
        category_fixtures,
        owned_product_images,
        make_auth_header,
        image_ids_factory,
        label,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        image_ids = owned_product_images(seller["id"], 10)
        res = _create_via_api(
            client,
            make_auth_header(seller["id"]),
            _payload(category_fixtures.items[0].id, image_ids_factory(image_ids)),
        )
        assert (res.status_code, res.get_json()["code"]) == (422, 9001)
        assert "image_ids" in res.get_json()["data"]["fields"]

    def test_create_others_image_9001(
        self,
        client,
        db_create_all,
        school_fixtures,
        user_factory,
        category_fixtures,
        owned_product_images,
        make_auth_header,
    ):
        """他人上传的图片 → 9001（归属复验）。"""
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        other = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        others_image = owned_product_images(other["id"], 1)
        res = _create_via_api(
            client,
            make_auth_header(seller["id"]),
            _payload(category_fixtures.items[0].id, others_image),
        )
        assert (res.status_code, res.get_json()["code"]) == (422, 9001)

    def test_create_nonexistent_image_9001(
        self,
        client,
        db_create_all,
        school_fixtures,
        user_factory,
        category_fixtures,
        make_auth_header,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        res = _create_via_api(
            client,
            make_auth_header(seller["id"]),
            _payload(category_fixtures.items[0].id, [424242]),
        )
        assert (res.status_code, res.get_json()["code"]) == (422, 9001)

    def test_create_avatar_purpose_image_9001(
        self,
        client,
        db_create_all,
        school_fixtures,
        user_factory,
        category_fixtures,
        owned_product_images,
        make_auth_header,
    ):
        """本人上传但 purpose != product 的图片 → 9001。"""
        from src.model import Image

        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        avatar = Image(
            owner_id=seller["id"],
            path="avatar/a.png",
            mime="image/png",
            size_bytes=10,
            sha256="a" * 64,
            purpose="avatar",
        )
        db.session.add(avatar)
        db.session.commit()
        res = _create_via_api(
            client,
            make_auth_header(seller["id"]),
            _payload(category_fixtures.items[0].id, [avatar.id]),
        )
        assert (res.status_code, res.get_json()["code"]) == (422, 9001)

    def test_create_other_school_campus_9001(
        self,
        client,
        db_create_all,
        school_fixtures,
        user_factory,
        category_fixtures,
        owned_product_images,
        make_auth_header,
    ):
        """他校校区 → 9001（campus 归属复验）。"""
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        image_ids = owned_product_images(seller["id"], 1)
        res = _create_via_api(
            client,
            make_auth_header(seller["id"]),
            _payload(
                category_fixtures.items[0].id,
                image_ids,
                campus_id=school_fixtures.main_campus.id,
            ),
        )
        assert (res.status_code, res.get_json()["code"]) == (422, 9001)
        assert "campus_id" in res.get_json()["data"]["fields"]

    def test_create_disabled_campus_9001(
        self,
        client,
        db_create_all,
        school_fixtures,
        user_factory,
        category_fixtures,
        owned_product_images,
        make_auth_header,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        image_ids = owned_product_images(seller["id"], 1)
        res = _create_via_api(
            client,
            make_auth_header(seller["id"]),
            _payload(
                category_fixtures.items[0].id,
                image_ids,
                campus_id=school_fixtures.disabled_campus.id,
            ),
        )
        assert (res.status_code, res.get_json()["code"]) == (422, 9001)

    def test_admin_create_9003(
        self,
        client,
        db_create_all,
        school_fixtures,
        user_factory,
        category_fixtures,
        owned_product_images,
        make_auth_header,
    ):
        admin = user_factory(role="admin", auth_status="approved")
        image_ids = owned_product_images(admin["id"], 1)
        res = _create_via_api(
            client,
            make_auth_header(admin["id"]),
            _payload(category_fixtures.items[0].id, image_ids),
        )
        body = res.get_json()
        assert (res.status_code, body["code"]) == (409, 9003)
        assert "管理员无交易能力" in body["message"]

    def test_unverified_create_1004(
        self, client, db_create_all, school_fixtures, user_factory, make_auth_header
    ):
        user = user_factory(school_id=school_fixtures.multi.id, auth_status="unverified")
        res = _create_via_api(client, make_auth_header(user["id"]), {"title": "x"})
        assert (res.status_code, res.get_json()["code"]) == (403, 1004)

    def test_anonymous_create_401(self, client, db_create_all):
        res = _create_via_api(client, {}, {})
        assert (res.status_code, res.get_json()["code"]) == (401, 1001)


# ============================================================
# 详情（可见性矩阵 / 浏览计数 / 缓存）
# ============================================================


class TestProductDetailVisibility:
    def _setup(self, school_fixtures, user_factory, category_fixtures, product_factory):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        stranger = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        return seller, stranger, product

    def test_on_sale_visible_to_same_school(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        seller, stranger, product = self._setup(
            school_fixtures, user_factory, category_fixtures, product_factory
        )
        res = client.get(
            f"{PRODUCTS_URL}/{product.id}", headers=make_auth_header(stranger["id"])
        )
        assert res.status_code == 200
        data = res.get_json()["data"]
        assert data["id"] == product.id
        assert data["description"] == "测试描述"
        assert len(data["images"]) == 1

    def test_view_count_increments_per_request(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        seller, stranger, product = self._setup(
            school_fixtures, user_factory, category_fixtures, product_factory
        )
        headers = make_auth_header(stranger["id"])
        for expected in (1, 2):
            res = client.get(f"{PRODUCTS_URL}/{product.id}", headers=headers)
            assert res.get_json()["data"]["view_count"] == expected

    def test_off_sale_visible_to_seller_and_admin_only(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        seller, stranger, product = self._setup(
            school_fixtures, user_factory, category_fixtures, product_factory
        )
        product.status = "off_sale"
        db.session.commit()
        url = f"{PRODUCTS_URL}/{product.id}"
        assert (
            client.get(url, headers=make_auth_header(seller["id"])).status_code == 200
        )
        admin = user_factory(role="admin")
        assert client.get(url, headers=make_auth_header(admin["id"])).status_code == 200
        res = client.get(url, headers=make_auth_header(stranger["id"]))
        assert (res.status_code, res.get_json()["code"]) == (404, 9002)

    def test_trading_visible_to_seller_and_admin_only(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        seller, stranger, product = self._setup(
            school_fixtures, user_factory, category_fixtures, product_factory
        )
        product.status = "trading"
        db.session.commit()
        url = f"{PRODUCTS_URL}/{product.id}"
        assert (
            client.get(url, headers=make_auth_header(seller["id"])).status_code == 200
        )
        admin = user_factory(role="admin")
        assert client.get(url, headers=make_auth_header(admin["id"])).status_code == 200
        res = client.get(url, headers=make_auth_header(stranger["id"]))
        assert (res.status_code, res.get_json()["code"]) == (404, 9002)

    def test_sold_invisible_to_everyone(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        seller, _stranger, product = self._setup(
            school_fixtures, user_factory, category_fixtures, product_factory
        )
        product.status = "sold"
        db.session.commit()
        res = client.get(
            f"{PRODUCTS_URL}/{product.id}", headers=make_auth_header(seller["id"])
        )
        assert (res.status_code, res.get_json()["code"]) == (404, 9002)

    def test_deleted_invisible_to_seller(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        seller, _stranger, product = self._setup(
            school_fixtures, user_factory, category_fixtures, product_factory
        )
        product.status = "deleted"
        db.session.commit()
        res = client.get(
            f"{PRODUCTS_URL}/{product.id}", headers=make_auth_header(seller["id"])
        )
        assert (res.status_code, res.get_json()["code"]) == (404, 9002)

    def test_other_school_on_sale_404(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        """他校在售商品直构 id → 404/9002（AC-03 防探测）。"""
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        outsider = _verified(
            user_factory, school_fixtures.single, school_fixtures.main_campus
        )
        res = client.get(
            f"{PRODUCTS_URL}/{product.id}", headers=make_auth_header(outsider["id"])
        )
        assert (res.status_code, res.get_json()["code"]) == (404, 9002)

    def test_nonexistent_404(self, client, db_create_all, user_factory, make_auth_header):
        user = user_factory(role="admin")
        res = client.get(f"{PRODUCTS_URL}/424242", headers=make_auth_header(user["id"]))
        assert (res.status_code, res.get_json()["code"]) == (404, 9002)


class TestDetailCache:
    def test_detail_cached_and_hit(
        self,
        client,
        db_create_all,
        school_fixtures,
        user_factory,
        category_fixtures,
        product_factory,
        make_auth_header,
        fake_redis,
    ):
        """首次详情写缓存（键含 school_id）；命中路径返回缓存体。"""
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id, title="缓存标题")
        stranger = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        res = client.get(
            f"{PRODUCTS_URL}/{product.id}", headers=make_auth_header(stranger["id"])
        )
        assert res.status_code == 200
        expected_key = f"product:detail:{school_fixtures.multi.id}:{product.id}"
        assert expected_key in fake_redis.store  # 键经 scoped_key 且含 school_id
        # 直接改库不失效缓存 → 第二次详情仍返回旧标题（缓存命中证据）
        product.title = "数据库新标题"
        db.session.commit()
        res = client.get(
            f"{PRODUCTS_URL}/{product.id}", headers=make_auth_header(stranger["id"])
        )
        assert res.get_json()["data"]["title"] == "缓存标题"

    def test_view_count_not_from_cache(
        self,
        client,
        db_create_all,
        school_fixtures,
        user_factory,
        category_fixtures,
        product_factory,
        make_auth_header,
    ):
        """view_count 不进缓存：命中路径下每次详情仍 +1。"""
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        stranger = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        headers = make_auth_header(stranger["id"])
        first = client.get(f"{PRODUCTS_URL}/{product.id}", headers=headers)
        second = client.get(f"{PRODUCTS_URL}/{product.id}", headers=headers)
        assert first.get_json()["data"]["view_count"] == 1
        assert second.get_json()["data"]["view_count"] == 2

    def test_cache_failure_degrades_gracefully(
        self,
        client,
        db_create_all,
        school_fixtures,
        user_factory,
        category_fixtures,
        product_factory,
        make_auth_header,
        fake_redis,
    ):
        """Redis 故障：详情照常 200（缓存降级，业务不受影响）。"""
        fake_redis.fail = True
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        stranger = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        res = client.get(
            f"{PRODUCTS_URL}/{product.id}", headers=make_auth_header(stranger["id"])
        )
        assert res.status_code == 200
        assert res.get_json()["data"]["id"] == product.id


# ============================================================
# 列表
# ============================================================


class TestListProducts:
    def _seed_products(self, school_fixtures, user_factory, category_fixtures, product_factory):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        cat_digital = category_fixtures.by_name["数码电子"]
        cat_book = category_fixtures.by_name["图书教材"]
        p1 = product_factory(
            seller,
            cat_digital.id,
            title="机械键盘",
            price="199.00",
            campus_id=school_fixtures.east.id,
        )
        p2 = product_factory(
            seller, cat_digital.id, title="蓝牙耳机", price="89.50",
            condition="as_new", campus_id=school_fixtures.west.id,
        )
        p3 = product_factory(
            seller, cat_book.id, title="高等数学教材", price="25.00", condition="good"
        )
        p4 = product_factory(seller, cat_book.id, title="已下架商品", status="off_sale")
        p5 = product_factory(seller, cat_book.id, title="已售商品", status="sold")
        # B 校商品：绝不可见
        outsider = _verified(
            user_factory, school_fixtures.single, school_fixtures.main_campus
        )
        p6 = product_factory(outsider, cat_digital.id, school_id=school_fixtures.single.id)
        return seller, (p1, p2, p3, p4, p5, p6)

    def test_list_returns_own_school_on_sale_only(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        seller, (p1, p2, p3, _p4, _p5, _p6) = self._seed_products(
            school_fixtures, user_factory, category_fixtures, product_factory
        )
        viewer = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        res = client.get(PRODUCTS_URL, headers=make_auth_header(viewer["id"]))
        assert res.status_code == 200
        data = res.get_json()["data"]
        assert data["total"] == 3
        assert {item["id"] for item in data["items"]} == {p1.id, p2.id, p3.id}
        assert data["page"] == 1 and data["pages"] == 1

    def test_filter_by_category(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        self._seed_products(school_fixtures, user_factory, category_fixtures, product_factory)
        viewer = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        cat_id = category_fixtures.by_name["数码电子"].id
        res = client.get(
            f"{PRODUCTS_URL}?category_id={cat_id}", headers=make_auth_header(viewer["id"])
        )
        items = res.get_json()["data"]["items"]
        assert len(items) == 2
        assert all(i["category"]["id"] == cat_id for i in items)

    def test_filter_by_condition(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        self._seed_products(school_fixtures, user_factory, category_fixtures, product_factory)
        viewer = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        res = client.get(
            f"{PRODUCTS_URL}?condition=as_new", headers=make_auth_header(viewer["id"])
        )
        items = res.get_json()["data"]["items"]
        assert [i["condition"] for i in items] == ["as_new"]

    def test_filter_by_price_range(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        seller, (p1, p2, p3, *_rest) = self._seed_products(
            school_fixtures, user_factory, category_fixtures, product_factory
        )
        viewer = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        res = client.get(
            f"{PRODUCTS_URL}?price_min=50&price_max=200", headers=make_auth_header(viewer["id"])
        )
        assert {i["id"] for i in res.get_json()["data"]["items"]} == {p1.id, p2.id}
        # 边界含等号
        res = client.get(
            f"{PRODUCTS_URL}?price_min=25&price_max=25", headers=make_auth_header(viewer["id"])
        )
        assert [i["id"] for i in res.get_json()["data"]["items"]] == [p3.id]
        _ = (p1, p2, p3)

    def test_price_min_greater_than_max_9001(
        self, client, db_create_all, school_fixtures, user_factory, make_auth_header
    ):
        viewer = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        res = client.get(
            f"{PRODUCTS_URL}?price_min=100&price_max=50", headers=make_auth_header(viewer["id"])
        )
        body = res.get_json()
        assert (res.status_code, body["code"]) == (422, 9001)
        assert "price_min" in body["data"]["fields"]

    def test_filter_by_campus(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        _seller, (p1, p2, *_rest) = self._seed_products(
            school_fixtures, user_factory, category_fixtures, product_factory
        )
        viewer = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        res = client.get(
            f"{PRODUCTS_URL}?campus_id={school_fixtures.west.id}",
            headers=make_auth_header(viewer["id"]),
        )
        items = res.get_json()["data"]["items"]
        assert [i["id"] for i in items] == [p2.id]
        _ = p1

    def test_filter_by_keyword_like(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        self._seed_products(school_fixtures, user_factory, category_fixtures, product_factory)
        viewer = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        res = client.get(
            f"{PRODUCTS_URL}?keyword=键盘", headers=make_auth_header(viewer["id"])
        )
        items = res.get_json()["data"]["items"]
        assert [i["title"] for i in items] == ["机械键盘"]

    def test_sort_three_options(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        self._seed_products(school_fixtures, user_factory, category_fixtures, product_factory)
        viewer = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        asc = client.get(
            f"{PRODUCTS_URL}?sort=price_asc", headers=make_auth_header(viewer["id"])
        ).get_json()["data"]["items"]
        desc = client.get(
            f"{PRODUCTS_URL}?sort=price_desc", headers=make_auth_header(viewer["id"])
        ).get_json()["data"]["items"]
        prices_asc = [i["price"] for i in asc]
        prices_desc = [i["price"] for i in desc]
        assert prices_asc == sorted(prices_asc)
        assert prices_desc == sorted(prices_desc, reverse=True)

    def test_invalid_filters_9001(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        make_auth_header,
    ):
        viewer = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        headers = make_auth_header(viewer["id"])
        cases = [
            ("condition=brand", "condition"),
            ("sort=hot", "sort"),
            ("category_id=424242", "category_id"),
            ("campus_id=424242", "campus_id"),
            ("keyword=" + "x" * 101, "keyword"),
            ("price_min=abc", "price_min"),
        ]
        for query, field in cases:
            res = client.get(f"{PRODUCTS_URL}?{query}", headers=headers)
            body = res.get_json()
            assert (res.status_code, body["code"]) == (422, 9001), query
            assert field in body["data"]["fields"], query

    def test_pagination(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        self._seed_products(school_fixtures, user_factory, category_fixtures, product_factory)
        viewer = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        res = client.get(
            f"{PRODUCTS_URL}?page_size=2&page=2", headers=make_auth_header(viewer["id"])
        )
        data = res.get_json()["data"]
        assert data["page"] == 2 and data["page_size"] == 2
        assert data["total"] == 3 and data["pages"] == 2
        assert len(data["items"]) == 1

    def test_admin_scope_all_sees_both_schools(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        self._seed_products(school_fixtures, user_factory, category_fixtures, product_factory)
        admin = user_factory(role="admin")
        res = client.get(PRODUCTS_URL, headers=make_auth_header(admin["id"]))
        data = res.get_json()["data"]
        assert data["total"] == 4  # A 校 3 件 + B 校 1 件

    def test_unverified_list_1004(
        self, client, db_create_all, user_factory, make_auth_header
    ):
        user = user_factory(auth_status="unverified")
        res = client.get(PRODUCTS_URL, headers=make_auth_header(user["id"]))
        assert (res.status_code, res.get_json()["code"]) == (403, 1004)


# ============================================================
# 我的商品
# ============================================================


class TestMineProducts:
    def test_mine_default_excludes_deleted(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        cat = category_fixtures.items[0].id
        on_sale = product_factory(seller, cat, title="在售")
        off_sale = product_factory(seller, cat, title="已下架", status="off_sale")
        sold = product_factory(seller, cat, title="已售", status="sold")
        deleted = product_factory(seller, cat, title="已删", status="deleted")
        other = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        others = product_factory(other, cat, title="别人的")
        res = client.get(f"{PRODUCTS_URL}/mine", headers=make_auth_header(seller["id"]))
        data = res.get_json()["data"]
        ids = {i["id"] for i in data["items"]}
        assert ids == {on_sale.id, off_sale.id, sold.id}
        assert deleted.id not in ids and others.id not in ids

    def test_mine_status_filter(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        cat = category_fixtures.items[0].id
        on_sale = product_factory(seller, cat)
        product_factory(seller, cat, status="off_sale")
        res = client.get(
            f"{PRODUCTS_URL}/mine?status=on_sale", headers=make_auth_header(seller["id"])
        )
        data = res.get_json()["data"]
        assert [i["id"] for i in data["items"]] == [on_sale.id]

    def test_mine_invalid_status_9001(
        self, client, db_create_all, school_fixtures, user_factory, make_auth_header
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        res = client.get(
            f"{PRODUCTS_URL}/mine?status=sold_out", headers=make_auth_header(seller["id"])
        )
        assert (res.status_code, res.get_json()["code"]) == (422, 9001)

    def test_mine_admin_returns_empty(
        self, client, db_create_all, user_factory, make_auth_header
    ):
        admin = user_factory(role="admin")
        res = client.get(f"{PRODUCTS_URL}/mine", headers=make_auth_header(admin["id"]))
        assert res.get_json()["data"]["total"] == 0


# ============================================================
# b2be2 接口函数（Interfaces 节签名与语义）
# ============================================================


class TestB2be2HelperFunctions:
    def test_get_on_sale_by_ids(
        self, app, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory,
    ):
        from src.services import product_service

        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        cat = category_fixtures.items[0].id
        p1 = product_factory(seller, cat)
        p2 = product_factory(seller, cat, status="off_sale")  # 非在售剔除
        outsider = _verified(
            user_factory, school_fixtures.single, school_fixtures.main_campus
        )
        p3 = product_factory(outsider, cat, school_id=school_fixtures.single.id)
        with app.app_context():
            rows = product_service.get_on_sale_by_ids(
                school_fixtures.multi.id, [p3.id, p1.id, p2.id]
            )
            assert [p.id for p in rows] == [p1.id]  # 按传入序 + 本校 + 在售过滤
            all_rows = product_service.get_on_sale_by_ids(
                None, [p3.id, p1.id], scope_all=True
            )
            assert [p.id for p in all_rows] == [p3.id, p1.id]  # 同样按传入序

    def test_list_on_sale_random(
        self, app, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory,
    ):
        from src.services import product_service

        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        cat = category_fixtures.items[0].id
        p1 = product_factory(seller, cat)
        p2 = product_factory(seller, cat)
        outsider = _verified(
            user_factory, school_fixtures.single, school_fixtures.main_campus
        )
        product_factory(outsider, cat, school_id=school_fixtures.single.id)
        with app.app_context():
            rows = product_service.list_on_sale_random(
                school_fixtures.multi.id, [p2.id], 1
            )
            assert [p.id for p in rows] == [p1.id]  # 排除 exclude_ids、限数、本校
            assert product_service.list_on_sale_random(school_fixtures.multi.id, [], 0) == []

    def test_get_active_by_id(
        self, app, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory,
    ):
        from src.services import product_service

        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        cat = category_fixtures.items[0].id
        on_sale = product_factory(seller, cat)
        deleted = product_factory(seller, cat, status="deleted")
        with app.app_context():
            assert product_service.get_active_by_id(on_sale.id).id == on_sale.id
            assert product_service.get_active_by_id(deleted.id) is None
            assert product_service.get_active_by_id(424242) is None


# ============================================================
# 商品域测试（二）：编辑 / 上下架 / 删除（事件与缓存失效断言见
# test_product_events.py，此处覆盖状态机矩阵与响应形态）
# ============================================================


class TestUpdateProduct:
    def _setup(self, school_fixtures, user_factory, category_fixtures, product_factory, **kw):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id, **kw)
        image_ids = [pi.image_id for pi in product.product_images]
        return seller, product, image_ids

    def test_update_full_replacement(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, owned_product_images, make_auth_header,
    ):
        """全量替换：字段更新 + image_ids 重写（数组序=排序）。"""
        seller, product, _old = self._setup(
            school_fixtures, user_factory, category_fixtures, product_factory
        )
        new_images = owned_product_images(seller["id"], 2)
        payload = _payload(
            category_fixtures.by_name["图书教材"].id,
            new_images,
            title="降价急出",
            description="新描述",
            price=179.5,
            condition="good",
        )
        res = client.put(
            f"{PRODUCTS_URL}/{product.id}",
            headers=make_auth_header(seller["id"]),
            json=payload,
        )
        assert res.status_code == 200
        data = res.get_json()["data"]
        assert data["title"] == "降价急出"
        assert data["price"] == 179.5
        assert data["category"]["name"] == "图书教材"
        assert [img["id"] for img in data["images"]] == new_images
        assert data["cover"]["id"] == new_images[0]

    def test_update_off_sale_keeps_status(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, owned_product_images, make_auth_header,
    ):
        """off_sale 可编辑，编辑后仍 off_sale。"""
        seller, product, _old = self._setup(
            school_fixtures, user_factory, category_fixtures, product_factory,
            status="off_sale",
        )
        new_images = owned_product_images(seller["id"], 1)
        payload = _payload(category_fixtures.items[0].id, new_images, title="下架中编辑")
        res = client.put(
            f"{PRODUCTS_URL}/{product.id}",
            headers=make_auth_header(seller["id"]),
            json=payload,
        )
        assert res.status_code == 200
        assert res.get_json()["data"]["status"] == "off_sale"

    @pytest.mark.parametrize("status", ["trading", "sold"])
    def test_update_trading_sold_3001(
        self, status, client, db_create_all, school_fixtures, user_factory,
        category_fixtures, product_factory, owned_product_images, make_auth_header,
    ):
        seller, product, _old = self._setup(
            school_fixtures, user_factory, category_fixtures, product_factory, status=status
        )
        new_images = owned_product_images(seller["id"], 1)
        res = client.put(
            f"{PRODUCTS_URL}/{product.id}",
            headers=make_auth_header(seller["id"]),
            json=_payload(category_fixtures.items[0].id, new_images),
        )
        body = res.get_json()
        assert (res.status_code, body["code"]) == (409, 3001)
        assert status_label(status) in body["message"]

    def test_update_deleted_404(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, owned_product_images, make_auth_header,
    ):
        seller, product, _old = self._setup(
            school_fixtures, user_factory, category_fixtures, product_factory,
            status="deleted",
        )
        new_images = owned_product_images(seller["id"], 1)
        res = client.put(
            f"{PRODUCTS_URL}/{product.id}",
            headers=make_auth_header(seller["id"]),
            json=_payload(category_fixtures.items[0].id, new_images),
        )
        assert (res.status_code, res.get_json()["code"]) == (404, 9002)

    def test_update_not_owner_404(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, owned_product_images, make_auth_header,
    ):
        """同校他人商品 → 404/9002（与不存在同语义，防探测）。"""
        seller, product, _old = self._setup(
            school_fixtures, user_factory, category_fixtures, product_factory
        )
        stranger = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        stranger_images = owned_product_images(stranger["id"], 1)
        res = client.put(
            f"{PRODUCTS_URL}/{product.id}",
            headers=make_auth_header(stranger["id"]),
            json=_payload(category_fixtures.items[0].id, stranger_images),
        )
        assert (res.status_code, res.get_json()["code"]) == (404, 9002)

    def test_update_other_school_404(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, owned_product_images, make_auth_header,
    ):
        seller, product, _old = self._setup(
            school_fixtures, user_factory, category_fixtures, product_factory
        )
        outsider = _verified(
            user_factory, school_fixtures.single, school_fixtures.main_campus
        )
        outsider_images = owned_product_images(outsider["id"], 1)
        res = client.put(
            f"{PRODUCTS_URL}/{product.id}",
            headers=make_auth_header(outsider["id"]),
            json=_payload(category_fixtures.items[0].id, outsider_images),
        )
        assert (res.status_code, res.get_json()["code"]) == (404, 9002)

    def test_update_admin_9003(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, owned_product_images, make_auth_header,
    ):
        seller, product, _old = self._setup(
            school_fixtures, user_factory, category_fixtures, product_factory
        )
        admin = user_factory(role="admin")
        admin_images = owned_product_images(admin["id"], 1)
        res = client.put(
            f"{PRODUCTS_URL}/{product.id}",
            headers=make_auth_header(admin["id"]),
            json=_payload(category_fixtures.items[0].id, admin_images),
        )
        assert (res.status_code, res.get_json()["code"]) == (409, 9003)

    def test_update_invalid_fields_9001(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        """编辑路径同样独立复验字段（不信任客户端）。"""
        seller, product, _old = self._setup(
            school_fixtures, user_factory, category_fixtures, product_factory
        )
        res = client.put(
            f"{PRODUCTS_URL}/{product.id}",
            headers=make_auth_header(seller["id"]),
            json={"title": "x", "description": "y", "price": 0,
                  "category_id": product.category_id, "condition": "good",
                  "image_ids": []},
        )
        assert (res.status_code, res.get_json()["code"]) == (422, 9001)


class TestChangeStatus:
    def _patch(self, client, headers, product_id, status):
        return client.patch(
            f"{PRODUCTS_URL}/{product_id}/status", headers=headers, json={"status": status}
        )

    def test_on_sale_to_off_sale_and_back(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        headers = make_auth_header(seller["id"])
        res = self._patch(client, headers, product.id, "off_sale")
        assert res.status_code == 200
        assert res.get_json()["data"]["status"] == "off_sale"
        # ProductSummary 形态（无 description/images 等 detail 字段）
        assert "description" not in res.get_json()["data"]
        res = self._patch(client, headers, product.id, "on_sale")
        assert res.get_json()["data"]["status"] == "on_sale"

    def test_same_status_idempotent_200(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        res = self._patch(client, make_auth_header(seller["id"]), product.id, "on_sale")
        assert res.status_code == 200
        assert res.get_json()["data"]["status"] == "on_sale"

    def test_forced_off_reshelve_3002(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        """off_sale + forced_off → 重新上架 3002（仅管理员可恢复，b5 写入标记）。"""
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(
            seller, category_fixtures.items[0].id, status="off_sale", forced_off=True
        )
        res = self._patch(client, make_auth_header(seller["id"]), product.id, "on_sale")
        body = res.get_json()
        assert (res.status_code, body["code"]) == (403, 3002)

    @pytest.mark.parametrize("status", ["trading", "sold"])
    def test_trading_sold_3001(
        self, status, client, db_create_all, school_fixtures, user_factory,
        category_fixtures, product_factory, make_auth_header,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id, status=status)
        res = self._patch(client, make_auth_header(seller["id"]), product.id, "off_sale")
        body = res.get_json()
        assert (res.status_code, body["code"]) == (409, 3001)

    def test_invalid_target_status_9001(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        res = self._patch(client, make_auth_header(seller["id"]), product.id, "sold")
        assert (res.status_code, res.get_json()["code"]) == (422, 9001)

    def test_not_owner_or_nonexistent_404(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        stranger = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        res = self._patch(client, make_auth_header(stranger["id"]), product.id, "off_sale")
        assert (res.status_code, res.get_json()["code"]) == (404, 9002)
        res = self._patch(client, make_auth_header(seller["id"]), 424242, "off_sale")
        assert (res.status_code, res.get_json()["code"]) == (404, 9002)


class TestDeleteProduct:
    def test_delete_on_sale_200_then_invisible(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        headers = make_auth_header(seller["id"])
        res = client.delete(f"{PRODUCTS_URL}/{product.id}", headers=headers)
        assert res.status_code == 200
        assert res.get_json()["data"] is None
        # 详情 404；mine 缺省不可见
        assert client.get(f"{PRODUCTS_URL}/{product.id}", headers=headers).status_code == 404
        mine = client.get(f"{PRODUCTS_URL}/mine", headers=headers).get_json()["data"]
        assert product.id not in {i["id"] for i in mine["items"]}

    def test_delete_off_sale_200(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id, status="off_sale")
        res = client.delete(
            f"{PRODUCTS_URL}/{product.id}", headers=make_auth_header(seller["id"])
        )
        assert res.status_code == 200

    @pytest.mark.parametrize("status", ["trading", "sold"])
    def test_delete_trading_sold_3001(
        self, status, client, db_create_all, school_fixtures, user_factory,
        category_fixtures, product_factory, make_auth_header,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id, status=status)
        res = client.delete(
            f"{PRODUCTS_URL}/{product.id}", headers=make_auth_header(seller["id"])
        )
        assert (res.status_code, res.get_json()["code"]) == (409, 3001)

    def test_delete_already_deleted_404(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id, status="deleted")
        res = client.delete(
            f"{PRODUCTS_URL}/{product.id}", headers=make_auth_header(seller["id"])
        )
        assert (res.status_code, res.get_json()["code"]) == (404, 9002)

    def test_delete_not_owner_404(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product = product_factory(seller, category_fixtures.items[0].id)
        stranger = _verified(user_factory, school_fixtures.multi, school_fixtures.west)
        res = client.delete(
            f"{PRODUCTS_URL}/{product.id}", headers=make_auth_header(stranger["id"])
        )
        assert (res.status_code, res.get_json()["code"]) == (404, 9002)


class TestUpdateImageReplacementSameSet:
    """同集替换回归（真机 MySQL 发现）：UOW 先 INSERT 后 DELETE 撞
    uk_product_image；修复后须先删旧 flush 再插入。"""

    def _two_image_product(self, school_fixtures, user_factory, category_fixtures,
                           product_factory, seller):
        product = product_factory(
            seller, category_fixtures.items[0].id, image_count=2
        )
        image_ids = [pi.image_id for pi in product.product_images]
        return product, image_ids

    def test_update_keep_same_images(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        """image_ids 原样保留只改价格 → 200，不撞唯一约束。"""
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product, image_ids = self._two_image_product(
            school_fixtures, user_factory, category_fixtures, product_factory, seller
        )
        res = client.put(
            f"{PRODUCTS_URL}/{product.id}",
            headers=make_auth_header(seller["id"]),
            json=_payload(
                category_fixtures.items[0].id, image_ids, price=55.0,
                description="测试描述",
            ),
        )
        assert res.status_code == 200
        data = res.get_json()["data"]
        assert [img["id"] for img in data["images"]] == image_ids
        assert data["price"] == 55.0

    def test_update_reorder_same_images(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, make_auth_header,
    ):
        """同集重排：数组序即新展示排序。"""
        seller = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        product, image_ids = self._two_image_product(
            school_fixtures, user_factory, category_fixtures, product_factory, seller
        )
        reordered = list(reversed(image_ids))
        res = client.put(
            f"{PRODUCTS_URL}/{product.id}",
            headers=make_auth_header(seller["id"]),
            json=_payload(
                category_fixtures.items[0].id, reordered,
                title="测试商品", description="测试描述",
            ),
        )
        assert res.status_code == 200
        assert [img["id"] for img in res.get_json()["data"]["images"]] == reordered
