"""vector_service 单元测试：模板文本、判变跳过、双写、重试队列、metadata 局部更新。

全部依赖经 conftest 三桩注入（fake_mongo/fake_chroma/fake_embedding +
autouse fake_redis），不触真实存储。
"""

import json
import time

import pytest

from src.services import vector_service


@pytest.fixture()
def product(db_create_all, school_fixtures, user_factory, category_fixtures, product_factory):
    """一件本校在售商品（含分类名可断言模板）。"""
    seller = user_factory(
        username="seller01",
        school_id=school_fixtures.multi.id,
        campus_id=school_fixtures.east.id,
        auth_status="approved",
    )
    category = category_fixtures.by_name["数码电子"]
    return product_factory(
        seller, category.id, title="罗技 K845 机械键盘", price="199.00",
        description="九成新，樱桃红轴",
    )


def _mongo(fake_mongo):
    return fake_mongo["product_vectors"]


class TestBuildText:
    def test_template_four_lines(self, product, category_fixtures):
        text = vector_service.build_text(product, "数码电子")
        assert text == (
            "标题：罗技 K845 机械键盘\n"
            "分类：数码电子\n"
            "成色：excellent\n"
            "描述：九成新，樱桃红轴"
        )

    def test_text_hash_deterministic(self):
        assert vector_service.text_hash("abc") == vector_service.text_hash("abc")
        assert vector_service.text_hash("abc") != vector_service.text_hash("abd")


class TestSyncProduct:
    def test_sync_writes_mongo_then_chroma(
        self, app, product, fake_mongo, fake_chroma, fake_embedding
    ):
        vector_service.sync_product(product)
        doc = _mongo(fake_mongo).find_one({"product_id": product.id})
        assert doc is not None
        assert doc["dim"] == app.config["EMBEDDING_DIM"]
        assert doc["model"] == "fake-embedding-model"
        assert doc["school_id"] == product.school_id
        assert doc["status"] == "on_sale"
        assert len(doc["text_hash"]) == 64
        # Chroma 双写：id 字符串化 + document=模板文本 + metadata 六字段
        chroma_id = str(product.id)
        assert chroma_id in fake_chroma.vectors
        assert fake_chroma.documents[chroma_id].startswith("标题：罗技 K845")
        meta = fake_chroma.metadatas[chroma_id]
        assert meta["school_id"] == product.school_id
        assert meta["status"] == "on_sale"
        assert meta["category_id"] == product.category_id
        assert meta["seller_id"] == product.seller_id
        assert meta["price"] == 199.0

    def test_unchanged_hash_and_metadata_skips_embedding(
        self, app, product, fake_mongo, fake_chroma, fake_embedding
    ):
        vector_service.sync_product(product)
        calls_after_first = list(fake_embedding.calls)
        # 同一商品重复同步：文本与 metadata 未变 → 不调 embedding、不重写
        vector_service.sync_product(product)
        assert fake_embedding.calls == calls_after_first

    def test_text_change_recomputes_and_rewrites(
        self, app, product, fake_mongo, fake_chroma, fake_embedding
    ):
        vector_service.sync_product(product)
        old_hash = _mongo(fake_mongo).find_one({"product_id": product.id})["text_hash"]
        product.title = "改标题后的机械键盘"
        vector_service.sync_product(product)
        doc = _mongo(fake_mongo).find_one({"product_id": product.id})
        assert doc["text_hash"] != old_hash
        assert len(fake_embedding.calls) == 2  # 重算发生
        assert fake_chroma.documents[str(product.id)].startswith("标题：改标题后")

    def test_price_change_rewrites_metadata(
        self, app, product, fake_mongo, fake_chroma, fake_embedding
    ):
        """价格变不改 text_hash，但 metadata 变 → 仍重写（不调 embedding 不可行，
        因向量文本未变——此处校验 metadata 比对触发重写且 Chroma metadata 更新）。"""
        from decimal import Decimal

        product.price = Decimal("299.00")
        vector_service.sync_product(product)
        meta = fake_chroma.metadatas[str(product.id)]
        assert meta["price"] == 299.0

    def test_chroma_failure_enqueues_retry_and_does_not_raise(
        self, app, product, fake_mongo, fake_chroma, fake_embedding, fake_redis, caplog
    ):
        fake_chroma.fail["fail"] = True
        with caplog.at_level("ERROR"):
            vector_service.sync_product(product)  # 不上抛
        assert fake_redis.llen(vector_service.VECTOR_RETRY_QUEUE_KEY) == 1
        message = json.loads(fake_redis.lists[vector_service.VECTOR_RETRY_QUEUE_KEY][0])
        assert message["product_id"] == product.id
        assert abs(message["ts"] - time.time()) < 60
        # Mongo 先行已写（先 Mongo 后 Chroma 语义）
        assert _mongo(fake_mongo).find_one({"product_id": product.id}) is not None
        assert any("向量同步失败" in r.message for r in caplog.records)

    def test_dimension_mismatch_rejected_without_retry(
        self, app, product, fake_mongo, fake_chroma, fake_embedding, fake_redis, monkeypatch
    ):
        from src.common import embedding_client

        dim = app.config["EMBEDDING_DIM"]
        monkeypatch.setattr(
            embedding_client, "embed_texts", lambda texts: [[0.5] * (dim + 1)] * len(texts)
        )
        vector_service.sync_product(product)  # 拒写，不上抛
        assert _mongo(fake_mongo).docs == []
        assert fake_chroma.vectors == {}
        assert fake_redis.llen(vector_service.VECTOR_RETRY_QUEUE_KEY) == 0  # 不进重试


class TestUpdateStatusMetadata:
    def test_updates_metadata_without_recompute(
        self, app, product, fake_mongo, fake_chroma, fake_embedding
    ):
        vector_service.sync_product(product)
        calls = list(fake_embedding.calls)
        product.status = "off_sale"
        vector_service.update_status_metadata(product)
        assert fake_embedding.calls == calls  # 不重算向量
        assert fake_chroma.metadatas[str(product.id)]["status"] == "off_sale"
        doc = _mongo(fake_mongo).find_one({"product_id": product.id})
        assert doc["status"] == "off_sale"
        assert doc["vector"] == fake_chroma.vectors[str(product.id)]  # 向量未变

    def test_missing_doc_falls_back_to_full_sync(
        self, app, product, fake_mongo, fake_chroma, fake_embedding
    ):
        product.status = "off_sale"
        vector_service.update_status_metadata(product)  # Mongo 无存量 → 全量同步
        doc = _mongo(fake_mongo).find_one({"product_id": product.id})
        assert doc is not None and doc["status"] == "off_sale"
        assert fake_chroma.metadatas[str(product.id)]["status"] == "off_sale"

    def test_failure_enqueues_retry(
        self, app, product, fake_mongo, fake_chroma, fake_embedding, fake_redis
    ):
        vector_service.sync_product(product)
        fake_chroma.fail["fail"] = True
        product.status = "off_sale"
        vector_service.update_status_metadata(product)
        assert fake_redis.llen(vector_service.VECTOR_RETRY_QUEUE_KEY) == 1


class TestRemoveProduct:
    def test_removes_from_both_stores(self, app, product, fake_mongo, fake_chroma, fake_embedding):
        vector_service.sync_product(product)
        assert _mongo(fake_mongo).docs and str(product.id) in fake_chroma.vectors
        vector_service.remove_product(product.id)
        assert _mongo(fake_mongo).docs == []
        assert str(product.id) not in fake_chroma.vectors

    def test_remove_idempotent(self, app, product, fake_mongo, fake_chroma, fake_embedding):
        vector_service.remove_product(product.id)  # 无存量也安全
        assert _mongo(fake_mongo).docs == []

    def test_failure_enqueues_retry(
        self, app, product, fake_mongo, fake_chroma, fake_embedding, fake_redis
    ):
        vector_service.sync_product(product)
        fake_chroma.fail["fail"] = True
        vector_service.remove_product(product.id)
        assert fake_redis.llen(vector_service.VECTOR_RETRY_QUEUE_KEY) == 1


class TestRebuildAll:
    def test_rebuild_recreates_everything(
        self, app, product, db_create_all, fake_mongo, fake_chroma, fake_embedding,
        school_fixtures, user_factory, category_fixtures, product_factory,
    ):
        other_seller = user_factory(
            username="seller02",
            school_id=school_fixtures.multi.id,
            auth_status="approved",
        )
        deleted = product_factory(
            other_seller, category_fixtures.items[1].id, status="deleted"
        )
        result = vector_service.rebuild_all()
        assert result["total"] == 1  # 仅 on_sale 商品（deleted 不重建）
        assert result["synced"] == 1
        assert result["failed"] == 0
        assert len(fake_chroma.vectors) == 1
        assert _mongo(fake_mongo).find_one({"product_id": deleted.id}) is None
