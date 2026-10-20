"""common 公共件测试：错误码表、分页解析、统一响应封装、表名前缀助手。"""

import pytest

from src.common.errors import ApiError, ErrorCode
from src.common.pagination import parse_pagination
from src.common.responses import failure, success
from src.model import prefix


class TestErrorCodeTable:
    """错误码表与契约 0.1.0 已定义的 10xx / 90xx 段逐条对齐。"""

    @pytest.mark.parametrize(
        ("member", "code", "http_status"),
        [
            ("TOKEN_INVALID", 1001, 401),
            ("TOKEN_EXPIRED", 1002, 401),
            ("TOKEN_REVOKED", 1003, 401),
            ("CAMPUS_VERIFICATION_REQUIRED", 1004, 403),
            ("ADMIN_REQUIRED", 1005, 403),
            ("LOGIN_RATE_LIMITED", 1006, 429),
            ("VALIDATION_ERROR", 9001, 422),
            ("NOT_FOUND", 9002, 404),
            ("CONFLICT", 9003, 409),
            ("DEPENDENCY_UNAVAILABLE", 9004, 503),
            ("INTERNAL_ERROR", 9005, 500),
            ("RATE_LIMITED", 9006, 429),
        ],
    )
    def test_contract_codes(self, member: str, code: int, http_status: int):
        item = ErrorCode[member]
        assert item.code == code
        assert item.http_status == http_status
        assert item.message  # 默认中文文案非空


class TestParsePagination:
    def test_defaults(self):
        paged = parse_pagination({})
        assert (paged.page, paged.page_size) == (1, 20)
        assert paged.offset == 0

    def test_valid_values(self):
        paged = parse_pagination({"page": "3", "page_size": "50"})
        assert (paged.page, paged.page_size) == (3, 50)
        assert paged.offset == 100

    def test_page_size_upper_bound(self):
        assert parse_pagination({"page_size": "100"}).page_size == 100

    @pytest.mark.parametrize(
        ("query", "field"),
        [
            ({"page": "0"}, "page"),
            ({"page": "-1"}, "page"),
            ({"page": "abc"}, "page"),
            ({"page_size": "0"}, "page_size"),
            ({"page_size": "101"}, "page_size"),
            ({"page_size": "1.5"}, "page_size"),
        ],
    )
    def test_invalid_raises_9001_with_field_errors(self, query, field):
        with pytest.raises(ApiError) as exc_info:
            parse_pagination(query)
        err = exc_info.value
        assert err.error is ErrorCode.VALIDATION_ERROR
        assert err.http_status == 422
        assert field in err.data["fields"]


class TestEnvelopeHelpers:
    def test_success_shape(self, app):
        with app.app_context():
            resp, status = success({"k": 1})
        assert status == 200
        assert resp.get_json() == {"code": 0, "message": "ok", "data": {"k": 1}}

    def test_failure_uses_table_defaults(self, app):
        with app.app_context():
            resp, status = failure(ErrorCode.NOT_FOUND)
        assert status == 404
        body = resp.get_json()
        assert body["code"] == 9002
        assert body["message"] == ErrorCode.NOT_FOUND.message
        assert body["data"] is None


class TestTablePrefix:
    def test_prefix_uses_env(self, monkeypatch):
        monkeypatch.setenv("DB_TABLE_PREFIX", "b0be-")
        assert prefix("users") == "b0be-users"
        monkeypatch.setenv("DB_TABLE_PREFIX", "")
        assert prefix("users") == "users"
