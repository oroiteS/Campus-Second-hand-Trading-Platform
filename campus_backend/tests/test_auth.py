"""auth 域测试：注册 / 登录 / 登出 / 密码重置（契约 0.2.0 行为与错误码）。"""

import pytest

from src.common.security import verify_password
from src.model import User, db
from tests.conftest import DEFAULT_PASSWORD

REGISTER_URL = "/api/auth/register"
LOGIN_URL = "/api/auth/login"
LOGOUT_URL = "/api/auth/logout"
RESET_URL = "/api/auth/password/reset"

VALID = {
    "username": "zhangsan01",
    "password": "Pass1234",
    "email": "zhangsan01@example.edu.cn",
    "student_no": "2024010101",
}


def _register(client, **overrides):
    return client.post(REGISTER_URL, json={**VALID, **overrides})


def _login(client, account, password):
    return client.post(LOGIN_URL, json={"account": account, "password": password})


def _body(res):
    return res.get_json()


class TestRegister:
    def test_register_success_returns_profile_without_token(self, client, db_create_all):
        res = _register(client, nickname="小张")
        assert res.status_code == 200
        body = _body(res)
        assert (body["code"], body["message"]) == (0, "ok")
        data = body["data"]
        assert set(data) == {
            "id", "username", "student_no", "email", "nickname", "display_name",
            "phone", "avatar", "school", "campus", "role", "auth_status", "status",
            "credit_score", "created_at",
        }
        assert data["username"] == "zhangsan01"
        assert data["nickname"] == "小张"
        assert data["display_name"] == "小张"  # 未认证：展示名 = 昵称
        assert data["role"] == "student"
        assert data["auth_status"] == "unverified"
        assert data["status"] == "active"
        assert data["phone"] is None and data["avatar"] is None
        assert data["school"] is None and data["campus"] is None
        assert data["credit_score"] is None
        assert data["created_at"].endswith("+08:00")
        assert "access_token" not in data  # 注册不签发令牌

    def test_password_stored_as_bcrypt_hash(self, client, db_create_all):
        data = _register(client).get_json()["data"]
        with client.application.app_context():
            user = db.session.get(User, data["id"])
            assert user.password_hash.startswith("$2")
            assert VALID["password"] not in user.password_hash  # 无明文
            assert verify_password(VALID["password"], user.password_hash)

    def test_nickname_defaults_to_username(self, client, db_create_all):
        data = _register(client).get_json()["data"]
        assert data["nickname"] == "zhangsan01"

    def test_duplicate_username_2001(self, client, db_create_all):
        assert _register(client).status_code == 200
        res = _register(client, student_no="other01")
        assert (res.status_code, _body(res)["code"]) == (409, 2001)

    def test_duplicate_student_no_2002(self, client, db_create_all):
        assert _register(client).status_code == 200
        res = _register(client, username="other01")
        assert (res.status_code, _body(res)["code"]) == (409, 2002)

    @pytest.mark.parametrize(
        "bad_password",
        ["abc1", "noupperc", "12345678", "abcdefgh"],
        ids=["too_short", "no_digit", "no_letter", "no_digit"],
    )
    def test_weak_password_9001_with_field(self, client, db_create_all, bad_password):
        res = _register(client, password=bad_password)
        assert res.status_code == 422
        body = _body(res)
        assert body["code"] == 9001
        assert "password" in body["data"]["fields"]

    def test_missing_required_field_9001(self, client, db_create_all):
        payload = {k: v for k, v in VALID.items() if k != "email"}
        res = client.post(REGISTER_URL, json=payload)
        assert (res.status_code, _body(res)["code"]) == (422, 9001)
        assert "email" in _body(res)["data"]["fields"]

    def test_bad_username_pattern_9001(self, client, db_create_all):
        res = _register(client, username="1startswithdigit")
        assert _body(res)["code"] == 9001
        assert "username" in _body(res)["data"]["fields"]

    def test_non_object_body_9001(self, client, db_create_all):
        res = client.post(REGISTER_URL, json=[1, 2])
        assert (res.status_code, _body(res)["code"]) == (422, 9001)


class TestLogin:
    @pytest.fixture()
    def registered(self, client, db_create_all):
        _register(client)
        return VALID

    def test_login_by_username(self, client, registered):
        res = _login(client, registered["username"], registered["password"])
        assert res.status_code == 200
        data = _body(res)["data"]
        assert set(data) == {"access_token", "token_type", "expires_in", "user"}
        assert data["token_type"] == "Bearer"
        assert data["expires_in"] == 1440 * 60
        assert data["user"]["username"] == registered["username"]

    def test_login_by_student_no(self, client, registered):
        res = _login(client, registered["student_no"], registered["password"])
        assert (res.status_code, _body(res)["code"]) == (200, 0)

    def test_wrong_password_2005(self, client, registered):
        res = _login(client, registered["username"], "WrongPass1")
        assert (res.status_code, _body(res)["code"]) == (401, 2005)

    def test_unknown_account_same_code_as_wrong_password(self, client, registered):
        """防探测：用户名不存在与密码错误同码 2005。"""
        wrong_pw = _login(client, registered["username"], "WrongPass1").get_json()["code"]
        unknown = _login(client, "ghost01", "Whatever1").get_json()["code"]
        assert wrong_pw == unknown == 2005

    def test_banned_account_2006_even_with_correct_password(
        self, client, db_create_all, user_factory
    ):
        banned = user_factory(status="banned", password="Pass1234")
        res = _login(client, banned["username"], "Pass1234")
        assert (res.status_code, _body(res)["code"]) == (403, 2006)

    def test_banned_failure_counts_toward_rate_limit(
        self, client, db_create_all, user_factory
    ):
        """封禁按一次失败计入限流：2006 ×1 + 2005 ×4 → 第 6 次尝试 1006。"""
        banned = user_factory(status="banned")
        assert _login(client, banned["username"], "Pass1234").get_json()["code"] == 2006
        for _ in range(4):
            assert _login(client, banned["username"], "WrongPass1").get_json()["code"] == 2005
        res = _login(client, banned["username"], "WrongPass1")
        assert (res.status_code, _body(res)["code"]) == (429, 1006)

    def test_fifth_consecutive_failure_blocks_with_1006(self, client, registered):
        for i in range(5):
            res = _login(client, registered["username"], "WrongPass1")
            if i < 5:
                assert (res.status_code, _body(res)["code"]) == (401, 2005)
        res = _login(client, registered["username"], "WrongPass1")  # 第 6 次尝试
        assert (res.status_code, _body(res)["code"]) == (429, 1006)

    def test_success_clears_failure_counter(self, client, registered):
        """成功清零：4 次失败后成功，再失败也不会提前触发限流。"""
        for _ in range(4):
            assert _login(client, registered["username"], "WrongPass1").status_code == 401
        assert _login(client, registered["username"], registered["password"]).status_code == 200
        assert _login(client, registered["username"], "WrongPass1").status_code == 401
        # 未清零的话，此处计数已到 6，会 429
        assert _login(client, registered["username"], registered["password"]).status_code == 200

    def test_rate_limit_fail_open_when_redis_down(
        self, client, registered, fake_redis
    ):
        """Redis 故障：限流降级放行，登录照常按密码结果响应。"""
        fake_redis.fail = True
        for _ in range(7):
            res = _login(client, registered["username"], "WrongPass1")
            assert (res.status_code, _body(res)["code"]) == (401, 2005)
        res = _login(client, registered["username"], registered["password"])
        assert res.status_code == 200

    def test_missing_account_9001(self, client, db_create_all):
        res = client.post(LOGIN_URL, json={"password": "x"})
        assert (res.status_code, _body(res)["code"]) == (422, 9001)


class TestLogout:
    def test_logout_then_old_token_rejected_1003(self, client, db_create_all):
        _register(client)
        token = _login(client, VALID["username"], VALID["password"]).get_json()["data"][
            "access_token"
        ]
        headers = {"Authorization": f"Bearer {token}"}
        res = client.post(LOGOUT_URL, headers=headers)
        assert res.status_code == 200
        assert _body(res)["data"] == {}
        # 同一令牌再次访问受保护接口 → 注销态 401/1003
        res = client.post(LOGOUT_URL, headers=headers)
        assert (res.status_code, _body(res)["code"]) == (401, 1003)

    def test_logout_degraded_when_redis_down(self, client, db_create_all, fake_redis):
        """Redis 故障：仍 200，data 带 degraded 标记；令牌有效至自然过期。"""
        _register(client)
        token = _login(client, VALID["username"], VALID["password"]).get_json()["data"][
            "access_token"
        ]
        headers = {"Authorization": f"Bearer {token}"}
        fake_redis.fail = True
        res = client.post(LOGOUT_URL, headers=headers)
        assert res.status_code == 200
        assert _body(res)["code"] == 0
        data = _body(res)["data"]
        assert data["degraded"] is True
        assert isinstance(data["degraded_reason"], str) and data["degraded_reason"]
        # 黑名单未落：同令牌仍可用（blocklist 查询 fail-open 放行）
        res = client.post(LOGOUT_URL, headers=headers)
        assert res.status_code == 200

    def test_logout_requires_login(self, client, db_create_all):
        res = client.post(LOGOUT_URL)
        assert (res.status_code, _body(res)["code"]) == (401, 1001)


class TestPasswordReset:
    @pytest.fixture()
    def registered(self, client, db_create_all):
        _register(client)
        return VALID

    def test_reset_by_student_no_then_new_password_works(self, client, registered):
        res = client.post(
            RESET_URL,
            json={
                "username": registered["username"],
                "reset_channel": "student_no",
                "reset_value": registered["student_no"],
                "new_password": "NewPass1234",
            },
        )
        assert res.status_code == 200
        assert _body(res)["data"] is None
        assert _login(client, registered["username"], DEFAULT_PASSWORD).status_code == 401
        assert _login(client, registered["username"], "NewPass1234").status_code == 200

    def test_reset_by_email(self, client, registered):
        res = client.post(
            RESET_URL,
            json={
                "username": registered["username"],
                "reset_channel": "email",
                "reset_value": registered["email"],
                "new_password": "NewPass1234",
            },
        )
        assert (res.status_code, _body(res)["code"]) == (200, 0)

    def test_reset_channel_mismatch_2004(self, client, registered):
        """学号渠道给了邮箱（或反之）→ 凭证不匹配 2004。"""
        res = client.post(
            RESET_URL,
            json={
                "username": registered["username"],
                "reset_channel": "student_no",
                "reset_value": registered["email"],
                "new_password": "NewPass1234",
            },
        )
        assert (res.status_code, _body(res)["code"]) == (422, 2004)

    def test_reset_unknown_username_same_2004(self, client, registered):
        """防探测：用户名不存在同样 2004。"""
        res = client.post(
            RESET_URL,
            json={
                "username": "ghost01",
                "reset_channel": "student_no",
                "reset_value": registered["student_no"],
                "new_password": "NewPass1234",
            },
        )
        assert (res.status_code, _body(res)["code"]) == (422, 2004)

    def test_reset_weak_new_password_9001(self, client, registered):
        res = client.post(
            RESET_URL,
            json={
                "username": registered["username"],
                "reset_channel": "student_no",
                "reset_value": registered["student_no"],
                "new_password": "12345678",
            },
        )
        assert (res.status_code, _body(res)["code"]) == (422, 9001)
        assert "new_password" in _body(res)["data"]["fields"]

    def test_reset_bad_channel_9001(self, client, registered):
        res = client.post(
            RESET_URL,
            json={
                "username": registered["username"],
                "reset_channel": "phone",
                "reset_value": registered["student_no"],
                "new_password": "NewPass1234",
            },
        )
        assert (res.status_code, _body(res)["code"]) == (422, 9001)
        assert "reset_channel" in _body(res)["data"]["fields"]
