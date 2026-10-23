"""分类域测试：verified 可读 / 未认证 1004 / 仅 enabled / 排序 / 缓存命中。"""

from src.model import Category, db
from tests.test_products import _verified

CATEGORIES_URL = "/api/categories"


class TestListCategories:
    def test_verified_can_read_sorted(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        make_auth_header,
    ):
        """仅 enabled，按 sort_order、id 升序；不分页。"""
        db.session.add(Category(name="停用分类", sort_order=0, status="disabled"))
        db.session.commit()
        viewer = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        res = client.get(CATEGORIES_URL, headers=make_auth_header(viewer["id"]))
        assert res.status_code == 200
        data = res.get_json()["data"]
        assert [c["name"] for c in data] == [
            "数码电子", "图书教材", "生活用品", "运动户外", "服饰鞋包", "其他",
        ]
        assert all(set(c) == {"id", "name"} for c in data)  # CategoryRef 形态

    def test_sort_order_then_id(
        self, client, db_create_all, school_fixtures, user_factory, make_auth_header
    ):
        """同 sort_order 按 id 升序兜底。"""
        first = Category(name="甲", sort_order=1, status="enabled")
        db.session.add(first)
        db.session.flush()
        second = Category(name="乙", sort_order=1, status="enabled")
        db.session.add(second)
        db.session.commit()
        viewer = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        data = client.get(
            CATEGORIES_URL, headers=make_auth_header(viewer["id"])
        ).get_json()["data"]
        assert data.index(next(c for c in data if c["name"] == "甲")) < data.index(
            next(c for c in data if c["name"] == "乙")
        )

    def test_unverified_1004(self, client, db_create_all, user_factory, make_auth_header):
        user = user_factory(auth_status="unverified")
        res = client.get(CATEGORIES_URL, headers=make_auth_header(user["id"]))
        assert (res.status_code, res.get_json()["code"]) == (403, 1004)

    def test_anonymous_401(self, client, db_create_all):
        res = client.get(CATEGORIES_URL)
        assert (res.status_code, res.get_json()["code"]) == (401, 1001)

    def test_cache_hit_path(
        self, client, db_create_all, school_fixtures, user_factory, category_fixtures,
        make_auth_header, fake_redis,
    ):
        """首查写缓存（product:category:all）；此后库内停用分类不影响响应
        （缓存命中证据）；b5 管理员维护后的失效不在本批范围。"""
        viewer = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        headers = make_auth_header(viewer["id"])
        first = client.get(CATEGORIES_URL, headers=headers)
        assert first.status_code == 200
        assert "product:category:all" in fake_redis.store
        # 直接改库：新停用一个分类，缓存未失效前响应不变
        victim = category_fixtures.by_name["其他"]
        victim.status = "disabled"
        db.session.commit()
        second = client.get(CATEGORIES_URL, headers=headers)
        assert len(second.get_json()["data"]) == len(first.get_json()["data"])

    def test_post_categories_405_9007(
        self, client, db_create_all, school_fixtures, user_factory, make_auth_header
    ):
        """全局 405 → envelope 9007（本文件顺带覆盖该横切行为）。"""
        viewer = _verified(user_factory, school_fixtures.multi, school_fixtures.east)
        res = client.post(
            CATEGORIES_URL, headers=make_auth_header(viewer["id"]), json={}
        )
        assert res.status_code == 405
        assert res.get_json()["code"] == 9007
