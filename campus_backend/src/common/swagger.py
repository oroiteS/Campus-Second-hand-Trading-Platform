"""Swagger UI 文档路由装配（flask-swagger-ui，静态资源随包分发、离线可用）。

按项目规范「Swagger UI」节：``/api/docs`` 页面由 flask-swagger-ui 蓝图承接，
数据源为本服务的 ``/api/openapi.json``。蓝图装配属横切件放在 common/，
注册动作仍统一发生在 router.py。
"""

from flask import Blueprint
from flask_swagger_ui import get_swaggerui_blueprint

SWAGGER_URL = "/api/docs"
OPENAPI_JSON_URL = "/api/openapi.json"


def create_swagger_ui_blueprint() -> Blueprint:
    """构建 Swagger UI 蓝图（自带 url_prefix=/api/docs，含静态资源子路由）。"""
    return get_swaggerui_blueprint(
        base_url=SWAGGER_URL,
        api_url=OPENAPI_JSON_URL,
        config={"app_name": "校园二手交易平台 API"},
    )
