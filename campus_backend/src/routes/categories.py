"""分类域路由（tag: categories）：启用分类列表（不分页）。"""

from flask import Blueprint

from src.common import responses
from src.common.auth import verified_required
from src.services import category_service

bp = Blueprint("categories", __name__)


@bp.get("/categories")
@verified_required
def list_categories():
    """GET /api/categories —— 启用分类（sort_order 升序；缓存 3600s）。"""
    return responses.success(category_service.list_enabled())
