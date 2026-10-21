"""学校域路由（tag: schools）：公开列表（游客可查，无业务错误）。"""

from flask import Blueprint

from src.common import responses
from src.services import school_service

bp = Blueprint("schools", __name__)


@bp.get("")
def list_schools():
    """GET /api/schools —— 公开；仅启用学校与校区，按名称排序，不分页。"""
    return responses.success(school_service.list_enabled())
