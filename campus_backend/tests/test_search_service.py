"""search_service / search 路由测试：召回精筛保序分页、业务过滤、LIKE 降级。

正常链路经 fake_chroma（预置受控向量，验证相似度序）+ fake_embedding
（指令前缀拼接断言）；降级经桩 fail 开关演练。fake_chroma 种子向量由
已知查询向量与固定正交轴混合构造，余弦序确定可控。
"""

from types import SimpleNamespace

import pytest

SEARCH_URL = "/api/products/search"
QUERY = "机械键盘"


@pytest.fixture()
def scene(
    app, db_create_all, school_fixtures, user_factory, category_fixtures, product_factory
):
    """两校用户与四件商品：本校 a/b/c + 他校 d。"""
    seller = user_factory(
        username="seller01",
        school_id=school_fixtures.multi.id,
        campus_id=school_fixtures.east.id,
        auth_status="approved",
    )
    other = user_factory(
        username="seller02",
        school_id=school_fixtures.single.id,
        auth_status="approved",
    )
    viewer = user_factory(
        username="viewer01",
        school_id=school_fixtures.multi.id,
        campus_id=school_fixtures.west.id,
        auth_status="approved",
    )
    cat_digital = category_fixtures.by_name["数码电子"]
    cat_book = category_fixtures.by_name["图书教材"]
    products = {
        "a": product_factory(seller, cat_digital.id, title="机械键盘 A", price="100.00"),
        "b": product_factory(seller, cat_digital.id, title="键盘 B", price="500.00"),
        "c": product_factory(seller, cat_book.id, title="旧书 C", price="10.00"),
        "d": product_factory(other, cat_digital.id, title="他校商品 D"),
    }
    return SimpleNamespace(
        seller=seller,
        viewer=viewer,
        products=products,
        cat_digital=cat_digital,
        cat_book=cat_book,
        school_id=school_fixtures.multi.id,
        other_school_id=school_fixtures.single.id,
    )


def _query_vector(app, q: str) -> list[float]:
    """与 embedding_client 相同拼接规则下的桩查询向量（conftest 确定性伪向量）。"""
    from tests.conftest import _pseudo_vector

    prefix = app.config["EMBEDDING_QUERY_PREFIX"]
    return _pseudo_vector(f"{prefix}\n{q}", app.config["EMBEDDING_DIM"])


def _seed(
    fake_chroma, product, query_vector, weight: float, *, school_id: int, status: str = "on_sale"
):
    """种子向量 = weight×查询向量 + (1-weight)×固定正交轴（weight 越大余弦越近）。"""
    from src.services.vector_service import build_text

    dim = len(query_vector)
    axis = 0 if abs(query_vector[0]) < 0.95 else 1
    noise = [0.0] * dim
    noise[axis] = 1.0
    mixed = [
        weight * qv + (1 - weight) * nz
        for qv, nz in zip(query_vector, noise, strict=False)
    ]
    norm = sum(c * c for c in mixed) ** 0.5 or 1.0
    fake_chroma.upsert(
        ids=[str(product.id)],
        embeddings=[[c / norm for c in mixed]],
        documents=[build_text(product, "")],
        metadatas=[{"school_id": school_id, "status": status}],
    )


class TestVectorPath:
    def test_recall_order_filter_pagination(
        self, app, client, scene, fake_mongo, fake_chroma, fake_embedding, make_auth_header
    ):
        qv = _query_vector(app, QUERY)
        # 相似度序：a(0.95) > b(0.75) > c(0.5)；d 为他校且最近也不可见
        _seed(fake_chroma, scene.products["a"], qv, 0.95, school_id=scene.school_id)
        _seed(fake_chroma, scene.products["b"], qv, 0.75, school_id=scene.school_id)
        _seed(fake_chroma, scene.products["c"], qv, 0.5, school_id=scene.school_id)
        _seed(fake_chroma, scene.products["d"], qv, 0.99, school_id=scene.other_school_id)

        res = client.get(
            SEARCH_URL,
            headers=make_auth_header(scene.viewer["id"]),
            query_string={"q": QUERY},
        )

        assert res.status_code == 200
        data = res.get_json()["data"]
        ids = [item["id"] for item in data["items"]]
        assert ids == [
            scene.products["a"].id,
            scene.products["b"].id,
            scene.products["c"].id,
        ]
        assert data["total"] == 3
        assert "degraded" not in data
        # 指令前缀拼接发生（四要素①）
        prefix = app.config["EMBEDDING_QUERY_PREFIX"]
        assert fake_embedding.calls[0].startswith(prefix)

    def test_where_excludes_off_sale(
        self, app, client, scene, fake_mongo, fake_chroma, fake_embedding, make_auth_header
    ):
        qv = _query_vector(app, QUERY)
        _seed(fake_chroma, scene.products["a"], qv, 0.5, school_id=scene.school_id)
        _seed(
            fake_chroma,
            scene.products["b"],
            qv,
            0.99,
            school_id=scene.school_id,
            status="off_sale",  # 最相似但非在售
        )

        res = client.get(
            SEARCH_URL,
            headers=make_auth_header(scene.viewer["id"]),
            query_string={"q": QUERY},
        )

        ids = [item["id"] for item in res.get_json()["data"]["items"]]
        assert ids == [scene.products["a"].id]

    def test_business_filters_keep_order(
        self, app, client, scene, fake_mongo, fake_chroma, fake_embedding, make_auth_header
    ):
        """分类/价格过滤剔除不匹配 id；保序不因分页打乱（逐页拼接序不变）。"""
        qv = _query_vector(app, QUERY)
        _seed(fake_chroma, scene.products["a"], qv, 0.95, school_id=scene.school_id)
        _seed(fake_chroma, scene.products["b"], qv, 0.75, school_id=scene.school_id)
        _seed(fake_chroma, scene.products["c"], qv, 0.5, school_id=scene.school_id)
        headers = make_auth_header(scene.viewer["id"])

        # 分类过滤：仅数码电子（a、b）
        res = client.get(
            SEARCH_URL,
            headers=headers,
            query_string={"q": QUERY, "category_id": scene.cat_digital.id},
        )
        ids = [i["id"] for i in res.get_json()["data"]["items"]]
        assert ids == [scene.products["a"].id, scene.products["b"].id]

        # 价格区间：≤200 剔除 b（500 元）
        res = client.get(
            SEARCH_URL, headers=headers, query_string={"q": QUERY, "price_max": "200"}
        )
        ids = [i["id"] for i in res.get_json()["data"]["items"]]
        assert ids == [scene.products["a"].id, scene.products["c"].id]

        # 分页不打乱相似度序：page_size=1 三页恰好 a → b → c
        seen = []
        for page in (1, 2, 3):
            res = client.get(
                SEARCH_URL,
                headers=headers,
                query_string={"q": QUERY, "page": page, "page_size": 1},
            )
            items = res.get_json()["data"]["items"]
            if items:
                seen.append(items[0]["id"])
        assert seen == [
            scene.products["a"].id,
            scene.products["b"].id,
            scene.products["c"].id,
        ]

    def test_results_not_cached(
        self,
        app,
        client,
        scene,
        fake_mongo,
        fake_chroma,
        fake_embedding,
        fake_redis,
        make_auth_header,
    ):
        qv = _query_vector(app, QUERY)
        _seed(fake_chroma, scene.products["a"], qv, 0.9, school_id=scene.school_id)
        client.get(
            SEARCH_URL,
            headers=make_auth_header(scene.viewer["id"]),
            query_string={"q": QUERY},
        )
        assert not any("search" in key for key in fake_redis.store)  # 结果不写缓存


class TestDegraded:
    def test_embedding_down_like_fallback(
        self,
        app,
        client,
        scene,
        db_create_all,
        fake_mongo,
        fake_chroma,
        fake_embedding,
        fake_redis,
        make_auth_header,
        caplog,
    ):
        fake_embedding.fail = True
        with caplog.at_level("INFO", logger="src.services.search_service"):
            res = client.get(
                SEARCH_URL,
                headers=make_auth_header(scene.viewer["id"]),
                query_string={"q": "键盘"},
            )

        assert res.status_code == 200
        data = res.get_json()["data"]
        assert data["degraded"] is True
        assert data["degraded_reason"]
        ids = [item["id"] for item in data["items"]]
        # LIKE 标题匹配：含「键盘」的 a/b 命中（created_at 倒序 → b 在前）
        assert ids == [scene.products["b"].id, scene.products["a"].id]
        assert any("搜索降级" in r.message for r in caplog.records)

    def test_chroma_down_like_fallback(
        self,
        app,
        client,
        scene,
        db_create_all,
        fake_mongo,
        fake_chroma,
        fake_embedding,
        fake_redis,
        make_auth_header,
    ):
        """探测可用但 Chroma 真实调用异常 → 异常路径同样降级（双判定）。"""
        _seed(
            fake_chroma,
            scene.products["a"],
            _query_vector(app, QUERY),
            0.9,
            school_id=scene.school_id,
        )
        fake_chroma.fail["fail"] = True  # query 时抛异常

        res = client.get(
            SEARCH_URL,
            headers=make_auth_header(scene.viewer["id"]),
            query_string={"q": "键盘"},
        )

        assert res.status_code == 200
        data = res.get_json()["data"]
        assert data["degraded"] is True
        ids = [item["id"] for item in data["items"]]
        assert set(ids) == {scene.products["a"].id, scene.products["b"].id}


class TestAdminScope:
    def test_admin_search_cross_school_where_only_status(
        self,
        app,
        client,
        scene,
        user_factory,
        product_factory,
        fake_chroma,
        fake_embedding,
        make_auth_header,
        monkeypatch,
    ):
        """S-5：管理员（scope_all）跨校只读——chroma where 仅 status 条件，
        他校在售商品可达；他校非在售仍被 where 过滤。"""
        admin = user_factory(
            username="admin01",
            role="admin",
            school_id=scene.school_id,
            auth_status="approved",
        )
        # 他校下架商品：where 仅 status 时也必须被过滤
        other_seller = {
            "id": scene.products["d"].seller_id,
            "school_id": scene.other_school_id,
            "campus_id": None,
        }
        off_sale_other = product_factory(
            other_seller,
            scene.cat_digital.id,
            title="他校下架 E",
            status="off_sale",
        )

        qv = _query_vector(app, QUERY)
        _seed(fake_chroma, scene.products["a"], qv, 0.95, school_id=scene.school_id)
        _seed(fake_chroma, scene.products["d"], qv, 0.99, school_id=scene.other_school_id)
        _seed(
            fake_chroma,
            off_sale_other,
            qv,
            0.98,
            school_id=scene.other_school_id,
            status="off_sale",
        )

        # 捕获 chroma where 实参
        captured: dict = {}
        original_query = fake_chroma.query

        def _spy(query_embeddings, n_results=10, where=None):
            captured["where"] = where
            return original_query(
                query_embeddings, n_results=n_results, where=where
            )

        monkeypatch.setattr(fake_chroma, "query", _spy)

        res = client.get(
            SEARCH_URL,
            headers=make_auth_header(admin["id"]),
            query_string={"q": QUERY},
        )

        assert res.status_code == 200
        assert captured["where"] == {"status": "on_sale"}  # 无 school_id 条件
        ids = [item["id"] for item in res.get_json()["data"]["items"]]
        # 跨校可达：他校 d（0.99 最相似）排在本校 a 之前；下架 E 被过滤
        assert ids == [scene.products["d"].id, scene.products["a"].id]


class TestValidation:
    def test_q_empty_9001(
        self, client, db_create_all, school_fixtures, user_factory, make_auth_header
    ):
        viewer = user_factory(
            username="viewer01",
            school_id=school_fixtures.multi.id,
            auth_status="approved",
        )
        headers = make_auth_header(viewer["id"])

        res = client.get(SEARCH_URL, headers=headers)  # 缺 q
        assert res.status_code == 422
        assert res.get_json()["code"] == 9001
        assert "q" in res.get_json()["data"]["fields"]

        res = client.get(SEARCH_URL, headers=headers, query_string={"q": "   "})  # 空白
        assert res.get_json()["code"] == 9001

    def test_unverified_1004(
        self, client, db_create_all, school_fixtures, user_factory, make_auth_header
    ):
        user = user_factory(username="unverified01", auth_status="unverified")
        res = client.get(
            SEARCH_URL,
            headers=make_auth_header(user["id"]),
            query_string={"q": "键盘"},
        )
        assert res.status_code == 403
        assert res.get_json()["code"] == 1004
