"""JWT 鉴权三装饰器、同校作用域注入、scoped_key 与 jti 黑名单挂钩。

权限判定一律查库实时状态（``g.current_user`` 恒为当前请求内查库所得），
令牌 claims 不做判权依据。Redis 键一律经 ``scoped_key()`` 生成；Redis
故障按降级决策 fail-open（放行 + 告警日志）。本模块是横切件：只被
router / routes / services 引用，不反向依赖它们。
"""

from collections.abc import Callable
from functools import wraps
from typing import TYPE_CHECKING

from flask import current_app, g
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from src.common import redis_client
from src.common.errors import ApiError, ErrorCode
from src.model import User, db

if TYPE_CHECKING:
    from flask_jwt_extended import JWTManager


def scoped_key(namespace: str, *parts: object) -> str:
    """生成统一命名空间的 Redis 键（冒号连接）。

    本批次限流与黑名单键：``scoped_key("rate:login", ip)`` /
    ``scoped_key("auth:blacklist", jti)``；批次 2 起商品域的键在 parts
    前置 ``g.school_id``，保持"缓存键含 school_id"的隔离约定。
    """
    return ":".join([namespace, *(str(part) for part in parts)])


def _load_current_user() -> User:
    """按 JWT identity 查库并挂 ``g.current_user``（inject_scope 已查则复用）。"""
    cached = getattr(g, "current_user", None)
    if cached is not None:
        return cached
    identity = get_jwt_identity()
    user = db.session.get(User, int(identity)) if identity else None
    if user is None:
        raise ApiError(ErrorCode.TOKEN_INVALID)
    g.current_user = user
    return user


def login_required(view: Callable) -> Callable:
    """JWT 有效（未过期/未注销/签名正确）且用户存在 → ``g.current_user``。"""

    @wraps(view)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        _load_current_user()
        return view(*args, **kwargs)

    return wrapper


def verified_required(view: Callable) -> Callable:
    """已通过校园认证的学生，或管理员；未认证学生 403/1004。"""

    @wraps(view)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        user = _load_current_user()
        is_verified_student = (
            user.role == "student" and user.auth_status == "approved"
        )
        if user.role == "admin" or is_verified_student:
            return view(*args, **kwargs)
        raise ApiError(ErrorCode.CAMPUS_VERIFICATION_REQUIRED)

    return wrapper


def admin_required(view: Callable) -> Callable:
    """仅管理员；角色不符 403/1005（游客与失效令牌由登录校验先拦 401）。"""

    @wraps(view)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        user = _load_current_user()
        if user.role != "admin":
            raise ApiError(ErrorCode.ADMIN_REQUIRED)
        return view(*args, **kwargs)

    return wrapper


def inject_scope() -> None:
    """每请求进入即注入同校作用域上下文（app.before_request 注册）。

    - 学生：``g.school_id = user.school_id``（未认证为 None）；
    - 管理员：``g.scope_all = True``（跨校可见）；
    - 匿名/令牌失效：按匿名作用域放行，不在此抛错——公开接口带着失效
      令牌也必须可访问，受保护接口随后由装饰器给出 401 envelope。
    """
    g.current_user = None
    g.school_id = None
    g.scope_all = False
    try:
        verify_jwt_in_request(optional=True)
    except Exception:  # noqa: BLE001 - 任何令牌错误都降级为匿名作用域
        return
    identity = get_jwt_identity()
    if not identity:
        return
    user = db.session.get(User, int(identity))
    if user is None:
        return
    g.current_user = user
    if user.role == "admin":
        g.scope_all = True
    else:
        g.school_id = user.school_id


def register_jwt_hooks(jwt: "JWTManager") -> None:
    """注册 jti 黑名单检查：命中即 401/1003；Redis 故障 fail-open 放行。"""

    @jwt.token_in_blocklist_loader
    def _is_token_revoked(_jwt_header, jwt_payload) -> bool:
        jti = jwt_payload["jti"]
        try:
            # 经模块属性调用（便于测试替换 get_redis 桩）
            return bool(redis_client.get_redis().exists(scoped_key("auth:blacklist", jti)))
        except Exception as exc:  # noqa: BLE001 - 降级决策：可用性优先
            current_app.logger.warning(
                "Redis 黑名单查询失败，fail-open 放行 jti=%s: %s", jti, exc
            )
            return False
