"""common 鉴权横切件测试：三装饰器矩阵、作用域注入、黑名单 fail-open、scoped_key。"""

from datetime import timedelta

import pytest
from flask import g
from flask_jwt_extended import create_access_token

from src.common.auth import (
    admin_required,
    inject_scope,
    login_required,
    scoped_key,
    verified_required,
)
from src.common.responses import success


def _register_probe_routes(app):
    """注册四类探针端点（公开/登录/认证/管理），响应体回显作用域上下文。"""

    @app.get("/api/__probe_public")
    def _public():
        return success({"school_id": g.school_id, "scope_all": g.scope_all})

    @app.get("/api/__probe_login")
    @login_required
    def _login():
        return success({"school_id": g.school_id, "scope_all": g.scope_all})

    @app.get("/api/__probe_verified")
    @verified_required
    def _verified():
        return success({"school_id": g.school_id, "scope_all": g.scope_all})

    @app.get("/api/__probe_admin")
    @admin_required
    def _admin():
        return success({"school_id": g.school_id, "scope_all": g.scope_all})


def _body(res):
    return res.get_json()


@pytest.fixture()
def probe_routes(app):
    """为请求探针端点的用例统一注册路由。"""
    _register_probe_routes(app)
    return app


class TestScopedKey:
    def test_login_rate_key_format(self):
        assert scoped_key("rate:login", "127.0.0.1") == "rate:login:127.0.0.1"

    def test_blacklist_key_format(self):
        assert scoped_key("auth:blacklist", "jti-abc") == "auth:blacklist:jti-abc"


class TestDecoratorMatrix:
    """游客 / 未认证学生 / 认证学生 / 管理员 × 公开 / 登录 / 认证 / 管理。"""

    @pytest.fixture()
    def probes(self, db_create_all, app, user_factory, school_fixtures):
        _register_probe_routes(app)
        unverified = user_factory(auth_status="unverified")
        approved = user_factory(
            auth_status="approved",
            school_id=school_fixtures.multi.id,
            campus_id=school_fixtures.east.id,
        )
        admin = user_factory(role="admin")
        return {"unverified": unverified, "approved": approved, "admin": admin}

    def test_public_endpoint_open_to_everyone(self, client, probes, make_auth_header):
        assert client.get("/api/__probe_public").status_code == 200
        for actor in ("unverified", "approved", "admin"):
            res = client.get(
                "/api/__probe_public", headers=make_auth_header(probes[actor]["id"])
            )
            assert res.status_code == 200

    def test_login_endpoint_blocks_guest_only(self, client, probes, make_auth_header):
        res = client.get("/api/__probe_login")
        assert res.status_code == 401
        assert _body(res)["code"] == 1001
        for actor in ("unverified", "approved", "admin"):
            res = client.get(
                "/api/__probe_login", headers=make_auth_header(probes[actor]["id"])
            )
            assert res.status_code == 200

    def test_verified_endpoint_matrix(self, client, probes, make_auth_header):
        res = client.get("/api/__probe_verified")
        assert (res.status_code, _body(res)["code"]) == (401, 1001)  # 游客
        res = client.get(
            "/api/__probe_verified", headers=make_auth_header(probes["unverified"]["id"])
        )
        assert (res.status_code, _body(res)["code"]) == (403, 1004)  # 未认证学生
        for actor in ("approved", "admin"):
            res = client.get(
                "/api/__probe_verified", headers=make_auth_header(probes[actor]["id"])
            )
            assert res.status_code == 200  # 认证学生与管理员

    def test_admin_endpoint_matrix(self, client, probes, make_auth_header):
        res = client.get("/api/__probe_admin")
        assert (res.status_code, _body(res)["code"]) == (401, 1001)  # 游客
        for actor in ("unverified", "approved"):
            res = client.get(
                "/api/__probe_admin", headers=make_auth_header(probes[actor]["id"])
            )
            assert (res.status_code, _body(res)["code"]) == (403, 1005)  # 非管理员
        res = client.get(
            "/api/__probe_admin", headers=make_auth_header(probes["admin"]["id"])
        )
        assert res.status_code == 200


class TestScopeInjection:
    def test_guest_scope_is_anonymous(self, db_create_all, app, client):
        with app.test_request_context("/api/anything"):
            inject_scope()
        assert g.school_id is None
        assert g.scope_all is False

    def test_student_scope_carries_school_id(
        self, db_create_all, probe_routes, client, approved_user, make_auth_header
    ):
        res = client.get(
            "/api/__probe_public", headers=make_auth_header(approved_user["id"])
        )
        assert res.status_code == 200
        data = _body(res)["data"]
        assert data["school_id"] == approved_user["school_id"]
        assert data["scope_all"] is False

    def test_admin_scope_all(
        self, db_create_all, probe_routes, client, user_factory, make_auth_header
    ):
        admin = user_factory(role="admin")
        res = client.get("/api/__probe_public", headers=make_auth_header(admin["id"]))
        data = _body(res)["data"]
        assert data["scope_all"] is True

    def test_stale_token_on_public_endpoint_stays_public(
        self, db_create_all, probe_routes, client, approved_user
    ):
        """失效令牌访问公开接口：作用域按匿名，接口照常 200（不 401）。"""
        with probe_routes.app_context():
            stale = create_access_token(
                identity=str(approved_user["id"]), expires_delta=timedelta(seconds=-1)
            )
        res = client.get(
            "/api/__probe_public", headers={"Authorization": f"Bearer {stale}"}
        )
        assert res.status_code == 200


class TestJwtErrorCodes:
    def test_expired_token_1002(self, db_create_all, probe_routes, client, user_factory):
        user = user_factory()
        with probe_routes.app_context():
            expired = create_access_token(
                identity=str(user["id"]), expires_delta=timedelta(seconds=-1)
            )
        res = client.get(
            "/api/__probe_login", headers={"Authorization": f"Bearer {expired}"}
        )
        assert (res.status_code, _body(res)["code"]) == (401, 1002)

    def test_garbage_token_1001(self, db_create_all, probe_routes, client):
        res = client.get(
            "/api/__probe_login", headers={"Authorization": "Bearer not-a-jwt"}
        )
        assert (res.status_code, _body(res)["code"]) == (401, 1001)

    def test_blacklisted_token_1003(
        self, db_create_all, probe_routes, client, user_factory, fake_redis
    ):
        """命中黑名单 → 1003（模拟 logout 写入的键；黑名单与请求同一令牌）。"""
        from types import SimpleNamespace

        from flask_jwt_extended import get_jti

        from src.common.auth import scoped_key
        from src.common.security import issue_token

        user = user_factory()
        with probe_routes.app_context():
            token, _ = issue_token(SimpleNamespace(id=user["id"]))
            fake_redis.setex(scoped_key("auth:blacklist", get_jti(token)), 600, "1")
        res = client.get(
            "/api/__probe_login", headers={"Authorization": f"Bearer {token}"}
        )
        assert (res.status_code, _body(res)["code"]) == (401, 1003)


class TestBlocklistFailOpen:
    def test_redis_down_fail_open(
        self, db_create_all, probe_routes, client, user_factory, make_auth_header, fake_redis
    ):
        """Redis 故障：黑名单查询放行，请求照常可达（fail-open + 告警）。"""
        user = user_factory()
        fake_redis.fail = True
        res = client.get(
            "/api/__probe_login", headers=make_auth_header(user["id"])
        )
        assert res.status_code == 200
