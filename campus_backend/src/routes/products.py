"""商品域路由（tag: products）：列表 / 发布 / 我的商品 / 详情。

**不含 search 路由**（`GET /api/products/search` 属 b2be2）。只做解析校验
→ 调 service → 组装 envelope；业务与事务全部在 service。
"""

from flask import Blueprint, g, request

from src.common import responses
from src.common.auth import verified_required
from src.common.errors import ApiError, ErrorCode
from src.common.pagination import parse_pagination
from src.services import product_service

bp = Blueprint("products", __name__)

# 列表可携带的筛选参数（解析为原始字符串，校验在 service 独立复验）
_FILTER_KEYS = (
    "category_id",
    "condition",
    "price_min",
    "price_max",
    "campus_id",
    "keyword",
    "sort",
)


def _json_payload() -> dict:
    """解析 JSON 请求体；缺失或非对象统一 9001。"""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            data={"fields": {"body": "请求体必须为 JSON 对象"}},
        )
    return payload


@bp.get("")
@verified_required
def list_products():
    """GET /api/products —— 本校在售分页列表（管理员跨校全量）。"""
    pagination = parse_pagination()
    filters = {key: request.args.get(key) for key in _FILTER_KEYS}
    return responses.success(
        product_service.list_on_sale(filters, pagination.page, pagination.page_size)
    )


@bp.post("")
@verified_required
def create_product():
    """POST /api/products —— 发布（管理员 9003；返回 ProductDetail）。"""
    product = product_service.create(g.current_user, _json_payload())
    return responses.success(product_service.detail_payload(product, g.current_user))


@bp.get("/mine")
@verified_required
def my_products():
    """GET /api/products/mine —— 我的商品（created_at 倒序，缺省除 deleted）。"""
    pagination = parse_pagination()
    return responses.success(
        product_service.mine(
            g.current_user, request.args.get("status"), pagination.page, pagination.page_size
        )
    )


@bp.get("/<int:product_id>")
@verified_required
def product_detail(product_id: int):
    """GET /api/products/{id} —— 详情（可见性矩阵；防探测 404/9002）。"""
    return responses.success(product_service.get_detail(g.current_user, product_id))


@bp.put("/<int:product_id>")
@verified_required
def update_product(product_id: int):
    """PUT /api/products/{id} —— 编辑（全量替换；管理员 9003）。"""
    product = product_service.update(g.current_user, product_id, _json_payload())
    return responses.success(product_service.detail_payload(product, g.current_user))


@bp.patch("/<int:product_id>/status")
@verified_required
def update_product_status(product_id: int):
    """PATCH /api/products/{id}/status —— 上下架（返回 ProductSummary）。"""
    payload = _json_payload()
    status = payload.get("status")
    if status not in ("on_sale", "off_sale"):
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            data={"fields": {"status": "目标状态必须为 on_sale 或 off_sale"}},
        )
    product = product_service.change_status(g.current_user, product_id, status)
    return responses.success(product.to_summary_dict())


@bp.delete("/<int:product_id>")
@verified_required
def delete_product(product_id: int):
    """DELETE /api/products/{id} —— 软删（data 为 null）。"""
    product_service.delete(g.current_user, product_id)
    return responses.success(None)
