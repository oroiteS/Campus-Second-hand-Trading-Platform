"""behavior_service 测试：流水无条件记录、24h 去重、权重公式数值、L2 模长 1。

全部依赖经 conftest 三桩注入；权重公式用已知向量数值断言（AC-08）。
"""

import math
from datetime import datetime, timedelta, timezone

import pytest

from src.services import behavior_service


@pytest.fixture()
def product(
    db_create_all, school_fixtures, user_factory, category_fixtures, product_factory
):
    seller = user_factory(
        username="seller01",
        school_id=school_fixtures.multi.id,
        campus_id=school_fixtures.east.id,
        auth_status="approved",
    )
    return product_factory(seller, category_fixtures.items[0].id, title="商品甲")


@pytest.fixture()
def viewer(user_factory, school_fixtures):
    return user_factory(
        username="viewer01",
        school_id=school_fixtures.multi.id,
        campus_id=school_fixtures.west.id,
        auth_status="approved",
    )


def _behaviors(fake_mongo):
    return fake_mongo["user_behaviors"]


def _profiles(fake_mongo):
    return fake_mongo["user_profiles"]


def _norm(vector: list[float]) -> float:
    return math.sqrt(sum(component**2 for component in vector))


class TestRecordView:
    def test_first_view_creates_profile_equal_to_product_vector(
        self, app, product, viewer, fake_mongo, fake_chroma, fake_embedding
    ):
        # 预置商品向量（发布链路产物）
        from src.services import vector_service

        vector_service.sync_product(product)
        product_vector = fake_mongo["product_vectors"].find_one(
            {"product_id": product.id}
        )["vector"]

        behavior_service.record_view(viewer["id"], product)

        profile = _profiles(fake_mongo).find_one({"user_id": viewer["id"]})
        assert profile is not None
        assert profile["vector"] == pytest.approx(product_vector, abs=1e-9)  # new=product_vec
        assert profile["dim"] == app.config["EMBEDDING_DIM"]
        assert profile["behavior_count"] == 1
        assert _norm(profile["vector"]) == pytest.approx(1.0, abs=1e-9)  # L2 模长=1

    def test_log_inserted_unconditionally(
        self, app, product, viewer, fake_mongo, fake_chroma, fake_embedding
    ):
        behavior_service.record_view(viewer["id"], product)
        logs = _behaviors(fake_mongo).find()
        assert len(logs) == 1
        log = logs[0]
        assert log["user_id"] == viewer["id"]
        assert log["product_id"] == product.id
        assert log["action"] == "view"
        assert log["weight"] == 0.82
        assert log["school_id"] == product.school_id
        assert log["source"] == "detail"

    def test_weight_formula_numeric_assertion(
        self, app, product, viewer, fake_mongo, fake_chroma, fake_embedding
    ):
        """构造已知向量：new = product×(1-0.82) + old×0.82（数值精确断言）。"""
        from src.services import vector_service

        vector_service.sync_product(product)
        product_vector = fake_mongo["product_vectors"].find_one(
            {"product_id": product.id}
        )["vector"]
        # 预置画像为「商品乙向量」：手工写入已知向量
        known_old = [1.0] + [0.0] * (app.config["EMBEDDING_DIM"] - 1)
        _profiles(fake_mongo).update_one(
            {"user_id": viewer["id"]},
            {
                "$set": {
                    "vector": list(known_old),
                    "dim": app.config["EMBEDDING_DIM"],
                    "model": "fake-embedding-model",
                    "behavior_count": 1,
                }
            },
            upsert=True,
        )

        behavior_service.record_view(viewer["id"], product)

        profile = _profiles(fake_mongo).find_one({"user_id": viewer["id"]})
        expected = [
            product_component * 0.18 + old_component * 0.82
            for product_component, old_component in zip(
                product_vector, known_old, strict=False
            )
        ]
        norm = math.sqrt(sum(c * c for c in expected))
        expected_normalized = [c / norm for c in expected]
        assert profile["vector"] == pytest.approx(expected_normalized, abs=1e-9)
        assert profile["behavior_count"] == 2

    def test_24h_dedup_skips_profile_but_still_logs(
        self, app, product, viewer, fake_mongo, fake_chroma, fake_embedding
    ):
        behavior_service.record_view(viewer["id"], product)
        first = _profiles(fake_mongo).find_one({"user_id": viewer["id"]})
        behavior_service.record_view(viewer["id"], product)  # 24h 内第二次
        logs = _behaviors(fake_mongo).find()
        assert len(logs) == 2  # 流水无条件记录
        second = _profiles(fake_mongo).find_one({"user_id": viewer["id"]})
        assert second["vector"] == first["vector"]  # 画像未变
        assert second["behavior_count"] == 1  # 不递增

    def test_dedup_window_expires_after_24h(
        self, app, product, viewer, fake_mongo, fake_chroma, fake_embedding
    ):
        behavior_service.record_view(viewer["id"], product)
        # 把首条流水 created_at 拨回 25h 前（模拟窗口过期）
        stale = _behaviors(fake_mongo).find()[0]
        stale["created_at"] = datetime.now(timezone(timedelta(hours=8))) - timedelta(
            hours=25
        )
        fake_mongo["user_behaviors"].docs = [stale]
        behavior_service.record_view(viewer["id"], product)
        profile = _profiles(fake_mongo).find_one({"user_id": viewer["id"]})
        assert profile["behavior_count"] == 2  # 窗口外：画像再次更新


class TestRecordFavorite:
    def test_favorite_weight_070_updates_profile(
        self, app, product, viewer, fake_mongo, fake_chroma, fake_embedding
    ):
        from src.services import vector_service

        vector_service.sync_product(product)
        behavior_service.record_favorite(viewer["id"], product, favorited=True)
        profile = _profiles(fake_mongo).find_one({"user_id": viewer["id"]})
        assert profile["behavior_count"] == 1
        product_vector = fake_mongo["product_vectors"].find_one(
            {"product_id": product.id}
        )["vector"]
        assert profile["vector"] == pytest.approx(product_vector, abs=1e-9)
        log = _behaviors(fake_mongo).find()[0]
        assert log["action"] == "favorite" and log["weight"] == 0.70

    def test_unfavorite_logs_without_profile_update(
        self, app, product, viewer, fake_mongo, fake_chroma, fake_embedding
    ):
        behavior_service.record_favorite(viewer["id"], product, favorited=False)
        assert len(_behaviors(fake_mongo).find()) == 1  # 流水照记
        assert _profiles(fake_mongo).find_one({"user_id": viewer["id"]}) is None

    def test_view_then_favorite_are_separate_actions(
        self, app, product, viewer, fake_mongo, fake_chroma, fake_embedding
    ):
        """同商品不同 action 各自首计（去重按 (user, product, action) 三元组）。"""
        behavior_service.record_view(viewer["id"], product)
        behavior_service.record_favorite(viewer["id"], product, favorited=True)
        profile = _profiles(fake_mongo).find_one({"user_id": viewer["id"]})
        assert profile["behavior_count"] == 2
        assert len(_behaviors(fake_mongo).find()) == 2


class TestMissingProductVector:
    def test_missing_vector_computed_on_the_fly(
        self, app, product, viewer, fake_mongo, fake_chroma, fake_embedding
    ):
        behavior_service.record_view(viewer["id"], product)  # Mongo 无商品向量
        assert _profiles(fake_mongo).find_one({"user_id": viewer["id"]}) is not None
        assert len(fake_embedding.calls) == 1  # 现场补算发生

    def test_missing_vector_and_embed_failure_skips_profile(
        self, app, product, viewer, fake_mongo, fake_chroma, fake_embedding, monkeypatch
    ):
        """探测可用但真实补算失败：画像跳过、流水仍在（异常路径双判定）。"""
        from src.common import embedding_client

        monkeypatch.setattr(embedding_client, "is_available", lambda: (True, "ok"))
        fake_embedding.fail = True
        behavior_service.record_view(viewer["id"], product)  # 补算失败：跳过
        assert len(_behaviors(fake_mongo).find()) == 1  # 流水仍在
        assert _profiles(fake_mongo).find_one({"user_id": viewer["id"]}) is None

    def test_embedding_unavailable_skips_backfill_but_logs(
        self, app, product, viewer, fake_mongo, fake_chroma, fake_embedding
    ):
        """S-4：探测不可用即跳过补算（不发起 embed），流水照记、画像跳过。"""
        fake_embedding.fail = True
        behavior_service.record_view(viewer["id"], product)
        assert fake_embedding.calls == []  # 探测失败：补算未发起
        assert len(_behaviors(fake_mongo).find()) == 1  # 流水照记
        assert _profiles(fake_mongo).find_one({"user_id": viewer["id"]}) is None
