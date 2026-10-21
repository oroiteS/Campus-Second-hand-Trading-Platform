"""uploads 上传校验测试：内容魔数嗅探（联调 P2 反例）+ 各校验层正反例。

直接覆盖 helper ``validate_and_save``（avatar 与 certification_service
两个调用方共用，单元级即同时覆盖两条链路），并经 avatar 接口复验联
调复现路径（txt 伪装 .png → 9001）。
"""

import base64
import io

import pytest
from werkzeug.datastructures import FileStorage

from src.common import uploads
from src.common.errors import ApiError
from src.model import Image, db
from tests.conftest import PNG_1PX

AVATAR_URL = "/api/users/me/avatar"

# 1×1 合法 JPEG（SOI=FF D8 FF 开头、EOI=FF D9 结尾）
JPEG_1PX = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRof"
    "Hh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAAB"
    "AAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AVN//2Q=="
)


def _webp_bytes() -> bytes:
    """最小 WEBP（VP8L 无损头）：RIFF 容器 + 8-11 字节 WEBP 标记。"""
    return b"RIFF" + (18).to_bytes(4, "little") + b"WEBP" + b"VP8L" + b"\x00" * 8


def _fs(data: bytes, name: str, mime: str) -> FileStorage:
    return FileStorage(stream=io.BytesIO(data), filename=name, content_type=mime)


def _avatar_post(upload_app, headers, data):
    return upload_app.test_client().post(AVATAR_URL, headers=headers, data=data)


def _assert_9001_file(res, body):
    assert res.status_code == 422
    assert body["code"] == 9001
    assert "file" in body["data"]["fields"]


class TestMagicSniffingUnit:
    """helper 单元级：魔数与扩展名族一一对应，不匹配即 9001。"""

    def _save(self, upload_app, data, name, mime):
        with upload_app.app_context():
            return uploads.validate_and_save(_fs(data, name, mime), "avatar")

    @pytest.mark.parametrize(
        ("data", "name", "mime"),
        [
            (b"hello world, plain text", "f.png", "image/png"),  # 联调复现载荷
            (b"hello world, plain text", "f.jpg", "image/jpeg"),
            (b"hello world, plain text", "f.webp", "image/webp"),
            (PNG_1PX, "f.jpg", "image/jpeg"),  # PNG 内容改名 jpg：族不一致
            (JPEG_1PX, "f.png", "image/png"),  # JPEG 内容改名 png：族不一致
            (b"", "f.png", "image/png"),  # 空文件无法通过魔数
            (b"\x89PNG", "f.png", "image/png"),  # 截断的 PNG 签名
            (b"GIF89a", "f.png", "image/png"),  # 其他魔数冒充
        ],
        ids=[
            "txt伪装png", "txt伪装jpg", "txt伪装webp",
            "png内容改名jpg", "jpg内容改名png", "空文件", "截断PNG签名", "GIF魔数冒充png",
        ],
    )
    def test_content_mismatch_rejected_9001(
        self, upload_app, db_create_all, data, name, mime
    ):
        with pytest.raises(ApiError) as exc_info:
            self._save(upload_app, data, name, mime)
        err = exc_info.value
        assert err.error.code == 9001
        assert err.http_status == 422
        assert "file" in err.data["fields"]

    @pytest.mark.parametrize(
        ("data", "name", "mime"),
        [
            (PNG_1PX, "a.png", "image/png"),
            (JPEG_1PX, "a.jpg", "image/jpeg"),
            (_webp_bytes(), "a.webp", "image/webp"),
        ],
        ids=["png", "jpg", "webp"],
    )
    def test_real_magic_still_saves(
        self, upload_app, db_create_all, data, name, mime
    ):
        """真实魔数不误杀：三个扩展名族均正常落盘。"""
        image = self._save(upload_app, data, name, mime)
        assert isinstance(image, Image)
        assert image.mime == mime
        assert image.path.endswith(f".{name.rsplit('.', 1)[-1]}")


class TestMagicSniffingApi:
    """接口级：联调复现路径经 POST /api/users/me/avatar 复验。"""

    def test_txt_disguised_as_png_rejected_9001(
        self, upload_app, db_create_all, user_factory, make_auth_header
    ):
        """联调复现：printf 'text' > f.png && curl -F file=@f.png → 9001。"""
        user = user_factory()
        res = _avatar_post(
            upload_app,
            make_auth_header(user["id"]),
            {"file": (io.BytesIO(b"text"), "f.png", "image/png")},
        )
        _assert_9001_file(res, res.get_json())

    def test_txt_disguised_as_jpg_rejected_9001(
        self, upload_app, db_create_all, user_factory, make_auth_header
    ):
        user = user_factory()
        res = _avatar_post(
            upload_app,
            make_auth_header(user["id"]),
            {"file": (io.BytesIO(b"text"), "f.jpg", "image/jpeg")},
        )
        _assert_9001_file(res, res.get_json())

    def test_png_content_renamed_jpg_rejected_9001(
        self, upload_app, db_create_all, user_factory, make_auth_header
    ):
        """PNG 内容经 .jpg 上传：魔数与扩展名族不一致 → 9001。"""
        user = user_factory()
        res = _avatar_post(
            upload_app,
            make_auth_header(user["id"]),
            {"file": (io.BytesIO(PNG_1PX), "f.jpg", "image/jpeg")},
        )
        _assert_9001_file(res, res.get_json())

    def test_real_png_still_200(self, upload_app, db_create_all, user_factory, make_auth_header):
        """防误杀：合法最小 PNG 仍 200，文件按 sha256 落盘。"""
        user = user_factory()
        res = _avatar_post(
            upload_app,
            make_auth_header(user["id"]),
            {"file": (io.BytesIO(PNG_1PX), "me.png", "image/png")},
        )
        assert res.status_code == 200
        assert res.get_json()["data"]["avatar"]["url"].startswith("/api/images/")

    def test_real_jpg_still_200(self, upload_app, db_create_all, user_factory, make_auth_header):
        """防误杀：真实 JPEG 魔数文件经 .jpg 上传仍 200。"""
        user = user_factory()
        res = _avatar_post(
            upload_app,
            make_auth_header(user["id"]),
            {"file": (io.BytesIO(JPEG_1PX), "me.jpg", "image/jpeg")},
        )
        assert res.status_code == 200
        avatar_id = res.get_json()["data"]["avatar"]["id"]
        with upload_app.app_context():
            assert db.session.get(Image, avatar_id).mime == "image/jpeg"
