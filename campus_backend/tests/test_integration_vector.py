"""端到端链路测试（三桩 + 真实事件接线）：发布/编辑/改价/下架/删除/点击。

经 HTTP 接口触发 b2be 事件 → b2be2 订阅者 → Mongo/Chroma/画像桩断言。
"""

import pytest

from src.services import vector_service

PRODUCTS_URL = "/api/products"


@pytest.fixture()
def seller_and_headers(
    db_create_all, school_fixtures, user_factory, make_auth_header
):
    seller = user_factory(
        username="seller01",
        school_id=school_fixtures.multi.id,
        campus_id=school_fixtures.east.id,
        auth_status="approved",
    )
    return seller, make_auth_header(seller["id"])


@pytest.fixture()
def viewer_headers(db_create_all, school_fixtures, user_factory, make_auth_header):
    viewer = user_factory(
        username="viewer01",
        school_id=school_fixtures.multi.id,
        campus_id=school_fixtures.west.id,
        auth_status="approved",
    )
    return viewer, make_auth_header(viewer["id"])


def _publish(client, headers, category_id, image_ids, **overrides):
    payload = {
        "title": "罗技 K845 机械键盘",
        "description": "九成新，樱桃红轴，无拆修",
        "price": 199.0,
        "category_id": category_id,
        "condition": "excellent",
        "image_ids": image_ids,
    }
    payload.update(overrides)
    return client.post(PRODUCTS_URL, headers=headers, json=payload)


@pytest.fixture()
def wired(wired_events):
    """显式声明端到端用例需要事件接线（可读性）。"""
    return True


class TestPublishToVector:
    def test_publish_writes_mongo_and_chroma(
        self, app, client, seller_and_headers, category_fixtures, owned_product_images,
        fake_mongo, fake_chroma, fake_embedding, wired,
    ):
        seller, headers = seller_and_headers
        image_ids = owned_product_images(seller["id"], 1)
        res = _publish(client, headers, category_fixtures.items[0].id, image_ids)
        assert res.status_code == 200
        product_id = res.get_json()["data"]["id"]

        doc = fake_mongo["product_vectors"].find_one({"product_id": product_id})
        assert doc is not None and doc["status"] == "on_sale"
        assert str(product_id) in fake_chroma.vectors
        assert fake_chroma.metadatas[str(product_id)]["seller_id"] == seller["id"]

    def test_edit_title_rebuilds_vector(
        self, app, client, seller_and_headers, category_fixtures, owned_product_images,
        product_factory, fake_mongo, fake_chroma, fake_embedding, wired,
    ):
        seller, headers = seller_and_headers
        product = product_factory(seller, category_fixtures.items[0].id, title="旧标题")
        vector_service.sync_product(product)
        old_hash = fake_mongo["product_vectors"].find_one({"product_id": product.id})["text_hash"]

        image_ids = owned_product_images(seller["id"], 1)
        res = client.put(
            f"{PRODUCTS_URL}/{product.id}",
            headers=headers,
            json={
                "title": "彻底换新的机械键盘",
                "description": "九成新，樱桃红轴，无拆修",
                "price": 199.0,
                "category_id": category_fixtures.items[0].id,
                "condition": "excellent",
                "image_ids": image_ids,
            },
        )
        assert res.status_code == 200
        doc = fake_mongo["product_vectors"].find_one({"product_id": product.id})
        assert doc["text_hash"] != old_hash  # 重建
        assert fake_chroma.documents[str(product.id)].startswith("标题：彻底换新")

    def test_price_only_edit_updates_metadata_without_recompute(
        self, app, client, seller_and_headers, category_fixtures, owned_product_images,
        product_factory, fake_mongo, fake_chroma, fake_embedding, wired,
    ):
        seller, headers = seller_and_headers
        product = product_factory(seller, category_fixtures.items[0].id, price="100.00")
        vector_service.sync_product(product)
        old_vector = list(fake_chroma.vectors[str(product.id)])
        calls_before = len(fake_embedding.calls)

        image_ids = owned_product_images(seller["id"], 1)
        res = client.put(
            f"{PRODUCTS_URL}/{product.id}",
            headers=headers,
            json={
                "title": "测试商品",  # 不变
                "description": "测试描述",  # 不变
                "price": 250.0,  # 仅价格变
                "category_id": category_fixtures.items[0].id,
                "condition": "excellent",  # 不变
                "image_ids": image_ids,
            },
        )
        assert res.status_code == 200
        assert len(fake_embedding.calls) == calls_before  # 不重算向量
        assert fake_chroma.metadatas[str(product.id)]["price"] == 250.0
        assert fake_chroma.vectors[str(product.id)] == old_vector

    def test_off_sale_updates_metadata(
        self, app, client, seller_and_headers, category_fixtures, product_factory,
        fake_mongo, fake_chroma, fake_embedding, wired,
    ):
        seller, headers = seller_and_headers
        product = product_factory(seller, category_fixtures.items[0].id)
        vector_service.sync_product(product)
        res = client.patch(
            f"{PRODUCTS_URL}/{product.id}/status",
            headers=headers,
            json={"status": "off_sale"},
        )
        assert res.status_code == 200
        assert fake_chroma.metadatas[str(product.id)]["status"] == "off_sale"
        doc = fake_mongo["product_vectors"].find_one({"product_id": product.id})
        assert doc["status"] == "off_sale"

    def test_delete_removes_from_both_stores(
        self, app, client, seller_and_headers, category_fixtures, product_factory,
        fake_mongo, fake_chroma, fake_embedding, wired,
    ):
        seller, headers = seller_and_headers
        product = product_factory(seller, category_fixtures.items[0].id)
        vector_service.sync_product(product)
        res = client.delete(f"{PRODUCTS_URL}/{product.id}", headers=headers)
        assert res.status_code == 200
        assert fake_mongo["product_vectors"].find_one({"product_id": product.id}) is None
        assert str(product.id) not in fake_chroma.vectors

    def test_view_updates_profile_l2_normalized(
        self, app, client, seller_and_headers, viewer_headers, category_fixtures,
        product_factory, fake_mongo, fake_chroma, fake_embedding, wired,
    ):
        """AC-08 链路：点击 → 画像变化且模长为 1。"""
        import math

        seller, _ = seller_and_headers
        viewer, viewer_auth = viewer_headers
        product_a = product_factory(seller, category_fixtures.items[0].id, title="键盘甲")
        product_b = product_factory(seller, category_fixtures.items[0].id, title="耳机乙")
        vector_service.sync_product(product_a)
        vector_service.sync_product(product_b)

        assert client.get(
            f"{PRODUCTS_URL}/{product_a.id}", headers=viewer_auth
        ).status_code == 200
        profile = fake_mongo["user_profiles"].find_one({"user_id": viewer["id"]})
        assert profile is not None
        assert profile["vector"] == pytest.approx(
            fake_mongo["product_vectors"].find_one({"product_id": product_a.id})["vector"],
            abs=1e-9,
        )  # 首行为 new=product_vec

        assert client.get(
            f"{PRODUCTS_URL}/{product_b.id}", headers=viewer_auth
        ).status_code == 200
        changed = fake_mongo["user_profiles"].find_one({"user_id": viewer["id"]})
        assert changed["vector"] != profile["vector"]  # 画像变化
        assert changed["behavior_count"] == 2
        norm = math.sqrt(sum(c * c for c in changed["vector"]))
        assert norm == pytest.approx(1.0, abs=1e-9)  # L2 模长恒 1
