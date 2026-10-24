"""vector_retry_worker 测试：队列重放出队、超龄丢弃、单轮批量上限、删除补偿。"""

import json
import time

from src.services import vector_retry_worker, vector_service


def _enqueue(fake_redis, product_id: int, ts: float | None = None) -> None:
    message = json.dumps(
        {"product_id": product_id, "ts": int(ts if ts is not None else time.time())}
    )
    fake_redis.rpush(vector_service.VECTOR_RETRY_QUEUE_KEY, message)


class TestProcessOnce:
    def test_replay_success_drains_queue(
        self, app, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, fake_mongo, fake_chroma, fake_embedding, fake_redis,
    ):
        seller = user_factory(
            username="seller01",
            school_id=school_fixtures.multi.id,
            auth_status="approved",
        )
        product = product_factory(seller, category_fixtures.items[0].id)
        _enqueue(fake_redis, product.id)

        result = vector_retry_worker.process_once(app)

        assert result == {"replayed": 1, "dropped": 0, "failed": 0}
        assert fake_redis.llen(vector_service.VECTOR_RETRY_QUEUE_KEY) == 0
        # 重放后向量双写落库
        assert fake_mongo["product_vectors"].find_one({"product_id": product.id})
        assert str(product.id) in fake_chroma.vectors

    def test_replay_failure_over_24h_dropped(
        self, app, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, fake_mongo, fake_chroma, fake_embedding, fake_redis, caplog,
    ):
        seller = user_factory(
            username="seller02",
            school_id=school_fixtures.multi.id,
            auth_status="approved",
        )
        product = product_factory(seller, category_fixtures.items[0].id)
        _enqueue(fake_redis, product.id, ts=time.time() - 25 * 3600)
        fake_embedding.fail = True  # 重试必失败

        with caplog.at_level("ERROR"):
            result = vector_retry_worker.process_once(app)

        assert result == {"replayed": 0, "dropped": 1, "failed": 0}  # 超龄只计 dropped
        assert fake_redis.llen(vector_service.VECTOR_RETRY_QUEUE_KEY) == 0  # 已丢弃
        assert any("超 24h" in r.message for r in caplog.records)

    def test_replay_failure_within_24h_requeued_with_original_ts(
        self, app, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, fake_mongo, fake_chroma, fake_embedding, fake_redis,
    ):
        seller = user_factory(
            username="seller03",
            school_id=school_fixtures.multi.id,
            auth_status="approved",
        )
        product = product_factory(seller, category_fixtures.items[0].id)
        original_ts = time.time() - 3600  # 1h 前入队
        _enqueue(fake_redis, product.id, ts=original_ts)
        fake_embedding.fail = True

        result = vector_retry_worker.process_once(app)

        assert result == {"replayed": 0, "dropped": 0, "failed": 1}
        assert fake_redis.llen(vector_service.VECTOR_RETRY_QUEUE_KEY) == 1
        message = json.loads(fake_redis.lists[vector_service.VECTOR_RETRY_QUEUE_KEY][0])
        assert message["ts"] == int(original_ts)  # 龄期不因重放重置

    def test_deleted_product_compensated_by_remove(
        self, app, db_create_all, school_fixtures, user_factory, category_fixtures,
        product_factory, fake_mongo, fake_chroma, fake_embedding, fake_redis,
    ):
        seller = user_factory(
            username="seller04",
            school_id=school_fixtures.multi.id,
            auth_status="approved",
        )
        product = product_factory(seller, category_fixtures.items[0].id)
        vector_service.sync_product(product)
        product.status = "deleted"
        db_create_all.session.commit()
        _enqueue(fake_redis, product.id)

        result = vector_retry_worker.process_once(app)

        assert result["replayed"] == 1
        assert fake_mongo["product_vectors"].find_one({"product_id": product.id}) is None
        assert str(product.id) not in fake_chroma.vectors

    def test_batch_limit_single_round(
        self, app, db_create_all, fake_redis, fake_mongo, fake_chroma, fake_embedding
    ):
        for i in range(5):
            _enqueue(fake_redis, 9000 + i)  # 商品不存在 → 走 remove 补偿路径

        result = vector_retry_worker.process_once(app, limit=2)

        assert result["replayed"] == 2
        assert fake_redis.llen(vector_service.VECTOR_RETRY_QUEUE_KEY) == 3

    def test_empty_queue_noop(self, app, fake_redis, fake_mongo, fake_chroma, fake_embedding):
        result = vector_retry_worker.process_once(app)
        assert result == {"replayed": 0, "dropped": 0, "failed": 0}


class TestDeleteCompensation:
    """B-3：删除补偿失败不得重置龄期（否则永不过期、replayed 虚高）。"""

    def test_delete_failure_over_24h_dropped(
        self, app, db_create_all, fake_redis, fake_mongo, fake_chroma, fake_embedding,
        caplog,
    ):
        _enqueue(fake_redis, 987654, ts=time.time() - 25 * 3600)  # 商品不存在
        fake_chroma.fail["fail"] = True

        with caplog.at_level("ERROR"):
            result = vector_retry_worker.process_once(app)

        # 超龄丢弃只计 dropped：failed 保持 0，避免 failed>0 告警误报
        assert result == {"replayed": 0, "dropped": 1, "failed": 0}
        assert fake_redis.llen(vector_service.VECTOR_RETRY_QUEUE_KEY) == 0
        assert any("超 24h" in r.message for r in caplog.records)

    def test_delete_failure_within_24h_requeues_original_ts(
        self, app, db_create_all, fake_redis, fake_mongo, fake_chroma, fake_embedding
    ):
        original_ts = time.time() - 3600
        _enqueue(fake_redis, 987655, ts=original_ts)  # 商品不存在
        fake_chroma.fail["fail"] = True

        result = vector_retry_worker.process_once(app)

        # 未超龄回队：只计 failed（不计 dropped），二者不双计
        assert result == {"replayed": 0, "dropped": 0, "failed": 1}
        assert fake_redis.llen(vector_service.VECTOR_RETRY_QUEUE_KEY) == 1
        message = json.loads(fake_redis.lists[vector_service.VECTOR_RETRY_QUEUE_KEY][0])
        assert message["ts"] == int(original_ts)  # 原 ts 保留，龄期不重置

    def test_delete_success_counts_replayed(
        self, app, db_create_all, fake_mongo, fake_chroma, fake_embedding, fake_redis
    ):
        _enqueue(fake_redis, 987656, ts=time.time() - 25 * 3600)  # 超龄但删除成功

        result = vector_retry_worker.process_once(app)

        assert result == {"replayed": 1, "dropped": 0, "failed": 0}


class TestIndexBackfill:
    """S-5：索引初始化失败标记待补建，由补偿线程每轮补建。"""

    def test_pending_indexes_backfilled_next_round(
        self, app, db_create_all, fake_mongo, fake_chroma, fake_embedding, fake_redis
    ):
        from src.services import events, events_subscribers

        events_subscribers._reset_for_tests()
        try:
            fake_mongo.fail = True
            with app.app_context():
                events_subscribers.register_all()  # 订阅照常注册，索引失败仅标记

            assert events_subscribers.indexes_pending() is True
            assert set(events._HANDLERS) == {
                events.PRODUCT_PUBLISHED,
                events.PRODUCT_UPDATED,
                events.PRODUCT_DELETED,
                events.PRODUCT_STATUS_CHANGED,
                events.PRODUCT_VIEWED,
                events.FAVORITE_CHANGED,
            }
            assert fake_mongo["user_profiles"].indexes == []

            fake_mongo.fail = False
            vector_retry_worker.process_once(app)  # 一轮开头补建

            assert events_subscribers.indexes_pending() is False
            assert fake_mongo["user_profiles"].indexes
            assert fake_mongo["product_vectors"].indexes
            assert fake_mongo["user_behaviors"].indexes
        finally:
            events_subscribers._reset_for_tests()

    def test_no_pending_means_no_extra_index_calls(
        self, app, db_create_all, fake_mongo, fake_chroma, fake_embedding, fake_redis
    ):
        from src.services import events_subscribers

        events_subscribers._reset_for_tests()
        try:
            with app.app_context():
                events_subscribers.register_all()
            count = len(fake_mongo["user_profiles"].indexes)

            result = vector_retry_worker.process_once(app)

            assert len(fake_mongo["user_profiles"].indexes) == count
            # 空队列 + 无需补建：三项计数均为 0（不只是索引条数不变）
            assert result == {"replayed": 0, "dropped": 0, "failed": 0}
        finally:
            events_subscribers._reset_for_tests()
