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
    def test_empty_collection_first_view_writes_log_and_profile(
        self, app, product, viewer, fake_mongo, fake_chroma, fake_embedding
    ):
        """B1 回归：空流水集合时首次行为必须落 1 条流水 + 画像。

        旧实现 ``if recent:`` + ``max(<空游标>)`` 抛 ValueError 被熔断吞掉，
        首次行为什么都不写——空游标恒为真（Cursor 无 __bool__/__len__）。
        """
        assert list(_behaviors(fake_mongo).find()) == []
        behavior_service.record_view(viewer["id"], product)
        logs = list(_behaviors(fake_mongo).find())
        assert len(logs) == 1
        assert _profiles(fake_mongo).find_one({"user_id": viewer["id"]}) is not None

    def test_dedup_query_is_bounded(
        self, app, product, viewer, fake_mongo, fake_chroma, fake_embedding
    ):
        """B1：去重查询有界（走 find_one + sort，或带 limit），不得全量拉回。"""
        behavior_service.record_view(viewer["id"], product)
        behavior_service.record_view(viewer["id"], product)
        behaviors = _behaviors(fake_mongo)
        assert behaviors.find_calls == []  # 未使用无界 find
        dedup_calls = [
            call for call in behaviors.find_one_calls if "action" in (call["filter"] or {})
        ]
        assert dedup_calls, "去重查询应发生"
        assert all(call["sort"] == [("created_at", -1)] for call in dedup_calls)

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
        logs = list(_behaviors(fake_mongo).find())
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
        logs = list(_behaviors(fake_mongo).find())
        assert len(logs) == 2  # 流水无条件记录
        second = _profiles(fake_mongo).find_one({"user_id": viewer["id"]})
        assert second["vector"] == first["vector"]  # 画像未变
        assert second["behavior_count"] == 1  # 不递增

    def test_dedup_window_expires_after_24h(
        self, app, product, viewer, fake_mongo, fake_chroma, fake_embedding
    ):
        behavior_service.record_view(viewer["id"], product)
        # 把首条流水 created_at 拨回 25h 前（模拟窗口过期）
        stale = list(_behaviors(fake_mongo).find())[0]
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
        log = list(_behaviors(fake_mongo).find())[0]
        assert log["action"] == "favorite" and log["weight"] == 0.70

    def test_unfavorite_logs_without_profile_update(
        self, app, product, viewer, fake_mongo, fake_chroma, fake_embedding
    ):
        behavior_service.record_favorite(viewer["id"], product, favorited=False)
        assert len(list(_behaviors(fake_mongo).find())) == 1  # 流水照记
        assert _profiles(fake_mongo).find_one({"user_id": viewer["id"]}) is None

    def test_view_then_favorite_are_separate_actions(
        self, app, product, viewer, fake_mongo, fake_chroma, fake_embedding
    ):
        """同商品不同 action 各自首计（去重按 (user, product, action) 三元组）。"""
        behavior_service.record_view(viewer["id"], product)
        behavior_service.record_favorite(viewer["id"], product, favorited=True)
        profile = _profiles(fake_mongo).find_one({"user_id": viewer["id"]})
        assert profile["behavior_count"] == 2
        assert len(list(_behaviors(fake_mongo).find())) == 2


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
        assert len(list(_behaviors(fake_mongo).find())) == 1  # 流水仍在
        assert _profiles(fake_mongo).find_one({"user_id": viewer["id"]}) is None

    def test_embedding_unavailable_skips_backfill_but_logs(
        self, app, product, viewer, fake_mongo, fake_chroma, fake_embedding
    ):
        """S-4：探测不可用即跳过补算（不发起 embed），流水照记、画像跳过。"""
        fake_embedding.fail = True
        behavior_service.record_view(viewer["id"], product)
        assert fake_embedding.calls == []  # 探测失败：补算未发起
        assert len(list(_behaviors(fake_mongo).find())) == 1  # 流水照记
        assert _profiles(fake_mongo).find_one({"user_id": viewer["id"]}) is None


class TestStaleProfile:
    """B-2：旧维度/旧模型画像不得混入新向量（否则 Chroma 维度错误永久降级）。"""

    def test_legacy_dim_profile_discarded(
        self, app, product, viewer, fake_mongo, fake_chroma, fake_embedding, caplog
    ):
        from src.services import vector_service

        vector_service.sync_product(product)
        product_vector = fake_mongo["product_vectors"].find_one(
            {"product_id": product.id}
        )["vector"]
        dim = app.config["EMBEDDING_DIM"]
        legacy = [0.05] * (dim - 256)  # 768 维旧画像（切换模型前的存量）
        _profiles(fake_mongo).update_one(
            {"user_id": viewer["id"]},
            {
                "$set": {
                    "vector": legacy,
                    "dim": dim,  # 存量 dim 字段本身是错的（谎报）
                    "model": "fake-embedding-model",
                    "behavior_count": 9,
                }
            },
            upsert=True,
        )

        with caplog.at_level("ERROR"):
            behavior_service.record_view(viewer["id"], product)

        profile = _profiles(fake_mongo).find_one({"user_id": viewer["id"]})
        assert len(profile["vector"]) == dim  # 不再落库 768 维
        assert profile["dim"] == len(profile["vector"])  # dim 与真实长度一致
        assert profile["behavior_count"] == 1  # 旧画像丢弃后从 1 起算
        assert profile["vector"] == pytest.approx(product_vector, abs=1e-9)
        assert any("丢弃" in r.message for r in caplog.records)

    def test_profile_model_mismatch_resets(
        self, app, product, viewer, fake_mongo, fake_chroma, fake_embedding, caplog
    ):
        """S-3 画像侧：model 不一致（同维）同样视为陈旧，整条丢弃重算。"""
        from src.services import vector_service

        vector_service.sync_product(product)
        product_vector = fake_mongo["product_vectors"].find_one(
            {"product_id": product.id}
        )["vector"]
        dim = app.config["EMBEDDING_DIM"]
        _profiles(fake_mongo).update_one(
            {"user_id": viewer["id"]},
            {
                "$set": {
                    "vector": [1.0] + [0.0] * (dim - 1),
                    "dim": dim,
                    "model": "old-model",
                    "behavior_count": 6,
                }
            },
            upsert=True,
        )

        with caplog.at_level("ERROR"):
            behavior_service.record_view(viewer["id"], product)

        profile = _profiles(fake_mongo).find_one({"user_id": viewer["id"]})
        assert profile["model"] == "fake-embedding-model"
        assert profile["behavior_count"] == 1
        assert profile["vector"] == pytest.approx(product_vector, abs=1e-9)
        assert any("丢弃" in r.message for r in caplog.records)

    def test_stale_product_vector_in_mongo_recomputed(
        self, app, product, viewer, fake_mongo, fake_chroma, fake_embedding, caplog
    ):
        """B-2 顺带：Mongo 存量商品向量维度不符时不得直接参与混合。"""
        dim = app.config["EMBEDDING_DIM"]
        fake_mongo["product_vectors"].update_one(
            {"product_id": product.id},
            {"$set": {"vector": [0.1] * (dim - 256), "dim": dim, "model": "fake-embedding-model"}},
            upsert=True,
        )

        with caplog.at_level("ERROR"):
            behavior_service.record_view(viewer["id"], product)

        profile = _profiles(fake_mongo).find_one({"user_id": viewer["id"]})
        assert len(profile["vector"]) == dim  # 走现场补算后的正确维度
        assert profile["dim"] == dim
        assert len(fake_embedding.calls) == 1  # 触发补算
        assert any("维度不符" in r.message for r in caplog.records)


class TestFavoriteDedupDirection:
    """B-W-2：取消收藏不得消费 24h 去重窗口（方向不同不算重复行为）。"""

    def test_favorite_unfavorite_favorite_updates_profile(
        self, app, product, viewer, fake_mongo, fake_chroma, fake_embedding
    ):
        from src.services import vector_service

        vector_service.sync_product(product)
        behavior_service.record_favorite(viewer["id"], product, favorited=True)
        behavior_service.record_favorite(viewer["id"], product, favorited=False)
        behavior_service.record_favorite(viewer["id"], product, favorited=True)

        profile = _profiles(fake_mongo).find_one({"user_id": viewer["id"]})
        assert profile["behavior_count"] == 2  # 第三次（再次收藏）仍更新画像
        logs = list(_behaviors(fake_mongo).find())
        assert len(logs) == 3  # 流水三条齐全
        assert [row["action"] for row in logs] == ["favorite"] * 3
        assert [row.get("favorited") for row in logs] == [True, False, True]

    def test_repeated_favorite_within_window_still_deduped(
        self, app, product, viewer, fake_mongo, fake_chroma, fake_embedding
    ):
        from src.services import vector_service

        vector_service.sync_product(product)
        behavior_service.record_favorite(viewer["id"], product, favorited=True)
        behavior_service.record_favorite(viewer["id"], product, favorited=True)
        profile = _profiles(fake_mongo).find_one({"user_id": viewer["id"]})
        assert profile["behavior_count"] == 1  # 同方向重复仍去重（需求原文）
        assert len(list(_behaviors(fake_mongo).find())) == 2


class TestMongoCircuitBreaker:
    """S-4：连续失败 3 次才熔断，冷却期满半开探测（成功关闭 / 失败续期）。"""

    @staticmethod
    def _counting_get_db(monkeypatch, mongo_client) -> list[int]:
        calls: list[int] = []
        original = mongo_client.get_db

        def _get_db():
            calls.append(1)
            return original()

        monkeypatch.setattr(mongo_client, "get_db", _get_db)
        return calls

    def test_two_failures_do_not_open_breaker(
        self, app, product, viewer, fake_mongo, fake_embedding, fake_chroma, monkeypatch
    ):
        from src.common import mongo_client

        calls = self._counting_get_db(monkeypatch, mongo_client)
        fake_mongo.fail = True

        behavior_service.record_view(viewer["id"], product)
        behavior_service.record_view(viewer["id"], product)

        assert len(calls) == 2  # 两次都真实尝试（瞬时抖动不熔断）
        assert behavior_service._failures == 2
        assert behavior_service._circuit_open() is False

    def test_third_failure_opens_breaker_then_short_circuits(
        self, app, product, viewer, fake_mongo, fake_embedding, fake_chroma, monkeypatch
    ):
        from src.common import mongo_client

        calls = self._counting_get_db(monkeypatch, mongo_client)
        fake_mongo.fail = True

        for _ in range(3):
            behavior_service.record_view(viewer["id"], product)

        assert len(calls) == 3
        assert behavior_service._circuit_open() is True

        behavior_service.record_view(viewer["id"], product)  # 冷却窗口：短路
        assert len(calls) == 3  # 未再触达 Mongo
        assert list(_behaviors(fake_mongo).find()) == []

    def test_half_open_success_closes_breaker(
        self, app, product, viewer, fake_mongo, fake_embedding, fake_chroma
    ):
        fake_mongo.fail = True
        for _ in range(3):
            behavior_service.record_view(viewer["id"], product)
        assert behavior_service._circuit_open() is True

        fake_mongo.fail = False
        behavior_service._open_until = 0.0  # 冷却期满：半开放行一次
        behavior_service.record_view(viewer["id"], product)

        assert behavior_service._circuit_open() is False  # 探测成功即关闭
        assert behavior_service._failures == 0
        behavior_service.record_view(viewer["id"], product)  # 恢复正常写入
        assert list(_behaviors(fake_mongo).find())

    def test_half_open_failure_renews_cooldown(
        self, app, product, viewer, fake_mongo, fake_embedding, fake_chroma
    ):
        import time as _time

        fake_mongo.fail = True
        for _ in range(3):
            behavior_service.record_view(viewer["id"], product)
        behavior_service._open_until = 0.0  # 半开窗口

        before = _time.monotonic()
        behavior_service.record_view(viewer["id"], product)  # 探测失败

        assert behavior_service._open_until > before  # 续期
        assert behavior_service._circuit_open() is True

    def test_success_keeps_breaker_closed(
        self, app, product, viewer, fake_mongo, fake_embedding, fake_chroma
    ):
        behavior_service.record_view(viewer["id"], product)
        behavior_service.record_view(viewer["id"], product)
        assert len(list(_behaviors(fake_mongo).find())) == 2  # 正常期无短路
        assert behavior_service._circuit_open() is False
