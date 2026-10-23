"""首页推荐路由（tag: recommendations）：GET /api/recommendations/home（b2be2）。

只做解析校验 → 调 service → 组装 envelope；配比/缓存/降级全在 service。
"""

from flask import Blueprint, g, request

from src.common import responses
from src.common.auth import verified_required
from src.services import recommendation_service

bp = Blueprint("recommendations", __name__)


@bp.get("/home")
@verified_required
def home():
    """GET /api/recommendations/home —— 首页推荐（管理员空列表；refresh 换一批）。"""
    refresh = request.args.get("refresh") == "true"
    return responses.success(recommendation_service.home_feed(g.current_user, refresh))
