"""images 域测试：本人头像可读、学生证越权 404、管理员可读、未登录 401。"""

import io
import pathlib

from werkzeug.datastructures import FileStorage

from src.common import uploads
from src.model import Image, db
from tests.conftest import PNG_1PX

IMAGE_URL = "/api/images/{id}"


def _create_image(app, owner_id: int, purpose: str, data: bytes = PNG_1PX) -> int:
    """造图：四件套落盘 + images 落库，返回图片 id。"""
    fs = FileStorage(stream=io.BytesIO(data), filename="x.png", content_type="image/png")
    with app.app_context():
        image = uploads.validate_and_save(fs, purpose)
        image.owner_id = owner_id
        db.session.add(image)
        db.session.commit()
        return image.id


def _body(res):
    return res.get_json()


class TestImageAccess:
    def test_own_avatar_readable(
        self, upload_app, db_create_all, user_factory, make_auth_header
    ):
        client = upload_app.test_client()
        user = user_factory()
        image_id = _create_image(upload_app, user["id"], "avatar")
        res = client.get(IMAGE_URL.format(id=image_id), headers=make_auth_header(user["id"]))
        assert res.status_code == 200
        assert res.data == PNG_1PX  # 实体二进制，非 envelope
        assert res.content_type == "image/png"

    def test_other_users_avatar_readable_after_login(
        self, upload_app, db_create_all, user_factory, make_auth_header
    ):
        """avatar 用途登录即可读（不限于本人）。"""
        client = upload_app.test_client()
        owner = user_factory()
        viewer = user_factory()
        image_id = _create_image(upload_app, owner["id"], "avatar")
        res = client.get(IMAGE_URL.format(id=image_id), headers=make_auth_header(viewer["id"]))
        assert res.status_code == 200

    def test_others_student_card_404_9002(
        self, upload_app, db_create_all, user_factory, make_auth_header
    ):
        """他人学生证越权 → 404/9002（与不存在同语义，防探测）。"""
        client = upload_app.test_client()
        owner = user_factory()
        stranger = user_factory()
        image_id = _create_image(upload_app, owner["id"], "student_card")
        res = client.get(
            IMAGE_URL.format(id=image_id), headers=make_auth_header(stranger["id"])
        )
        assert (res.status_code, _body(res)["code"]) == (404, 9002)

    def test_owner_reads_own_student_card(
        self, upload_app, db_create_all, user_factory, make_auth_header
    ):
        client = upload_app.test_client()
        owner = user_factory()
        image_id = _create_image(upload_app, owner["id"], "student_card")
        res = client.get(IMAGE_URL.format(id=image_id), headers=make_auth_header(owner["id"]))
        assert res.status_code == 200
        assert res.data == PNG_1PX

    def test_admin_reads_student_card(
        self, upload_app, db_create_all, user_factory, make_auth_header
    ):
        client = upload_app.test_client()
        owner = user_factory()
        admin = user_factory(role="admin")
        image_id = _create_image(upload_app, owner["id"], "student_card")
        res = client.get(IMAGE_URL.format(id=image_id), headers=make_auth_header(admin["id"]))
        assert res.status_code == 200
        assert res.data == PNG_1PX

    def test_requires_login(self, upload_app, db_create_all, user_factory):
        client = upload_app.test_client()
        user = user_factory()
        image_id = _create_image(upload_app, user["id"], "avatar")
        res = client.get(IMAGE_URL.format(id=image_id))
        assert (res.status_code, _body(res)["code"]) == (401, 1001)

    def test_nonexistent_image_404_9002(
        self, upload_app, db_create_all, user_factory, make_auth_header
    ):
        client = upload_app.test_client()
        user = user_factory()
        res = client.get(IMAGE_URL.format(id=424242), headers=make_auth_header(user["id"]))
        assert (res.status_code, _body(res)["code"]) == (404, 9002)

    def test_missing_file_on_disk_404_9002(
        self, upload_app, db_create_all, user_factory, make_auth_header
    ):
        """库中有记录但文件缺失（磁盘被清）：同 404/9002，不泄露细节。"""
        client = upload_app.test_client()
        user = user_factory()
        image_id = _create_image(upload_app, user["id"], "avatar")
        with upload_app.app_context():
            image = db.session.get(Image, image_id)
            pathlib.Path(upload_app.config["UPLOAD_DIR"], image.path).unlink()
        res = client.get(IMAGE_URL.format(id=image_id), headers=make_auth_header(user["id"]))
        assert (res.status_code, _body(res)["code"]) == (404, 9002)
