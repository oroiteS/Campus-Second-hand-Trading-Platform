"""认证域路由（tag: auth）：注册 / 登录 / 登出 / 密码重置。

只做：解析/校验请求（含 client_ip 提取）→ 调 service → 组装 envelope；
业务规则、字段独立复验与事务全部在 service。
"""

import time

from flask import Blueprint, request
from flask_jwt_extended import get_jwt

from src.common import responses
from src.common.auth import IMG_COOKIE, IMG_COOKIE_PATH, login_required
from src.common.errors import ApiError, ErrorCode
from src.services import auth_service

bp = Blueprint("auth", __name__)


def _json_payload() -> dict:
    """解析 JSON 请求体；缺失或非对象统一 9001。"""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            data={"fields": {"body": "请求体必须为 JSON 对象"}},
        )
    return payload


@bp.post("/register")
def register():
    """POST /api/auth/register —— 公开；成功返回 UserProfile，不签发令牌。"""
    user = auth_service.register(_json_payload())
    return responses.success(user.to_profile_dict())


@bp.post("/login")
def login():
    """POST /api/auth/login —— 公开；account 先按用户名后按学号匹配。"""
    payload = _json_payload()
    fields: dict[str, str] = {}
    account = payload.get("account")
    if not isinstance(account, str) or not 1 <= len(account) <= 32:
        fields["account"] = "账号（用户名或学号）长度须为 1–32 字符"
    password = payload.get("password")
    if not isinstance(password, str) or not password:
        fields["password"] = "密码必填"
    if fields:
        raise ApiError(ErrorCode.VALIDATION_ERROR, data={"fields": fields})
    # 测试客户端与直连场景 remote_addr 均可用；反代部署时由前置写入
    client_ip = request.remote_addr or "unknown"
    user, token, expires_in = auth_service.login(account, password, client_ip)
    body, _status = responses.success(
        {
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": expires_in,
            "user": user.to_profile_dict(),
        }
    )
    # 图片 Cookie 通道（契约 0.3.0）：值为同一 JWT，TTL 同令牌；
    # httpOnly + SameSite=Lax + Path=/api/images 四属性齐全
    body.set_cookie(
        IMG_COOKIE,
        token,
        max_age=expires_in,
        httponly=True,
        samesite="Lax",
        path=IMG_COOKIE_PATH,
    )
    return body


@bp.post("/logout")
@login_required
def logout():
    """POST /api/auth/logout —— 需登录；jti 入黑名单，Redis 故障降级可见。"""
    claims = get_jwt()
    remaining_seconds = int(claims["exp"] - time.time())
    body, _status = responses.success(
        auth_service.logout(claims["jti"], remaining_seconds)
    )
    # 登出清除图片 Cookie（与 login 种下的同 path）
    body.delete_cookie(IMG_COOKIE, path=IMG_COOKIE_PATH)
    return body


@bp.post("/password/reset")
def reset_password():
    """POST /api/auth/password/reset —— 公开；data 固定 null。"""
    auth_service.reset_password(_json_payload())
    return responses.success(None)
