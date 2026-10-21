"""用户域服务：个人资料读取/更新、密码修改、头像更新（事务边界在本层提交）。

字段规则按批次计划「3.0 字段校验对照表」在 service 独立复验，不信任
客户端；``phone`` 须匹配 ``^1\\d{10}$``、空串清除存 NULL；approved 且
昵称变更 → ``display_name`` 重算（FR-USR-10 / AC-04）。
"""

import re
from typing import TYPE_CHECKING

from src.common import security, uploads
from src.common.errors import ApiError, ErrorCode
from src.model import User, db
from src.services.auth_service import EMAIL_RE, PASSWORD_RE

if TYPE_CHECKING:
    from werkzeug.datastructures import FileStorage

# 契约 3.0：phone 填写时为 1 开头的 11 位纯数字；空串 = 清除
PHONE_RE = re.compile(r"^1\d{10}$")


def _fields_error(fields: dict[str, str]) -> ApiError:
    return ApiError(ErrorCode.VALIDATION_ERROR, data={"fields": fields})


def get_profile(user_id: int) -> User:
    """当前登录用户资料；登录态用户已不存在视为登录失效（401/1001）。"""
    user = db.session.get(User, user_id)
    if user is None:
        raise ApiError(ErrorCode.TOKEN_INVALID)
    return user


def update_profile(user: User, payload: object) -> User:
    """更新资料：仅更新请求体中出现的字段（username / student_no 不可改）。"""
    if not isinstance(payload, dict):
        raise _fields_error({"body": "请求体必须为 JSON 对象"})

    fields: dict[str, str] = {}
    updates: dict[str, object] = {}
    if "nickname" in payload:
        nickname = payload["nickname"]
        if not isinstance(nickname, str) or not 1 <= len(nickname) <= 32:
            fields["nickname"] = "昵称长度须为 1–32 字符"
        else:
            updates["nickname"] = nickname
    if "email" in payload:
        email = payload["email"]
        if not isinstance(email, str) or not EMAIL_RE.fullmatch(email):
            fields["email"] = "邮箱格式不正确"
        else:
            updates["email"] = email
    if "phone" in payload:
        phone = payload["phone"]
        if phone is None or phone == "":
            updates["phone"] = None  # 空串/null = 清除，存 NULL
        elif isinstance(phone, str) and PHONE_RE.fullmatch(phone):
            updates["phone"] = phone
        else:
            fields["phone"] = "手机号须为 1 开头的 11 位纯数字；空串表示清除"
    if fields:
        raise _fields_error(fields)

    nickname_changed = False
    for key, value in updates.items():
        if key == "nickname" and value != user.nickname:
            nickname_changed = True
        setattr(user, key, value)
    if nickname_changed:
        if user.auth_status == "approved":
            user.display_name_recalc(user.school, user.campus)
        else:
            # 未认证 / pending / rejected：展示名 = 昵称（FR-USR-10）
            user.display_name_recalc(None, None)
    db.session.commit()
    return user


def change_password(user: User, old_password: object, new_password: object) -> None:
    """修改密码：原密码错误 400/2003；新密码强度同注册（9001）；bcrypt 落库。"""
    fields: dict[str, str] = {}
    if not isinstance(old_password, str) or not old_password:
        fields["old_password"] = "原密码必填"
    if not isinstance(new_password, str) or not PASSWORD_RE.fullmatch(new_password):
        fields["new_password"] = "密码长度须为 8–64 位且同时包含字母与数字"
    if fields:
        raise _fields_error(fields)
    if not security.verify_password(old_password, user.password_hash):
        raise ApiError(ErrorCode.OLD_PASSWORD_MISMATCH)
    user.password_hash = security.hash_password(new_password)
    db.session.commit()


def update_avatar(user: User, file_storage: "FileStorage | None") -> User:
    """头像上传：四件套校验 + images 落库 + user 头像指针，同一事务提交。

    旧头像文件保留不删（images 表仅增不改，YAGNI）。
    """
    image = uploads.validate_and_save(file_storage, "avatar")
    image.owner_id = user.id
    db.session.add(image)
    user.avatar = image  # 关系赋值，插入顺序由 ORM 保证
    db.session.commit()
    return user
