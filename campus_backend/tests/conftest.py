"""pytest 公共 fixture：应用与测试客户端、内存 Redis 桩、建表与造数工厂。

b2be2 追加三桩（全手写、不引新包；b3/b4 可复用，接口形态如下）：

- ``fake_mongo``：内存 dict 集合桩 ``FakeMongoDatabase``，实现
  ``find_one(filter)`` / ``update_one(filter, {"$set"|"$inc"}, upsert)``
  / ``insert_one`` / ``delete_one`` / ``delete_many`` / ``find`` /
  ``create_index`` 子集，等值过滤语义；经 monkeypatch
  ``common.mongo_client.get_db`` 注入。置 ``db.fail = True`` 后 get_db
  抛 ``ConnectionError``（降级演练）。
- ``fake_chroma``：内存余弦 top-k 桩 ``FakeChromaCollection``，实现
  ``upsert(ids, embeddings, documents, metadatas)`` / ``query(
  query_embeddings, n_results, where)`` / ``update(ids, metadata)`` /
  ``get(ids)`` / ``delete(ids)`` 子集；``where`` 支持
  ``{"k": v}`` 与 ``{"$and": [...]}``；距离 = 1 − 余弦相似度（与真实
  Chroma cosine 同构）；经 monkeypatch ``common.chroma_client.
  get_collection`` / ``delete_collection`` 注入。置 ``stub.fail = True``
  后 get_collection 抛 ``ConnectionError``。
- ``fake_embedding``：确定性伪向量 ``fake_embedding(texts) ->
  list[list[float]]``——按文本全文 hash 生成 1024 维（EMBEDDING_DIM）
  单位向量，同文本恒同向量、异文本异向量；monkeypatch
  ``common.embedding_client`` 的 ``embed_texts`` / ``is_available`` /
  ``active_model``（模型名固定 ``fake-embedding-model``）。置
  ``fake_embedding.fail = True`` 后 embed 抛 ``ConnectionError``、
  is_available 返回 False。
"""

import base64
import hashlib
import io
import math
from decimal import Decimal
from itertools import count
from types import SimpleNamespace

import pytest

from src.app import create_app
from src.common import redis_client, security
from src.config import Config
from src.model import Campus, Category, Image, School, User, db

# 1×1 合法 PNG（上传四件套按扩展名/MIME/大小/内容哈希校验，不解析像素）
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
DEFAULT_PASSWORD = "Pass1234"

_user_seq = count(1)


class TestConfig(Config):
    """测试配置：不依赖真实凭据（依赖探针在各用例内注入替换）。"""

    TESTING = True
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


@pytest.fixture()
def app():
    return create_app(TestConfig)


@pytest.fixture()
def client(app):
    return app.test_client()


class FakeRedis:
    """内存 Redis 桩：覆盖限流（incr/expire/get/delete）与黑名单（setex/exists）。

    ``fail = True`` 后所有方法抛 ``ConnectionError``，用于降级演练
    （黑名单 fail-open、限流放行）。不引入任何新包。
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}
        self.fail = False

    def _maybe_fail(self) -> None:
        if self.fail:
            raise ConnectionError("模拟 Redis 故障")

    def get(self, key: str) -> str | None:
        self._maybe_fail()
        return self.store.get(key)

    def setex(self, key: str, seconds: int, value: str) -> None:
        self._maybe_fail()
        self.store[key] = str(value)

    def delete(self, *keys: str) -> int:
        self._maybe_fail()
        removed = 0
        for key in keys:
            if self.store.pop(key, None) is not None:
                removed += 1
        return removed

    def exists(self, key: str) -> int:
        self._maybe_fail()
        return 1 if key in self.store else 0

    def incr(self, key: str) -> int:
        self._maybe_fail()
        value = int(self.store.get(key, "0")) + 1
        self.store[key] = str(value)
        return value

    def expire(self, key: str, seconds: int) -> bool:
        self._maybe_fail()
        return key in self.store

    # ---- 列表操作（b2be2 向量重试队列 queue:vector:retry）----

    def rpush(self, key: str, value: str) -> int:
        self._maybe_fail()
        self.lists.setdefault(key, []).append(str(value))
        return len(self.lists[key])

    def lpop(self, key: str) -> str | None:
        self._maybe_fail()
        items = self.lists.get(key)
        if not items:
            return None
        return items.pop(0)

    def llen(self, key: str) -> int:
        self._maybe_fail()
        return len(self.lists.get(key, []))


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    """全用例隔离真实 Redis：get_redis 一律返回内存桩（防误连本机实例）。

    多库版 ``get_redis(db_offset)`` 按 offset 返回**同一**内存桩——测试
    用键名区分（product:* / auth:* / rate:*），键空间不隔离即可。
    """
    stub = FakeRedis()
    monkeypatch.setattr(redis_client, "get_redis", lambda db_offset=3: stub)
    return stub


@pytest.fixture()
def db_create_all(app):
    """应用上下文内建全部表；上下文在用例期间保持，可直接造数查询。"""
    with app.app_context():
        db.create_all()
        yield db


@pytest.fixture()
def school_fixtures(db_create_all):
    """学校/校区造数：多校区(2 启用校区)、单校区、停用学校各一。"""
    multi = School(name="示例大学", multi_campus=True, status="enabled")
    east = Campus(school=multi, name="东校区", status="enabled")
    west = Campus(school=multi, name="西校区", status="enabled")
    disabled_campus = Campus(school=multi, name="停用校区", status="disabled")
    single = School(name="示例学院", multi_campus=False, status="enabled")
    main_campus = Campus(school=single, name="主校区", status="enabled")
    disabled = School(name="停用学院", multi_campus=False, status="disabled")
    db.session.add_all(
        [multi, east, west, disabled_campus, single, main_campus, disabled]
    )
    db.session.commit()
    return SimpleNamespace(
        multi=multi,
        east=east,
        west=west,
        disabled_campus=disabled_campus,
        single=single,
        main_campus=main_campus,
        disabled=disabled,
    )


@pytest.fixture()
def user_factory(db_create_all):
    """用户造数工厂：直接落库，返回 detach 安全的标量 dict。"""

    def _create(**overrides) -> dict:
        password = overrides.pop("password", DEFAULT_PASSWORD)
        seq = overrides.pop("seq", next(_user_seq))
        fields = {
            "username": f"user{seq:04d}",
            "student_no": f"2024{seq:08d}",
            "email": f"user{seq:04d}@example.edu.cn",
            "nickname": f"用户{seq:04d}",
            "role": "student",
            "auth_status": "unverified",
            "status": "active",
        }
        fields.update(overrides)
        user = User(
            display_name=fields["nickname"],
            password_hash=security.hash_password(password),
            **fields,
        )
        if fields.get("school_id") is not None and fields["auth_status"] == "approved":
            school = db.session.get(School, fields["school_id"])
            campus = (
                db.session.get(Campus, fields["campus_id"])
                if fields.get("campus_id") is not None
                else None
            )
            user.display_name_recalc(school, campus)
        db.session.add(user)
        db.session.commit()
        return {
            "id": user.id,
            "username": user.username,
            "student_no": user.student_no,
            "email": user.email,
            "nickname": user.nickname,
            "display_name": user.display_name,
            "password": password,
            "role": user.role,
            "auth_status": user.auth_status,
            "status": user.status,
            "school_id": user.school_id,
            "campus_id": user.campus_id,
        }

    return _create


@pytest.fixture()
def approved_user(user_factory, school_fixtures):
    """已认证（approved）学生：挂多校区学校与东校区，展示名已重算。"""
    return user_factory(
        username="approved01",
        student_no="2024010101",
        nickname="小张",
        school_id=school_fixtures.multi.id,
        campus_id=school_fixtures.east.id,
        auth_status="approved",
    )


@pytest.fixture()
def make_auth_header(app):
    """按用户 id 签发 JWT 并返回 Authorization 头。"""

    def _make(user_id: int) -> dict[str, str]:
        with app.app_context():
            token, _ = security.issue_token(SimpleNamespace(id=user_id))
        return {"Authorization": f"Bearer {token}"}

    return _make


@pytest.fixture()
def upload_app(app, tmp_path):
    """UPLOAD_DIR 指向用例级临时目录，避免写入仓库 uploads/。"""
    app.config["UPLOAD_DIR"] = str(tmp_path / "uploads")
    return app


@pytest.fixture()
def category_fixtures(db_create_all):
    """分类造数：6 个启用分类（sort_order 1–6，联调同款命名）。"""
    names = ["数码电子", "图书教材", "生活用品", "运动户外", "服饰鞋包", "其他"]
    items = [
        Category(name=name, sort_order=i + 1, status="enabled")
        for i, name in enumerate(names)
    ]
    db_create_all.session.add_all(items)
    db_create_all.session.commit()
    return SimpleNamespace(items=items, by_name={c.name: c for c in items})


@pytest.fixture()
def product_factory(db_create_all):
    """商品造数工厂：含 purpose=product 图片记录与 product_images 关联。

    参数化 status/school/campus/price/condition/forced_off/image_count；
    默认卖家本人的学校与校区、1 张图、在售。
    """
    from src.model import Product, ProductImage

    _img_seq = count(1)

    def _create(
        seller: dict,
        category_id: int,
        *,
        status: str = "on_sale",
        price: str = "100.00",
        condition: str = "excellent",
        school_id: int | None = None,
        campus_id: int | None = None,
        title: str = "测试商品",
        description: str = "测试描述",
        image_count: int = 1,
        forced_off: bool = False,
    ) -> Product:
        images = [
            Image(
                owner_id=seller["id"],
                path=f"product/2026-10/{next(_img_seq):04d}.png",
                mime="image/png",
                size_bytes=100,
                sha256=f"{next(_img_seq):064x}",
                purpose="product",
            )
            for _ in range(image_count)
        ]
        product = Product(
            seller_id=seller["id"],
            school_id=school_id if school_id is not None else seller["school_id"],
            campus_id=campus_id if campus_id is not None else seller["campus_id"],
            category_id=category_id,
            title=title,
            description=description,
            price=Decimal(price),
            condition=condition,
            status=status,
            forced_off=forced_off,
        )
        db_create_all.session.add_all(images)
        db_create_all.session.flush()
        for i, image in enumerate(images):
            db_create_all.session.add(
                ProductImage(product=product, image=image, sort_order=i)
            )
        db_create_all.session.add(product)
        db_create_all.session.commit()
        return product

    return _create


@pytest.fixture()
def owned_product_images(db_create_all):
    """为指定用户造 n 张 purpose=product 的图片记录（不经上传接口），
    返回图片 id 列表——发布接口用例的 image_ids 素材。"""
    _seq = count(1)

    def _make(owner_id: int, n: int = 1) -> list[int]:
        ids = []
        for _ in range(n):
            seq = next(_seq)
            image = Image(
                owner_id=owner_id,
                path=f"product/2026-10/img{seq:04d}.png",
                mime="image/png",
                size_bytes=100,
                sha256=f"{seq:064x}",
                purpose="product",
            )
            db_create_all.session.add(image)
            db_create_all.session.flush()
            ids.append(image.id)
        db_create_all.session.commit()
        return ids

    return _make


@pytest.fixture()
def png_upload():
    """构造 PNG multipart 文件字段（可改文件名/MIME 做类型校验反例）。"""

    def _make(name: str = "a.png", mime: str = "image/png", data: bytes | None = None):
        return {"file": (io.BytesIO(data or PNG_1PX), name, mime)}

    return _make


# ============================================================
# b2be2 三桩：fake_mongo / fake_chroma / fake_embedding
# （接口形态见模块 docstring；b3/b4 可复用）
# ============================================================


class FakeMongoCollection:
    """内存集合桩：等值过滤 + $set/$inc 更新 + upsert（覆盖 b2be2 所用子集）。"""

    def __init__(self) -> None:
        self.docs: list[dict] = []
        self.indexes: list[tuple] = []

    @staticmethod
    def _match(doc: dict, filter_: dict | None) -> bool:
        if not filter_:
            return True
        for key, value in filter_.items():
            actual = doc.get(key)
            if isinstance(value, dict) and value and all(
                op.startswith("$") for op in value
            ):
                # 比较操作符子集（b2be2 画像 24h 去重用 $gte）
                for op, operand in value.items():
                    if op == "$gte" and not (actual is not None and actual >= operand):
                        return False
                    if op == "$gt" and not (actual is not None and actual > operand):
                        return False
                    if op == "$lte" and not (actual is not None and actual <= operand):
                        return False
                    if op == "$lt" and not (actual is not None and actual < operand):
                        return False
                continue
            if actual != value:
                return False
        return True

    @staticmethod
    def _apply(doc: dict, update: dict) -> None:
        unknown = set(update) - {"$set", "$inc"}
        if unknown:
            raise NotImplementedError(f"FakeMongoCollection 不支持操作符: {unknown}")
        for key, value in (update.get("$set") or {}).items():
            doc[key] = value
        for key, value in (update.get("$inc") or {}).items():
            doc[key] = doc.get(key, 0) + value

    def find_one(self, filter_: dict | None = None, *args, **kwargs) -> dict | None:
        for doc in self.docs:
            if self._match(doc, filter_):
                return dict(doc)
        return None

    def find(self, filter_: dict | None = None) -> list[dict]:
        return [dict(doc) for doc in self.docs if self._match(doc, filter_)]

    def insert_one(self, doc: dict):
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id=len(self.docs))

    def update_one(self, filter_: dict, update: dict, upsert: bool = False):
        for doc in self.docs:
            if self._match(doc, filter_):
                self._apply(doc, update)
                return SimpleNamespace(matched_count=1, upserted_id=None)
        if upsert:
            doc = dict(filter_)
            self._apply(doc, update)
            self.docs.append(doc)
            return SimpleNamespace(matched_count=0, upserted_id=len(self.docs))
        return SimpleNamespace(matched_count=0, upserted_id=None)

    def delete_one(self, filter_: dict):
        for i, doc in enumerate(self.docs):
            if self._match(doc, filter_):
                del self.docs[i]
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)

    def delete_many(self, filter_: dict | None = None):
        before = len(self.docs)
        self.docs = [d for d in self.docs if not self._match(d, filter_)]
        return SimpleNamespace(deleted_count=before - len(self.docs))

    def create_index(self, *keys, **kwargs):
        """幂等 no-op：仅记录签名供断言。"""
        self.indexes.append((keys, tuple(sorted(kwargs.items()))))
        return f"idx_{len(self.indexes)}"


class FakeMongoDatabase:
    """内存库桩：按集合名懒建集合（dict 与属性两种访问形态）。"""

    def __init__(self) -> None:
        self._collections: dict[str, FakeMongoCollection] = {}
        self.fail = False

    def __getitem__(self, name: str) -> FakeMongoCollection:
        return self._collections.setdefault(name, FakeMongoCollection())

    def __getattr__(self, name: str) -> FakeMongoCollection:
        # 仅在常规属性查找失败时进入（_collections 已在 __init__ 落 __dict__）
        return self[name]


@pytest.fixture(autouse=True)
def fake_mongo(monkeypatch):
    """monkeypatch ``common.mongo_client.get_db`` 注入内存库桩。

    autouse：router 接线后事件订阅者在全部用例中可达，桩化保证任何
    用例（含 b2be 存量）都不触真实 Mongo。"""
    from src.common import mongo_client

    stub = FakeMongoDatabase()

    def _get_db():
        if stub.fail:
            raise ConnectionError("模拟 Mongo 故障")
        return stub

    monkeypatch.setattr(mongo_client, "get_db", _get_db)
    return stub


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _match_where(metadata: dict, where: dict | None) -> bool:
    """Chroma where 子集：等值与 $and（b2be2 仅用这两种形态）。"""
    if not where:
        return True
    if "$and" in where:
        return all(_match_where(metadata, cond) for cond in where["$and"])
    return all(metadata.get(key) == value for key, value in where.items())


class FakeChromaCollection:
    """内存余弦 top-k 桩：距离 = 1 − 余弦相似度（与真实 cosine 空间同构）。"""

    def __init__(self) -> None:
        self.name = "product_vectors-test"
        self.metadata = {"hnsw:space": "cosine"}
        self.vectors: dict[str, list[float]] = {}
        self.documents: dict[str, str] = {}
        self.metadatas: dict[str, dict] = {}

    def upsert(self, ids, embeddings, documents=None, metadatas=None):
        for i, item_id in enumerate(ids):
            self.vectors[str(item_id)] = list(embeddings[i])
            if documents is not None:
                self.documents[str(item_id)] = documents[i]
            if metadatas is not None:
                self.metadatas[str(item_id)] = dict(metadatas[i])

    def query(self, query_embeddings, n_results: int = 10, where: dict | None = None):
        scored: list[tuple[str, float]] = []
        query = query_embeddings[0]
        for item_id, vector in self.vectors.items():
            if _match_where(self.metadatas.get(item_id, {}), where):
                scored.append((item_id, 1.0 - _cosine(query, vector)))
        scored.sort(key=lambda pair: pair[1])
        top = scored[:n_results]
        return {
            "ids": [[item_id for item_id, _ in top]],
            "distances": [[distance for _, distance in top]],
        }

    def update(
        self,
        ids,
        embeddings=None,
        metadatas=None,
        documents=None,
        images=None,
        uris=None,
    ):
        """镜像 chromadb-client 1.5.9 ``Collection.update`` 真实签名。

        参数名与真实 API 逐字一致（``metadatas`` 复数、无 ``**kwargs``），
        作为生产调用侧关键字拼写的防回归锚点——传 ``metadata=`` 单数将直接
        TypeError，与真实 Chroma 行为同构。语义：仅更新已存在条目的提供字段
        （metadata 按键合并，与真实 update 一致），不创建新条目。
        """
        for i, item_id in enumerate(ids):
            item_id = str(item_id)
            if item_id not in self.vectors:
                continue
            if embeddings is not None:
                self.vectors[item_id] = list(embeddings[i])
            if documents is not None:
                self.documents[item_id] = documents[i]
            if metadatas is not None:
                self.metadatas[item_id].update(dict(metadatas[i]))

    def get(self, ids=None):
        wanted = [str(i) for i in ids] if ids else list(self.vectors)
        return {"ids": [i for i in wanted if i in self.vectors]}

    def delete(self, ids=None):
        for item_id in [str(i) for i in (ids or [])]:
            self.vectors.pop(item_id, None)
            self.documents.pop(item_id, None)
            self.metadatas.pop(item_id, None)


@pytest.fixture(autouse=True)
def fake_chroma(monkeypatch):
    """monkeypatch ``common.chroma_client.get_collection/delete_collection``。

    autouse 理由同 fake_mongo。"""
    from src.common import chroma_client

    stub = FakeChromaCollection()
    state = {"fail": False}

    def _get_collection():
        if state["fail"]:
            raise ConnectionError("模拟 Chroma 故障")
        return stub

    def _delete_collection():
        stub.vectors.clear()
        stub.documents.clear()
        stub.metadatas.clear()

    monkeypatch.setattr(chroma_client, "get_collection", _get_collection)
    monkeypatch.setattr(chroma_client, "delete_collection", _delete_collection)
    stub.fail = state  # 用例经 stub.fail["fail"] = True 演练故障
    return stub


def _pseudo_vector(text: str, dim: int) -> list[float]:
    """确定性伪向量：全文 SHA-256 hash 决定相位，正弦叠加后归一化为单位向量。"""
    seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
    raw = [
        math.sin(seed * 0.37 + i * 0.11) + 0.05 * ((seed + i) % 5 - 2)
        for i in range(dim)
    ]
    norm = math.sqrt(sum(v * v for v in raw)) or 1.0
    return [v / norm for v in raw]


@pytest.fixture(autouse=True)
def fake_embedding(monkeypatch):
    """确定性伪 embedding：同文本恒同向量；记录调用文本供断言。

    autouse 理由同 fake_mongo（测试一律走桩，不依赖真实侧车）。"""
    from flask import current_app

    from src.common import embedding_client

    def _embed(texts):
        if _embed.fail:
            raise ConnectionError("模拟 embedding 故障")
        _embed.calls.extend(texts)
        try:
            dim = current_app.config["EMBEDDING_DIM"]
        except RuntimeError:  # 无应用上下文（纯函数测试）
            dim = 1024
        return [_pseudo_vector(text, dim) for text in texts]

    _embed.calls = []
    _embed.fail = False

    def _is_available():
        if _embed.fail:
            return False, "embedding 不可用（测试桩）"
        return True, "ok"

    monkeypatch.setattr(embedding_client, "embed_texts", _embed)
    monkeypatch.setattr(embedding_client, "is_available", _is_available)
    monkeypatch.setattr(embedding_client, "active_model", lambda: "fake-embedding-model")
    return _embed


@pytest.fixture()
def wired_events():
    """重置并注册 b2be2 事件订阅（幂等接线在测试中的可重复形态）。

    router 在 create_app 时已调用 ``register_all``，但个别用例（如
    test_product_events）会清空 ``events._HANDLERS``；本夹具显式复位
    注册态，用例结束再清场，避免跨用例泄漏。
    """
    from src.services import events_subscribers

    events_subscribers._reset_for_tests()
    events_subscribers.register_all()
    yield
    events_subscribers._reset_for_tests()
