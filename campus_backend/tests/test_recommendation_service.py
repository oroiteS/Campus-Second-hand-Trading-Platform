"""recommendation_service / recommendations 路由测试：配比、冷启动、缓存、降级矩阵。

画像召回经 fake_chroma 种子向量（以画像向量为准构造相似度序）；随机池
为 MySQL 在售商品（45 件）。
"""

from types import SimpleNamespace

import pytest

from tests.conftest import _pseudo_vector

HOME_URL = "/api/recommendations/home"


@pytest.fixture()
def world(
    app, db_create_all, school_fixtures, user_factory, category_fixtures, product_factory
):
    """本校 45 件在售（含 viewer 自有 3 件）+ 3 件下架 + 他校 5 件；viewer/管理员。"""
    seller = user_factory(
        username="seller01",
        school_id=school_fixtures.multi.id,
        campus_id=school_fixtures.east.id,
        auth_status="approved",
    )
    viewer = user_factory(
        username="viewer01",
        school_id=school_fixtures.multi.id,
        campus_id=school_fixtures.west.id,
        auth_status="approved",
    )
    admin = user_factory(username="admin01", role="admin", school_id=school_fixtures.multi.id)
    other = user_factory(
        username="seller02", school_id=school_fixtures.single.id, auth_status="approved"
    )
    category = category_fixtures.by_name["数码电子"]
    pool = [
        product_factory(seller, category.id, title=f"在售商品{i:02d}") for i in range(45)
    ]
    own = [product_factory(viewer, category.id, title=f"自有商品{i}") for i in range(3)]
    off_sale = [
        product_factory(seller, category.id, title=f"下架商品{i}", status="off_sale")
        for i in range(3)
    ]
    other_school = [
        product_factory(other, category.id, title=f"他校商品{i}") for i in range(5)
    ]
    return SimpleNamespace(
        seller=seller,
        viewer=viewer,
        admin=admin,
        pool=pool,  # 45 件他人在售
        own=own,
        off_sale=off_sale,
        other_school=other_school,
        school_id=school_fixtures.multi.id,
        category=category,
    )


def _seed_profile(fake_mongo, app, user_id: int) -> list[float]:
    """写入画像向量（确定性伪向量），返回同一向量供 Chroma 种子对齐。"""
    vector = _pseudo_vector("profile-seed", app.config["EMBEDDING_DIM"])
    fake_mongo["user_profiles"].update_one(
        {"user_id": user_id},
        {
            "$set": {
                "vector": vector,
                "dim": app.config["EMBEDDING_DIM"],
                "model": "fake-embedding-model",
                "behavior_count": 1,
            }
        },
        upsert=True,
    )
    return vector


def _seed_chroma(
    fake_chroma, product, profile_vector, weight: float, *, school_id: int, status: str = "on_sale"
):
    dim = len(profile_vector)
    axis = 0 if abs(profile_vector[0]) < 0.95 else 1
    noise = [0.0] * dim
    noise[axis] = 1.0
    mixed = [
        weight * pv + (1 - weight) * nz
        for pv, nz in zip(profile_vector, noise, strict=False)
    ]
    norm = sum(c * c for c in mixed) ** 0.5 or 1.0
    fake_chroma.upsert(
        ids=[str(product.id)],
        embeddings=[[c / norm for c in mixed]],
        metadatas=[{"school_id": school_id, "status": status}],
    )


class TestColdStart:
    def test_random_40_no_degraded(
        self, app, client, world, fake_mongo, fake_chroma, fake_embedding, fake_redis,
        make_auth_header,
    ):
        res = client.get(HOME_URL, headers=make_auth_header(world.viewer["id"]))
        assert res.status_code == 200
        data = res.get_json()["data"]
        assert len(data["items"]) == 40  # 在售 48 件 → 随机 40
        assert "degraded" not in data  # 冷启动是正常路径
        assert all(item["status"] == "on_sale" for item in data["items"])
        # 全部本校（他校 5 件绝迹，AC-03）
        assert all(item["campus"]["school_id"] == world.school_id for item in data["items"])
        # 缓存已回写
        key = f"product:home:{world.school_id}:{world.viewer['id']}"
        assert key in fake_redis.store


class TestProfileFeed:
    def test_ratio_32_plus_8_exclusions(
        self, app, client, world, fake_mongo, fake_chroma, fake_embedding, make_auth_header
    ):
        profile_vector = _seed_profile(fake_mongo, app, world.viewer["id"])
        eligible = world.pool[:32]
        for product in eligible:
            _seed_chroma(fake_chroma, product, profile_vector, 0.9, school_id=world.school_id)
        # 应被过滤的三类：自己发布 / 非 on_sale / 他校（相似度更高也不入选）
        _seed_chroma(fake_chroma, world.own[0], profile_vector, 0.99, school_id=world.school_id)
        _seed_chroma(
            fake_chroma, world.off_sale[0], profile_vector, 0.99,
            school_id=world.school_id, status="off_sale",
        )
        _seed_chroma(
            fake_chroma, world.other_school[0], profile_vector, 0.99,
            school_id=world.other_school[0].school_id,
        )

        res = client.get(HOME_URL, headers=make_auth_header(world.viewer["id"]))

        assert res.status_code == 200
        data = res.get_json()["data"]
        assert "degraded" not in data
        ids = [item["id"] for item in data["items"]]
        assert len(ids) == 40  # 32 画像 + 8 随机补足
        profile_ids = set(ids[:32])
        random_ids = set(ids[32:])
        assert profile_ids == {p.id for p in eligible}  # 前 32 全为画像召回
        assert world.own[0].id not in profile_ids  # 自己发布被排除
        assert world.off_sale[0].id not in profile_ids  # 非 on_sale 被排除
        assert world.other_school[0].id not in profile_ids  # 他校被排除
        assert random_ids.isdisjoint(profile_ids)  # 批内按 id 去重
        assert len(random_ids) == 8

    def test_recall_shortfall_random_fill(
        self, app, client, world, fake_mongo, fake_chroma, fake_embedding, make_auth_header
    ):
        """召回 10 → 随机补 30（AC-07 缺口补足）。"""
        profile_vector = _seed_profile(fake_mongo, app, world.viewer["id"])
        recalled = world.pool[:10]
        for product in recalled:
            _seed_chroma(fake_chroma, product, profile_vector, 0.9, school_id=world.school_id)

        res = client.get(HOME_URL, headers=make_auth_header(world.viewer["id"]))

        data = res.get_json()["data"]
        ids = [item["id"] for item in data["items"]]
        assert len(ids) == 40
        assert set(ids[:10]) == {p.id for p in recalled}
        assert len(set(ids)) == 40  # 无重复

    def test_cache_hit_skips_recompute(
        self, app, client, world, fake_mongo, fake_chroma, fake_embedding, fake_redis,
        make_auth_header,
    ):
        _seed_profile(fake_mongo, app, world.viewer["id"])
        first = client.get(HOME_URL, headers=make_auth_header(world.viewer["id"]))
        key = f"product:home:{world.school_id}:{world.viewer['id']}"
        assert key in fake_redis.store

        # 二次调用命中缓存：Chroma 故障也不影响（不触发计算路径）
        fake_chroma.fail["fail"] = True
        second = client.get(HOME_URL, headers=make_auth_header(world.viewer["id"]))
        assert second.get_json()["data"]["items"] == first.get_json()["data"]["items"]
        assert "degraded" not in second.get_json()["data"]

    def test_refresh_bypasses_cache(
        self, app, client, world, product_factory, fake_mongo, fake_chroma, fake_embedding,
        make_auth_header,
    ):
        profile_vector = _seed_profile(fake_mongo, app, world.viewer["id"])
        for product in world.pool[:5]:
            _seed_chroma(fake_chroma, product, profile_vector, 0.9, school_id=world.school_id)
        first_ids = [
            i["id"] for i in client.get(
                HOME_URL, headers=make_auth_header(world.viewer["id"])
            ).get_json()["data"]["items"]
        ]

        # 新增一件最相似商品；refresh=true 强制重算
        new_product = product_factory(world.seller, world.category.id, title="新上架商品")
        _seed_chroma(fake_chroma, new_product, profile_vector, 0.999, school_id=world.school_id)
        refreshed = client.get(
            HOME_URL,
            headers=make_auth_header(world.viewer["id"]),
            query_string={"refresh": "true"},
        )
        refreshed_ids = [i["id"] for i in refreshed.get_json()["data"]["items"]]
        assert new_product.id in refreshed_ids
        assert new_product.id not in first_ids

    def test_recalled_order_reflects_profile_vector(
        self, app, client, world, fake_mongo, fake_chroma, fake_embedding, make_auth_header
    ):
        """「纯随机冒充推荐」反目标不成立：召回序由画像向量决定（近者优先）。"""
        profile_vector = _seed_profile(fake_mongo, app, world.viewer["id"])
        near, far = world.pool[0], world.pool[1]
        _seed_chroma(fake_chroma, far, profile_vector, 0.5, school_id=world.school_id)
        _seed_chroma(fake_chroma, near, profile_vector, 0.95, school_id=world.school_id)
        # 其余商品不进 Chroma：召回池仅 near/far
        ids = [
            i["id"] for i in client.get(
                HOME_URL,
                headers=make_auth_header(world.viewer["id"]),
                query_string={"refresh": "true"},
            ).get_json()["data"]["items"]
        ]
        assert ids.index(near.id) < ids.index(far.id)  # 相似度序


class TestDegraded:
    def test_mongo_down_random_with_degraded(
        self, app, client, world, fake_mongo, fake_chroma, fake_embedding, fake_redis,
        make_auth_header,
    ):
        fake_mongo.fail = True
        res = client.get(HOME_URL, headers=make_auth_header(world.viewer["id"]))
        data = res.get_json()["data"]
        assert data["degraded"] is True
        assert data["degraded_reason"]
        assert len(data["items"]) == 40  # 全随机

    def test_embedding_down_random_with_degraded(
        self, app, client, world, fake_mongo, fake_chroma, fake_embedding, make_auth_header
    ):
        _seed_profile(fake_mongo, app, world.viewer["id"])
        fake_embedding.fail = True
        res = client.get(HOME_URL, headers=make_auth_header(world.viewer["id"]))
        data = res.get_json()["data"]
        assert data["degraded"] is True
        assert len(data["items"]) == 40

    def test_redis_down_direct_compute_not_degraded(
        self, app, client, world, fake_mongo, fake_chroma, fake_embedding, fake_redis,
        make_auth_header,
    ):
        fake_redis.fail = True  # 缓存读写均故障
        res = client.get(HOME_URL, headers=make_auth_header(world.viewer["id"]))
        data = res.get_json()["data"]
        assert len(data["items"]) == 40
        assert "degraded" not in data  # Redis 不可用不算 degraded


class TestAdmin:
    def test_admin_empty_list(
        self, app, client, world, fake_mongo, fake_chroma, fake_embedding, fake_redis,
        make_auth_header,
    ):
        res = client.get(HOME_URL, headers=make_auth_header(world.admin["id"]))
        assert res.status_code == 200
        assert res.get_json()["data"]["items"] == []
        assert not any(key.startswith("product:home") for key in fake_redis.store)
