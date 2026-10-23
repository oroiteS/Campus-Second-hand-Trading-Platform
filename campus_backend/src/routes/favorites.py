"""收藏域路由（tag: favorites）：收藏 / 取消 / 我的收藏。

路径横跨 ``/api/products/{id}/favorite`` 与 ``/api/favorites/mine``，故
蓝图挂 ``/api`` 前缀、路由内写全相对路径。
"""

from flask import Blueprint, g

from src.common import responses
from src.common.auth import verified_required
from src.common.pagination import parse_pagination
from src.services import favorite_service

bp = Blueprint("favorites", __name__)


@bp.post("/products/<int:product_id>/favorite")
@verified_required
def favorite_product(product_id: int):
    """POST /api/products/{id}/favorite —— 收藏（管理员 9003）。"""
    return responses.success(favorite_service.favorite(g.current_user, product_id))


@bp.delete("/products/<int:product_id>/favorite")
@verified_required
def unfavorite_product(product_id: int):
    """DELETE /api/products/{id}/favorite —— 取消收藏（幂等）。"""
    return responses.success(favorite_service.unfavorite(g.current_user, product_id))


@bp.get("/favorites/mine")
@verified_required
def my_favorites():
    """GET /api/favorites/mine —— 收藏列表（favorited_at 倒序，含非在售）。"""
    pagination = parse_pagination()
    return responses.success(
        favorite_service.my_favorites(g.current_user, pagination.page, pagination.page_size)
    )
