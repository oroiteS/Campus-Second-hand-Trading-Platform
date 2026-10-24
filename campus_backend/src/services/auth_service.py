"""认证域服务：注册 / 登录 / 登出 / 密码重置（事务边界在本层提交）。

字段规则按批次计划「3.0 字段校验对照表」在 service 独立复验，不信任
客户端；错误码经 ``ApiError`` 抛出。Redis 故障按降级决策 fail-open：
限流放行、黑名单未落时 logout 返回 ``degraded`` 标记，均落告警日志。
"""

import re
from typing import TYPE_CHECKING

from flask import current_app
from sqlalchemy.exc import IntegrityError

from src.common import redis_client, security
from src.common.auth import scoped_key
from src.common.errors import ApiError, ErrorCode
from src.model import User, db
from src.services.degradation import LOGOUT_DEGRADED_REASON

if TYPE_CHECKING:
    from redis import Redis

# 契约「3.0 字段校验对照表」双端同源唯一口径（后端独立复验）
USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")
PASSWORD_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,64}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# 登录限流参数（契约：连续失败 5 次后 10 分钟内 429/1006，成功清零）
LOGIN_FAIL_LIMIT = 5
LOGIN_FAIL_TTL_SECONDS = 600

_RESET_CHANNELS = ("student_no", "email")


# ---- 字段复验 ----


def validate_register(payload: dict) -> dict[str, str]:
    """注册字段独立复验；返回 ``{字段: 原因}``（空 dict 即通过）。"""
    fields: dict[str, str] = {}
    username = payload.get("username")
    if not isinstance(username, str) or not USERNAME_RE.fullmatch(username):
        fields["username"] = "用户名须为 1–32 位、字母开头，仅含字母/数字/下划线"
    password = payload.get("password")
    if not isinstance(password, str) or not PASSWORD_RE.fullmatch(password):
        fields["password"] = "密码长度须为 8–64 位且同时包含字母与数字"
    email = payload.get("email")
    if not isinstance(email, str) or not EMAIL_RE.fullmatch(email):
        fields["email"] = "邮箱格式不正确"
    student_no = payload.get("student_no")
    if not isinstance(student_no, str) or not 1 <= len(student_no) <= 32:
        fields["student_no"] = "学号长度须为 1–32 字符"
    nickname = payload.get("nickname")
    if nickname is not None and (
        not isinstance(nickname, str) or not 1 <= len(nickname) <= 32
    ):
        fields["nickname"] = "昵称长度须为 1–32 字符"
    return fields


def _fields_error(fields: dict[str, str]) -> ApiError:
    return ApiError(ErrorCode.VALIDATION_ERROR, data={"fields": fields})


# ---- 注册 ----


def register(payload: dict) -> User:
    """注册：字段复验 9001 → 唯一性 2001/2002 → bcrypt 落库；不签发令牌。"""
    fields = validate_register(payload)
    if fields:
        raise _fields_error(fields)

    exists = db.session.execute(
        db.select(User).where(
            (User.username == payload["username"]) | (User.student_no == payload["student_no"])
        )
    ).scalar_one_or_none()
    if exists is not None:
        if exists.username == payload["username"]:
            raise ApiError(ErrorCode.USERNAME_TAKEN)
        raise ApiError(ErrorCode.STUDENT_NO_TAKEN)

    nickname = payload.get("nickname") or payload["username"]
    user = User(
        username=payload["username"],
        student_no=payload["student_no"],
        email=payload["email"],
        nickname=nickname,
        display_name=nickname,
        password_hash=security.hash_password(payload["password"]),
        role="student",
        auth_status="unverified",
        status="active",
    )
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError as exc:  # 竞态兜底：唯一约束冲突转 2001/2002 而非 500
        db.session.rollback()
        raise _unique_conflict(exc) from None
    return user


# 唯一冲突识别 token（整词精确匹配，不做子串判断）。约束名不随
# DB_TABLE_PREFIX 参数化（MySQL 索引名仅要求表内唯一，跨表重名合法），
# token 与前缀无关。各方言报文形态（取 ``exc.orig`` 方言原生消息；
# ``str(exc)`` 会拼接 SQL 与参数，其中的列名清单会污染文本匹配）：
# - MySQL 8.0.19+：``Duplicate entry '<值>' for key '<表>.<约束名>'``
#   （worktree 如 ``b1be-users.uk_student_no``）；
# - SQLite：``UNIQUE constraint failed: <表>.<列名>``（无约束名，按列识别）。
# token 前后紧邻 [A-Za-z0-9_-] 即不视为命中，因此值里偶然出现
# ``student_no`` 子串（如 username "a_student_no"）不再误判来源。
_STUDENT_NO_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(?:uk_student_no|student_no)(?![A-Za-z0-9_-])"
)
_USERNAME_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(?:uk_username|username)(?![A-Za-z0-9_-])"
)


def _unique_conflict(exc: IntegrityError) -> ApiError:
    """按唯一约束名/列名整词匹配区分竞态冲突来源（uk_username / uk_student_no）。

    未识别的 IntegrityError 维持既有兜底口径：USERNAME_TAKEN。
    """
    orig = exc.orig
    text = (str(orig) if orig is not None else str(exc)).lower()
    if _STUDENT_NO_TOKEN_RE.search(text):
        return ApiError(ErrorCode.STUDENT_NO_TAKEN)
    if _USERNAME_TOKEN_RE.search(text):
        return ApiError(ErrorCode.USERNAME_TAKEN)
    return ApiError(ErrorCode.USERNAME_TAKEN)  # 未识别：保持原兜底


# ---- 登录 ----


def login(account: str, password: str, client_ip: str) -> tuple[User, str, int]:
    """登录：先按 username 精确匹配、未命中按 student_no。

    失败不区分"用户名不存在/密码错误"（同 2005，防探测）；封禁用户即使
    密码正确也 2006，且按一次失败计入限流；连续失败 5 次 → 429/1006，
    成功清零。Redis 故障时限流降级放行 + 告警日志。
    """
    _check_login_rate(client_ip)
    user = db.session.execute(
        db.select(User).where(User.username == account)
    ).scalar_one_or_none()
    if user is None:
        user = db.session.execute(
            db.select(User).where(User.student_no == account)
        ).scalar_one_or_none()
    if user is None or not security.verify_password(password, user.password_hash):
        _record_login_failure(client_ip)
        raise ApiError(ErrorCode.LOGIN_FAILED)
    if user.status == "banned":
        _record_login_failure(client_ip)
        raise ApiError(ErrorCode.ACCOUNT_BANNED)
    _clear_login_failures(client_ip)
    token, expires_in = security.issue_token(user)
    return user, token, expires_in


def _check_login_rate(client_ip: str) -> None:
    """达到失败阈值即 429/1006；查询故障放行（fail-open）。"""
    key = scoped_key("rate:login", client_ip)
    try:
        count = redis_client.get_redis().get(key)
    except Exception as exc:  # noqa: BLE001 - 降级决策：可用性优先
        current_app.logger.warning("Redis 不可用，登录限流降级放行: %s", exc)
        return
    if count is not None and int(count) >= LOGIN_FAIL_LIMIT:
        raise ApiError(ErrorCode.LOGIN_RATE_LIMITED)


def _record_login_failure(client_ip: str) -> None:
    """失败计数 +1 并刷新 TTL（600s）；计数故障仅告警，不影响失败响应。"""
    key = scoped_key("rate:login", client_ip)
    try:
        client = redis_client.get_redis()
        client.incr(key)
        client.expire(key, LOGIN_FAIL_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning("Redis 不可用，登录失败计数未落: %s", exc)


def _clear_login_failures(client_ip: str) -> None:
    """登录成功清零计数；清零故障仅告警。"""
    try:
        redis_client.get_redis().delete(scoped_key("rate:login", client_ip))
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning("Redis 不可用，登录成功清零未执行: %s", exc)


# ---- 登出 ----


def logout(jti: str, remaining_seconds: int) -> dict:
    """jti 写黑名单至令牌自然过期；Redis 故障返回降级标记（仍 200）。"""
    try:
        client: Redis = redis_client.get_redis()
        client.setex(scoped_key("auth:blacklist", jti), max(int(remaining_seconds), 1), "1")
        return {}
    except Exception as exc:  # noqa: BLE001 - 降级显式可见（契约 logout 200 语义）
        current_app.logger.warning("Redis 不可用，logout 黑名单未落: %s", exc)
        return {"degraded": True, "degraded_reason": LOGOUT_DEGRADED_REASON}


# ---- 密码重置 ----


def reset_password(payload: dict) -> None:
    """用户名 + 学号/邮箱 + 新密码重置（不发邮件短信）。

    凭证不匹配与用户名不存在一律 2004，不泄露用户名存在性（防探测）。
    """
    fields: dict[str, str] = {}
    username = payload.get("username")
    if not isinstance(username, str) or not username:
        fields["username"] = "用户名必填"
    channel = payload.get("reset_channel")
    if channel not in _RESET_CHANNELS:
        fields["reset_channel"] = "重置渠道必须为 student_no 或 email"
    reset_value = payload.get("reset_value")
    if not isinstance(reset_value, str) or not reset_value:
        fields["reset_value"] = "凭证值必填"
    new_password = payload.get("new_password")
    if not isinstance(new_password, str) or not PASSWORD_RE.fullmatch(new_password):
        fields["new_password"] = "密码长度须为 8–64 位且同时包含字母与数字"
    if fields:
        raise _fields_error(fields)

    user = db.session.execute(
        db.select(User).where(User.username == username)
    ).scalar_one_or_none()
    expected = None
    if user is not None:
        expected = user.student_no if channel == "student_no" else user.email
    if expected is None or reset_value != expected:
        raise ApiError(ErrorCode.RESET_CREDENTIAL_MISMATCH)

    user.password_hash = security.hash_password(new_password)
    db.session.commit()
