"""图片域路由（tag: images）：实体鉴权访问。

契约明确：成功响应不走统一响应体 envelope，直接输出文件流；
错误仍按 ErrorEnvelope JSON 结构输出（ApiError 走全局处理器）。
"""

from flask import Blueprint, g, send_file

from src.common.auth import login_required_img
from src.services import image_service

bp = Blueprint("images", __name__)


@bp.get("/<int:image_id>")
@login_required_img
def get_image(image_id: int):
    """GET /api/images/{id} —— 图片实体二进制（Bearer 头优先，缺失回退
    img_token Cookie；二者同一 JWT 校验与黑名单，契约 0.3.0 双通道）。"""
    image = image_service.get_with_access_check(image_id, g.current_user)
    return send_file(image_service.open_file(image), mimetype=image.mime)
