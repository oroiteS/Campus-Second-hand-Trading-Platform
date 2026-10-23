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

        assert result["dropped"] == 1
        assert result["replayed"] == 0
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

        assert result["failed"] == 1
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
