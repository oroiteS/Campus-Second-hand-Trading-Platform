"""校园认证域路由（tag: certification）：申请提交与我的历史。

只做：multipart 解析（form 原样传 service、client_ip/文件提取）→
调 service → 组装 envelope；校验与事务全部在 service。
"""

from flask import Blueprint, g, request

from src.common import responses
from src.common.auth import login_required
from src.services import certification_service

bp = Blueprint("certification", __name__)


@bp.post("/applications")
@login_required
def submit_application():
    """POST /api/certification/applications —— 提交认证申请（status=pending）。"""
    application = certification_service.submit(
        g.current_user, request.form, request.files.get("file")
    )
    return responses.success(application.to_dict())


@bp.get("/applications/mine")
@login_required
def my_applications():
    """GET /api/certification/applications/mine —— 我的申请历史（倒序，不分页）。"""
    applications = certification_service.my_applications(g.current_user.id)
    return responses.success([application.to_dict() for application in applications])
