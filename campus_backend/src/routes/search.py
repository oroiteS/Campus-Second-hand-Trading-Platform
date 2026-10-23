"""向量搜索路由（tag: products）：GET /api/products/search（b2be2）。

与 ``products.py`` 同 url_prefix、不同 endpoint（``search.*``），无冲突。
只做解析校验 → 调 service → 组装 envelope；业务与降级全在 service。
"""

from flask import Blueprint, g, request

from src.common import responses
from src.common.auth import verified_required
from src.common.pagination import parse_pagination
from src.services import search_service

bp = Blueprint("search", __name__)

# 搜索可携带的筛选参数（解析为原始字符串，校验在 service 复用列表口径）
_FILTER_KEYS = ("category_id", "condition", "price_min", "price_max", "campus_id")


@bp.get("/search")
@verified_required
def search_products():
    """GET /api/products/search —— 向量搜索（降级时 LIKE + degraded 标记）。"""
    pagination = parse_pagination()
    filters = {key: request.args.get(key) for key in _FILTER_KEYS}
    return responses.success(
        search_service.search(
            g.current_user,
            request.args.get("q", ""),
            filters,
            pagination.page,
            pagination.page_size,
        )
    )
