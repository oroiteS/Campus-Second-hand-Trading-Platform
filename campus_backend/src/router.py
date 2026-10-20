"""唯一蓝图注册处：所有蓝图在此集中注册（统一 /api 前缀）。"""

from flask import Flask

from src.common.swagger import SWAGGER_URL, create_swagger_ui_blueprint
from src.routes import system


def register_routes(app: Flask) -> None:
    """注册全部业务蓝图与文档蓝图。"""
    app.register_blueprint(system.bp, url_prefix="/api")
    # Swagger UI 蓝图自带 url_prefix=/api/docs（静态资源路由挂在其下）
    app.register_blueprint(create_swagger_ui_blueprint())
    # flask-swagger-ui 首页路由注册为 /api/docs/（尾斜杠）；契约路径是
    # /api/docs，放开该组规则的 strict_slashes 使精确路径直接 200，
    # 避免 308 重定向偏离契约。
    for rule in app.url_map.iter_rules():
        if rule.rule.startswith(SWAGGER_URL):
            rule.strict_slashes = False
