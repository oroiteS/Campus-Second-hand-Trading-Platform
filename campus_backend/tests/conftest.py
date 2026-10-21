"""pytest 公共 fixture：应用与测试客户端、内存 Redis 桩、建表与造数工厂。"""

import base64
import io
from itertools import count
from types import SimpleNamespace

import pytest

from src.app import create_app
from src.common import redis_client, security
from src.config import Config
from src.model import Campus, School, User, db

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


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    """全用例隔离真实 Redis：get_redis 一律返回内存桩（防误连本机实例）。"""
    stub = FakeRedis()
    monkeypatch.setattr(redis_client, "get_redis", lambda: stub)
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
    single = School(name="示例学院", multi_campus=False, status="enabled")
    main_campus = Campus(school=single, name="主校区", status="enabled")
    disabled = School(name="停用学院", multi_campus=False, status="disabled")
    db.session.add_all([multi, east, west, single, main_campus, disabled])
    db.session.commit()
    return SimpleNamespace(
        multi=multi,
        east=east,
        west=west,
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
def png_upload():
    """构造 PNG multipart 文件字段（可改文件名/MIME 做类型校验反例）。"""

    def _make(name: str = "a.png", mime: str = "image/png", data: bytes | None = None):
        return {"file": (io.BytesIO(data or PNG_1PX), name, mime)}

    return _make
