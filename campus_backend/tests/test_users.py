"""users 域测试：资料读取/更新、phone 规则、改密、头像上传（含四件套反例）。"""

import hashlib
import io
from pathlib import Path

import pytest

from src.model import Image, User, db
from tests.conftest import DEFAULT_PASSWORD, PNG_1PX

ME_URL = "/api/users/me"
PASSWORD_URL = "/api/users/me/password"
AVATAR_URL = "/api/users/me/avatar"

OVER_5MB = b"\x00" * (5 * 1024 * 1024 + 1)


def _body(res):
    return res.get_json()


class TestGetMe:
    def test_profile_shape_and_unset_fields_null(
        self, client, db_create_all, user_factory, make_auth_header
    ):
        user = user_factory()
        res = client.get(ME_URL, headers=make_auth_header(user["id"]))
        assert res.status_code == 200
        data = _body(res)["data"]
        assert data["username"] == user["username"]
        assert data["display_name"] == user["nickname"]  # 未认证：展示名 = 昵称
        for field in ("phone", "avatar", "school", "campus", "credit_score"):
            assert data[field] is None

    def test_requires_login(self, client, db_create_all):
        res = client.get(ME_URL)
        assert (res.status_code, _body(res)["code"]) == (401, 1001)


class TestUpdateProfile:
    def test_update_three_fields_at_once(
        self, client, db_create_all, user_factory, make_auth_header
    ):
        user = user_factory()
        res = client.put(
            ME_URL,
            headers=make_auth_header(user["id"]),
            json={"nickname": "新昵称", "email": "new@example.edu.cn", "phone": "13812345678"},
        )
        assert res.status_code == 200
        data = _body(res)["data"]
        assert data["nickname"] == "新昵称"
        assert data["email"] == "new@example.edu.cn"
        assert data["phone"] == "13812345678"

    def test_only_updates_present_fields(
        self, client, db_create_all, user_factory, make_auth_header
    ):
        user = user_factory(email="keep@example.edu.cn", phone="13812345678")
        res = client.put(
            ME_URL, headers=make_auth_header(user["id"]), json={"nickname": "只改昵称"}
        )
        data = _body(res)["data"]
        assert data["nickname"] == "只改昵称"
        assert data["email"] == "keep@example.edu.cn"  # 未出现字段不更新
        assert data["phone"] == "13812345678"

    def test_phone_valid_13812345678(
        self, client, db_create_all, user_factory, make_auth_header
    ):
        user = user_factory()
        res = client.put(
            ME_URL, headers=make_auth_header(user["id"]), json={"phone": "13812345678"}
        )
        assert _body(res)["data"]["phone"] == "13812345678"
        with client.application.app_context():
            assert db.session.get(User, user["id"]).phone == "13812345678"

    @pytest.mark.parametrize(
        "bad_phone",
        ["1381234567", "138123456789", "1381234567a", "23812345678", 13812345678],
        ids=["10位", "12位", "含字母", "非1开头", "数字类型"],
    )
    def test_phone_invalid_9001_field(
        self, client, db_create_all, user_factory, make_auth_header, bad_phone
    ):
        user = user_factory()
        res = client.put(
            ME_URL, headers=make_auth_header(user["id"]), json={"phone": bad_phone}
        )
        assert res.status_code == 422
        assert _body(res)["code"] == 9001
        assert "phone" in _body(res)["data"]["fields"]

    def test_phone_empty_string_clears_to_null(
        self, client, db_create_all, user_factory, make_auth_header
    ):
        user = user_factory(phone="13812345678")
        res = client.put(
            ME_URL, headers=make_auth_header(user["id"]), json={"phone": ""}
        )
        assert _body(res)["data"]["phone"] is None
        with client.application.app_context():
            assert db.session.get(User, user["id"]).phone is None  # 存 NULL

    def test_approved_nickname_change_recalcs_display_name(
        self, client, db_create_all, approved_user, make_auth_header
    ):
        """approved 造数用户改昵称 → 展示名联动重算（AC-04）。"""
        res = client.put(
            ME_URL, headers=make_auth_header(approved_user["id"]), json={"nickname": "小明明"}
        )
        data = _body(res)["data"]
        assert data["display_name"] == "小明明-示例大学(东校区)"

    def test_unverified_nickname_change_keeps_display_name_as_nickname(
        self, client, db_create_all, user_factory, make_auth_header
    ):
        user = user_factory()
        res = client.put(
            ME_URL, headers=make_auth_header(user["id"]), json={"nickname": "改名了"}
        )
        assert _body(res)["data"]["display_name"] == "改名了"

    def test_username_not_updatable(self, client, db_create_all, user_factory, make_auth_header):
        """username / student_no 不在请求体口径内：传入即被忽略。"""
        user = user_factory()
        res = client.put(
            ME_URL,
            headers=make_auth_header(user["id"]),
            json={"username": "hacker", "student_no": "999", "nickname": "正常"},
        )
        data = _body(res)["data"]
        assert data["username"] == user["username"]
        assert data["student_no"] == user["student_no"]

    def test_non_object_body_9001(self, client, db_create_all, user_factory, make_auth_header):
        user = user_factory()
        res = client.put(ME_URL, headers=make_auth_header(user["id"]), json="str")
        assert (res.status_code, _body(res)["code"]) == (422, 9001)


class TestChangePassword:
    def test_wrong_old_password_2003(
        self, client, db_create_all, user_factory, make_auth_header
    ):
        user = user_factory(password=DEFAULT_PASSWORD)
        res = client.put(
            PASSWORD_URL,
            headers=make_auth_header(user["id"]),
            json={"old_password": "WrongOld1", "new_password": "NewPass1234"},
        )
        assert (res.status_code, _body(res)["code"]) == (400, 2003)

    def test_change_then_login_with_new_password(
        self, client, db_create_all, user_factory, make_auth_header
    ):
        user = user_factory(password=DEFAULT_PASSWORD)
        res = client.put(
            PASSWORD_URL,
            headers=make_auth_header(user["id"]),
            json={"old_password": DEFAULT_PASSWORD, "new_password": "NewPass1234"},
        )
        assert res.status_code == 200
        assert _body(res)["data"] is None
        login = client.post(
            "/api/auth/login",
            json={"account": user["username"], "password": "NewPass1234"},
        )
        assert login.status_code == 200

    def test_weak_new_password_9001(
        self, client, db_create_all, user_factory, make_auth_header
    ):
        user = user_factory(password=DEFAULT_PASSWORD)
        res = client.put(
            PASSWORD_URL,
            headers=make_auth_header(user["id"]),
            json={"old_password": DEFAULT_PASSWORD, "new_password": "nodigit"},
        )
        assert (res.status_code, _body(res)["code"]) == (422, 9001)
        assert "new_password" in _body(res)["data"]["fields"]


class TestUploadAvatar:
    def test_upload_success_updates_avatar_and_saves_hashed_file(
        self, upload_app, db_create_all, user_factory, make_auth_header
    ):
        client = upload_app.test_client()
        user = user_factory()
        res = client.post(
            AVATAR_URL,
            headers=make_auth_header(user["id"]),
            data={"file": (io.BytesIO(PNG_1PX), "me.png", "image/png")},
        )
        assert res.status_code == 200
        data = _body(res)["data"]
        assert data["avatar"]["url"] == f"/api/images/{data['avatar']['id']}"
        with client.application.app_context():
            image = db.session.get(Image, data["avatar"]["id"])
            assert image.purpose == "avatar"
            assert image.owner_id == user["id"]
            assert image.mime == "image/png"
            assert image.sha256 == hashlib.sha256(PNG_1PX).hexdigest()
            # path 为相对路径，文件应已按内容哈希改名落盘
            path = Path(upload_app.config["UPLOAD_DIR"]) / image.path
            assert path.exists()
            assert path.name == f"{image.sha256}.png"

    def test_oversize_5mb_rejected_9001(
        self, upload_app, db_create_all, user_factory, make_auth_header
    ):
        client = upload_app.test_client()
        user = user_factory()
        res = client.post(
            AVATAR_URL,
            headers=make_auth_header(user["id"]),
            data={"file": (io.BytesIO(OVER_5MB), "big.png", "image/png")},
        )
        assert res.status_code == 422
        assert _body(res)["code"] == 9001
        assert "file" in _body(res)["data"]["fields"]

    def test_mime_extension_mismatch_rejected_9001(
        self, upload_app, db_create_all, user_factory, make_auth_header
    ):
        client = upload_app.test_client()
        user = user_factory()
        res = client.post(
            AVATAR_URL,
            headers=make_auth_header(user["id"]),
            data={"file": (io.BytesIO(PNG_1PX), "fake.png", "text/plain")},
        )
        assert (res.status_code, _body(res)["code"]) == (422, 9001)

    def test_unsupported_extension_rejected_9001(
        self, upload_app, db_create_all, user_factory, make_auth_header
    ):
        client = upload_app.test_client()
        user = user_factory()
        res = client.post(
            AVATAR_URL,
            headers=make_auth_header(user["id"]),
            data={"file": (io.BytesIO(b"GIF89a"), "a.gif", "image/gif")},
        )
        assert (res.status_code, _body(res)["code"]) == (422, 9001)

    def test_missing_file_9001(
        self, upload_app, db_create_all, user_factory, make_auth_header
    ):
        client = upload_app.test_client()
        user = user_factory()
        res = client.post(AVATAR_URL, headers=make_auth_header(user["id"]), data={})
        assert (res.status_code, _body(res)["code"]) == (422, 9001)

    def test_requires_login(self, upload_app, db_create_all):
        client = upload_app.test_client()
        res = client.post(
            AVATAR_URL, data={"file": (io.BytesIO(PNG_1PX), "a.png", "image/png")}
        )
        assert (res.status_code, _body(res)["code"]) == (401, 1001)
