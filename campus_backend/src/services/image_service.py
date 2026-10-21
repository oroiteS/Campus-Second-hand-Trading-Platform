"""图片域服务：鉴权访问控制与实体文件读取。"""

from pathlib import Path
from typing import TYPE_CHECKING

from flask import current_app

from src.common.errors import ApiError, ErrorCode
from src.model import Image, db

if TYPE_CHECKING:
    from src.model import User


def get_with_access_check(image_id: int, current_user: "User") -> Image:
    """按 id 取图并做访问控制（NFR-08）。

    ``student_card`` 仅上传者本人与管理员可读；越权与不存在一律
    404/9002，不区分两种情况（防探测）。其余用途（本批次 avatar）
    登录即可读。
    """
    image = db.session.get(Image, image_id)
    if image is None:
        raise ApiError(ErrorCode.NOT_FOUND)
    if image.purpose == "student_card":
        is_owner = image.owner_id == current_user.id
        is_admin = current_user.role == "admin"
        if not (is_owner or is_admin):
            raise ApiError(ErrorCode.NOT_FOUND)
    return image


def open_file(image: Image) -> Path:
    """解析图片实体文件绝对路径；文件缺失同样 404/9002（不泄露细节）。"""
    path = Path(current_app.config["UPLOAD_DIR"]) / image.path
    if not path.is_file():
        raise ApiError(ErrorCode.NOT_FOUND)
    return path
