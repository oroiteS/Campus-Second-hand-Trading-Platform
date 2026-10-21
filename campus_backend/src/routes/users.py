"""用户域路由（tag: users）：个人资料 / 密码修改 / 头像上传。

只做：解析/校验请求 → 调 service → 组装 envelope；字段独立复验与
事务全部在 service（本层不写 db.session）。
"""

from flask import Blueprint, g, request

from src.common import responses
from src.common.auth import login_required
from src.common.errors import ApiError, ErrorCode
from src.services import user_service

bp = Blueprint("users", __name__)


def _json_payload() -> dict:
    """解析 JSON 请求体；缺失或非对象统一 9001。"""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            data={"fields": {"body": "请求体必须为 JSON 对象"}},
        )
    return payload


@bp.get("/me")
@login_required
def get_me():
    """GET /api/users/me —— 当前登录用户完整资料。"""
    user = user_service.get_profile(g.current_user.id)
    return responses.success(user.to_profile_dict())


@bp.put("/me")
@login_required
def update_me():
    """PUT /api/users/me —— 仅更新请求体中出现的字段。"""
    user = user_service.update_profile(g.current_user, request.get_json(silent=True))
    return responses.success(user.to_profile_dict())


@bp.put("/me/password")
@login_required
def change_password():
    """PUT /api/users/me/password —— 校验原密码后设置新密码。"""
    payload = _json_payload()
    user_service.change_password(
        g.current_user, payload.get("old_password"), payload.get("new_password")
    )
    return responses.success(None)


@bp.post("/me/avatar")
@login_required
def upload_avatar():
    """POST /api/users/me/avatar —— multipart 头像上传，返回最新资料。"""
    user = user_service.update_avatar(g.current_user, request.files.get("file"))
    return responses.success(user.to_profile_dict())
