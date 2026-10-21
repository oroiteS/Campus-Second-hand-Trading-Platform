"""certification 域测试：提交（多/单校区）、表单反例、状态闸门、历史与重提。"""

import io
from pathlib import Path

from src.model import AuthApplication, Image
from tests.conftest import PNG_1PX

SUBMIT_URL = "/api/certification/applications"
MINE_URL = "/api/certification/applications/mine"


def _form(school_id, campus_id=None, real_name="张三", student_no="2024010101"):
    form = {"school_id": str(school_id), "real_name": real_name, "student_no": student_no}
    if campus_id is not None:
        form["campus_id"] = str(campus_id)
    return form


def _submit(client, headers, form, file=None):
    data = dict(form)
    if file is not False:
        data["file"] = (
            file if file is not None else (io.BytesIO(PNG_1PX), "card.png", "image/png")
        )
    return client.post(SUBMIT_URL, headers=headers, data=data)


def _body(res):
    return res.get_json()


class TestSubmit:
    def test_multi_campus_with_campus_success(
        self, upload_app, db_create_all, user_factory, school_fixtures, make_auth_header
    ):
        client = upload_app.test_client()
        user = user_factory(username="zhangsan01", student_no="2024010101")
        res = _submit(
            client,
            make_auth_header(user["id"]),
            _form(school_fixtures.multi.id, school_fixtures.east.id),
        )
        assert res.status_code == 200
        data = _body(res)["data"]
        assert data["status"] == "pending"
        assert data["school"]["id"] == school_fixtures.multi.id
        assert data["campus"]["id"] == school_fixtures.east.id
        assert data["student_no"] == "2024010101"
        assert data["real_name"] == "张三"
        assert data["reject_reason"] is None and data["reviewed_at"] is None
        assert data["student_card"]["url"].startswith("/api/images/")
        # 同一事务：用户状态 pending、图片落库、文件按哈希落盘
        with client.application.app_context():
            from src.model import User, db

            assert db.session.get(User, user["id"]).auth_status == "pending"
            image = db.session.get(Image, data["student_card"]["id"])
            assert image.purpose == "student_card"
            assert image.owner_id == user["id"]
            path = Path(upload_app.config["UPLOAD_DIR"]) / image.path
            assert path.exists() and path.name.endswith(".png")

    def test_single_campus_without_campus_success(
        self, upload_app, db_create_all, user_factory, school_fixtures, make_auth_header
    ):
        client = upload_app.test_client()
        user = user_factory()
        res = _submit(
            client,
            make_auth_header(user["id"]),
            _form(school_fixtures.single.id, None, student_no=user["student_no"]),
        )
        assert res.status_code == 200
        assert _body(res)["data"]["campus"] is None

    def test_multi_campus_missing_campus_9001(
        self, upload_app, db_create_all, user_factory, school_fixtures, make_auth_header
    ):
        client = upload_app.test_client()
        user = user_factory()
        res = _submit(
            client,
            make_auth_header(user["id"]),
            _form(school_fixtures.multi.id, None, student_no=user["student_no"]),
        )
        assert res.status_code == 422
        assert _body(res)["code"] == 9001
        assert "campus_id" in _body(res)["data"]["fields"]

    def test_campus_of_other_school_9001(
        self, upload_app, db_create_all, user_factory, school_fixtures, make_auth_header
    ):
        client = upload_app.test_client()
        user = user_factory()
        res = _submit(
            client,
            make_auth_header(user["id"]),
            _form(
                school_fixtures.multi.id,
                school_fixtures.main_campus.id,
                student_no=user["student_no"],
            ),
        )
        assert _body(res)["code"] == 9001
        assert "campus_id" in _body(res)["data"]["fields"]

    def test_single_campus_with_campus_provided_9001(
        self, upload_app, db_create_all, user_factory, school_fixtures, make_auth_header
    ):
        """单校区学校必须省略 campus_id。"""
        client = upload_app.test_client()
        user = user_factory()
        res = _submit(
            client,
            make_auth_header(user["id"]),
            _form(
                school_fixtures.single.id,
                school_fixtures.main_campus.id,
                student_no=user["student_no"],
            ),
        )
        assert _body(res)["code"] == 9001
        assert "campus_id" in _body(res)["data"]["fields"]

    def test_student_no_mismatch_9001(
        self, upload_app, db_create_all, user_factory, school_fixtures, make_auth_header
    ):
        client = upload_app.test_client()
        user = user_factory()
        res = _submit(
            client,
            make_auth_header(user["id"]),
            _form(school_fixtures.single.id, None, student_no="9999999999"),
        )
        assert _body(res)["code"] == 9001
        assert "student_no" in _body(res)["data"]["fields"]

    def test_disabled_school_9001(
        self, upload_app, db_create_all, user_factory, school_fixtures, make_auth_header
    ):
        client = upload_app.test_client()
        user = user_factory()
        res = _submit(
            client,
            make_auth_header(user["id"]),
            _form(school_fixtures.disabled.id, None, student_no=user["student_no"]),
        )
        assert _body(res)["code"] == 9001
        assert "school_id" in _body(res)["data"]["fields"]

    def test_nonexistent_school_9001(
        self, upload_app, db_create_all, user_factory, make_auth_header
    ):
        client = upload_app.test_client()
        user = user_factory()
        res = _submit(
            client,
            make_auth_header(user["id"]),
            _form(99999, None, student_no=user["student_no"]),
        )
        assert _body(res)["code"] == 9001
        assert "school_id" in _body(res)["data"]["fields"]

    def test_bad_file_9001(
        self, upload_app, db_create_all, user_factory, school_fixtures, make_auth_header
    ):
        client = upload_app.test_client()
        user = user_factory()
        res = _submit(
            client,
            make_auth_header(user["id"]),
            _form(school_fixtures.single.id, None, student_no=user["student_no"]),
            file=(io.BytesIO(b"plain text"), "card.txt", "text/plain"),
        )
        assert _body(res)["code"] == 9001
        assert "file" in _body(res)["data"]["fields"]

    def test_requires_login(self, upload_app, db_create_all, school_fixtures):
        client = upload_app.test_client()
        res = _submit(client, {}, _form(school_fixtures.single.id))
        assert (res.status_code, _body(res)["code"]) == (401, 1001)


class TestStatusGate:
    def test_pending_resubmit_9003(
        self, upload_app, db_create_all, user_factory, school_fixtures, make_auth_header
    ):
        client = upload_app.test_client()
        user = user_factory()
        headers = make_auth_header(user["id"])
        form = _form(school_fixtures.single.id, None, student_no=user["student_no"])
        assert _submit(client, headers, form).status_code == 200
        res = _submit(client, headers, form)
        assert (res.status_code, _body(res)["code"]) == (409, 9003)

    def test_approved_resubmit_9003(
        self, upload_app, db_create_all, approved_user, school_fixtures, make_auth_header
    ):
        client = upload_app.test_client()
        res = _submit(
            client,
            make_auth_header(approved_user["id"]),
            _form(school_fixtures.single.id, None, student_no=approved_user["student_no"]),
        )
        assert (res.status_code, _body(res)["code"]) == (409, 9003)

    def test_admin_submit_9003_with_message(
        self, upload_app, db_create_all, user_factory, school_fixtures, make_auth_header
    ):
        client = upload_app.test_client()
        admin = user_factory(role="admin")
        res = _submit(
            client,
            make_auth_header(admin["id"]),
            _form(school_fixtures.single.id, None, student_no=admin["student_no"]),
        )
        assert (res.status_code, _body(res)["code"]) == (409, 9003)
        assert "管理员" in _body(res)["message"]


class TestHistoryAndResubmit:
    def test_rejected_resubmit_keeps_history(
        self, upload_app, db_create_all, user_factory, school_fixtures, make_auth_header
    ):
        client = upload_app.test_client()
        user = user_factory(auth_status="rejected")
        headers = make_auth_header(user["id"])
        # 造一条历史 rejected 申请（含驳回原因）
        with client.application.app_context():
            from src.model import User, db

            image = Image(
                owner_id=user["id"],
                path="student_card/2026-09/old.png",
                mime="image/png",
                size_bytes=1,
                sha256="old",
                purpose="student_card",
            )
            old = AuthApplication(
                user_id=user["id"],
                school_id=school_fixtures.single.id,
                student_no=user["student_no"],
                real_name="张三",
                status="rejected",
                reject_reason="学生证照片模糊",
            )
            old.student_card = image
            db.session.add(image)
            db.session.add(old)
            db.session.commit()
            old_id = old.id

        # rejected 可重提
        res = _submit(
            client,
            headers,
            _form(school_fixtures.single.id, None, student_no=user["student_no"]),
        )
        assert res.status_code == 200
        assert _body(res)["data"]["status"] == "pending"

        # 历史保留且倒序：新 pending 在前，旧 rejected（含驳回原因）在后
        mine = client.get(MINE_URL, headers=headers)
        data = _body(mine)["data"]
        assert [item["status"] for item in data] == ["pending", "rejected"]
        assert data[1]["id"] == old_id
        assert data[1]["reject_reason"] == "学生证照片模糊"
        with client.application.app_context():
            from src.model import User, db

            assert db.session.get(User, user["id"]).auth_status == "pending"

    def test_mine_requires_login(self, upload_app, db_create_all):
        client = upload_app.test_client()
        res = client.get(MINE_URL)
        assert (res.status_code, _body(res)["code"]) == (401, 1001)

    def test_mine_empty_list(self, upload_app, db_create_all, user_factory, make_auth_header):
        client = upload_app.test_client()
        user = user_factory()
        res = client.get(MINE_URL, headers=make_auth_header(user["id"]))
        assert _body(res)["data"] == []
