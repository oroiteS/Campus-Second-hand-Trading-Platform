"""统一响应封装：成功 / 失败 helper，输出契约 ``{code, message, data}`` envelope。"""

from typing import Any

from flask import jsonify

from src.common.errors import ErrorCode

SUCCESS_CODE = 0
SUCCESS_MESSAGE = "ok"


def success(data: Any = None, *, message: str = SUCCESS_MESSAGE, status: int = 200):
    """成功响应：``{"code": 0, "message": "ok", "data": ...}``。"""
    payload = {"code": SUCCESS_CODE, "message": message, "data": data}
    return jsonify(payload), status


def failure(
    error: ErrorCode,
    *,
    message: str | None = None,
    data: Any = None,
    status: int | None = None,
):
    """失败响应：``{"code": 业务码, "message": ..., "data": ...}``。

    HTTP 状态码与契约错误码表对齐；``message`` / ``data`` / ``status``
    缺省取错误码表默认值。
    """
    payload = {"code": error.code, "message": message or error.message, "data": data}
    return jsonify(payload), status or error.http_status
