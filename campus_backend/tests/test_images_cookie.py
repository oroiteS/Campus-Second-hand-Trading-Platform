"""图片 Cookie 通道测试（契约 0.3.0：login 种 / images 双通道 / logout 清 / 仅图片路由接受）。

复用 b1 造数（user_factory / make_auth_header / upload_app），登录走真实
POST /api/auth/login 拿到 Set-Cookie；Flask 测试客户端自带 Cookie jar。
"""

import io

from werkzeug.datastructures import FileStorage

from src.common import uploads
from src.model import db
from tests.conftest import DEFAULT_PASSWORD, PNG_1PX

LOGIN_URL = "/api/auth/login"


def _create_image(app, owner_id: int, purpose: str = "avatar") -> int:
    fs = FileStorage(stream=io.BytesIO(PNG_1PX), filename="x.png", content_type="image/png")
    with app.app_context():
        image = uploads.validate_and_save(fs, purpose)
        image.owner_id = owner_id
        db.session.add(image)
        db.session.commit()
        return image.id


def _login(client, username: str, password: str = DEFAULT_PASSWORD):
    return client.post(
        LOGIN_URL, json={"account": username, "password": password}
    )


class TestLoginSetCookie:
    def test_login_sets_img_token_cookie_with_all_attributes(
        self, upload_app, db_create_all, user_factory
    ):
        """login 200 → Set-Cookie img_token：HttpOnly / SameSite=Lax /
        Path=/api/images / Max-Age=expires_in，值与 access_token 同一 JWT。"""
        user = user_factory()
        res = _login(upload_app.test_client(), user["username"])
        assert res.status_code == 200
        set_cookie = res.headers.get("Set-Cookie", "")
        assert "img_token=" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "SameSite=Lax" in set_cookie
        assert "Path=/api/images" in set_cookie
        expires_in = res.get_json()["data"]["expires_in"]
        assert f"Max-Age={expires_in}" in set_cookie

    def test_cookie_value_equals_access_token(
        self, upload_app, db_create_all, user_factory
    ):
        """Cookie 值 = 同一 JWT（非另签令牌）。"""
        user = user_factory()
        res = _login(upload_app.test_client(), user["username"])
        token = res.get_json()["data"]["access_token"]
        cookie_header = next(
            v for k, v in res.headers.items() if k == "Set-Cookie" and "img_token" in v
        )
        assert f"img_token={token}" in cookie_header


class TestImagesDualChannel:
    def test_cookie_only_access_image_200(self, upload_app, db_create_all, user_factory):
        """无 Bearer 头、仅 Cookie → GET /api/images/{id} 200（b1 缺陷修复主场景：
        <img> 标签直载）。"""
        client = upload_app.test_client()
        user = user_factory()
        image_id = _create_image(upload_app, user["id"])
        res = _login(client, user["username"])
        assert res.status_code == 200
        res = client.get(f"/api/images/{image_id}")  # 不带 Authorization
        assert res.status_code == 200
        assert res.data == PNG_1PX

    def test_blacklisted_cookie_token_401_1003(
        self, upload_app, db_create_all, user_factory
    ):
        """Cookie 值为已注销令牌（jti 黑名单）→ 401/1003（同一黑名单路径）。"""
        client = upload_app.test_client()
        user = user_factory()
        res = _login(client, user["username"])
        token = res.get_json()["data"]["access_token"]
        # 注销该令牌（黑名单入库；再手动回种 Cookie 模拟旧页面残留）
        out = client.post(
            "/api/auth/logout", headers={"Authorization": f"Bearer {token}"}
        )
        assert out.status_code == 200
        client.set_cookie("img_token", token, path="/api/images")
        image_id = _create_image(upload_app, user["id"])
        res = client.get(f"/api/images/{image_id}")
        assert res.status_code == 401
        assert res.get_json()["code"] == 1003

    def test_bearer_takes_priority_over_cookie(
        self, upload_app, db_create_all, user_factory
    ):
        """双通道并存时 Bearer 头优先：头有效 + Cookie 无效 → 仍 200。"""
        client = upload_app.test_client()  # 未登录，jar 干净
        user = user_factory()
        image_id = _create_image(upload_app, user["id"])
        res = _login(upload_app.test_client(), user["username"])
        token = res.get_json()["data"]["access_token"]
        # jar 种入无效 Cookie（显式 Cookie 头 werkzeug 测试客户端不解析，
        # 必须经 jar 传递），请求显式带有效 Bearer → 应按头鉴权成功
        client.set_cookie("img_token", "not-a-valid-jwt", path="/api/images")
        res = client.get(
            f"/api/images/{image_id}", headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 200

    def test_logout_clears_cookie(self, upload_app, db_create_all, user_factory):
        """logout 响应清除 img_token（同 path），客户端 jar 不再携带。"""
        client = upload_app.test_client()
        user = user_factory()
        res = _login(client, user["username"])
        token = res.get_json()["data"]["access_token"]
        out = client.post(
            "/api/auth/logout", headers={"Authorization": f"Bearer {token}"}
        )
        assert out.status_code == 200
        set_cookie = out.headers.get("Set-Cookie", "")
        assert "img_token=" in set_cookie
        assert 'Max-Age=0' in set_cookie or '1970' in set_cookie
        # jar 已清：后续请求无任何凭据 → 401/1001
        image_id = _create_image(upload_app, user["id"])
        res = client.get(f"/api/images/{image_id}")
        assert res.status_code == 401
        assert res.get_json()["code"] == 1001


class TestCookieChannelOnlyForImages:
    def test_non_image_route_rejects_cookie_auth(self, upload_app, db_create_all, user_factory):
        """仅图片路由接受 Cookie：非图片路由（如 GET /api/schools 的鉴权场景）
        带 Cookie 无 Bearer → 401/1001，不回退 Cookie。"""
        client = upload_app.test_client()
        user = user_factory()
        _login(client, user["username"])
        # /api/auth/logout 需登录：仅带 Cookie（无 Bearer）应 401
        res = client.post("/api/auth/logout")
        assert res.status_code == 401
        assert res.get_json()["code"] == 1001
