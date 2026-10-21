"""密码哈希（bcrypt，NFR-05）与 JWT 签发助手。

密码落库纪律：bcrypt 加盐哈希——任何链路不得明文、不得可逆加密、
不得以 sha256 等无盐快速哈希替代（sha256 仅用于上传文件内容改名，
与密码无关，见 ``uploads.py``）。
"""

from typing import TYPE_CHECKING

import bcrypt
from flask import current_app
from flask_jwt_extended import create_access_token

if TYPE_CHECKING:
    from src.model import User


def hash_password(raw: str) -> str:
    """bcrypt 加盐哈希（每次随机盐），返回可入库的 ASCII 哈希串。"""
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(raw: str, hashed: str) -> bool:
    """与 bcrypt 哈希比对；哈希串非法（格式不符）一律 False。"""
    if not hashed or not hashed.startswith("$2"):
        return False
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("ascii"))
    except ValueError:  # 含 UnicodeEncodeError：脏数据按校验失败处理
        return False


def issue_token(user: "User") -> tuple[str, int]:
    """签发 JWT（identity = ``str(user.id)``），返回 ``(token, expires_in 秒)``。"""
    token = create_access_token(identity=str(user.id))
    expires_in = int(current_app.config["JWT_ACCESS_TOKEN_EXPIRES"].total_seconds())
    return token, expires_in
