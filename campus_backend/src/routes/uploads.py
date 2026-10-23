"""上传域路由（tag: uploads）：通用图片上传（本批次 purpose=product）。"""

from flask import Blueprint, g, request

from src.common import responses
from src.common.auth import verified_required
from src.common.errors import ApiError, ErrorCode
from src.services import upload_service

bp = Blueprint("uploads", __name__)

# 本接口接受的 purpose 值域（b4 聊天图复用时扩展 image_message）
_PURPOSES = ("product",)


@bp.post("/uploads")
@verified_required
def upload_image():
    """POST /api/uploads —— multipart：file + purpose（管理员 9003）。"""
    purpose = request.form.get("purpose")
    if purpose not in _PURPOSES:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            data={"fields": {"purpose": "上传用途必须为 product"}},
        )
    image = upload_service.save_product_image(g.current_user, request.files.get("file"))
    return responses.success(image.ref_dict())
