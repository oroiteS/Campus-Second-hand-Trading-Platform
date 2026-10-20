"""系统路由（tag: system，均公开）：健康检查与 OpenAPI 文档。"""

from flask import Blueprint, jsonify

from src.common.responses import success
from src.services import system_service

bp = Blueprint("system", __name__)


@bp.get("/health")
def get_health():
    """GET /api/health —— 四库连通性 + Embedding 生效模式探测。

    任一依赖不可用 HTTP 仍 200，由 data.status = degraded 表达。
    """
    return success(system_service.check_health())


@bp.get("/openapi.json")
def get_openapi_json():
    """GET /api/openapi.json —— 契约原文（docs/api/openapi.yaml）的 JSON 序列化。

    按契约该接口返回 OpenAPI 文档对象本身，不套响应 envelope。
    """
    return jsonify(system_service.load_openapi_document())
