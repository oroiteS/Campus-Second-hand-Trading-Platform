"""应用工厂：创建 Flask、初始化扩展、注册路由与全局错误处理。

import 顺序约定：``src.config``（其模块级 load_dotenv）必须先于
``src.model`` 加载，保证 model 的 ``prefix()`` 在类定义期读得到
DB_TABLE_PREFIX——下面的字母序 import 恰好满足，勿调整顺序。
"""

from flask import Flask, request
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from werkzeug.exceptions import HTTPException, MethodNotAllowed

from src.common import responses
from src.common.auth import inject_scope, register_jwt_hooks
from src.common.errors import ApiError, ErrorCode, map_http_status
from src.config import get_config_class
from src.model import db
from src.router import register_routes


def create_app(config_object: object = None) -> Flask:
    """创建并装配 Flask 应用。"""
    app = Flask(__name__)
    app.config.from_object(config_object or get_config_class())
    app.json.ensure_ascii = False  # 中文 message 原样输出

    # 扩展初始化（db 实例来自 model.py，此处仅 init_app；
    # Alembic 版本表同样带 DB_TABLE_PREFIX 前缀，随 worktree 隔离）
    db.init_app(app)
    Migrate().init_app(app, db, version_table=f"{app.config['DB_TABLE_PREFIX']}alembic_version")
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    _configure_jwt(JWTManager(app))
    # 每请求进入即注入同校作用域上下文（g.school_id / g.scope_all）
    app.before_request(inject_scope)

    register_routes(app)
    _register_error_handlers(app)
    # b2be2：向量重试补偿线程（默认开；TESTING 跳过）
    if app.config.get("VECTOR_RETRY_WORKER") and not app.config.get("TESTING"):
        from src.services.vector_retry_worker import start_worker

        start_worker(app)
    # 启动任务（孤儿商品图清理等）：TESTING 跳过；失败仅日志、不阻断起服务
    if not app.config.get("TESTING"):
        from src.services.upload_service import run_startup_tasks

        with app.app_context():
            run_startup_tasks()
    return app


def _configure_jwt(jwt: JWTManager) -> None:
    """JWT 校验错误统一转契约 envelope（1001/1002/1003）。

    外加 jti 黑名单检查（common.auth.register_jwt_hooks：Redis 故障
    fail-open 放行 + 告警日志，与降级决策一致）。
    """
    register_jwt_hooks(jwt)

    @jwt.expired_token_loader
    def _expired_token(_jwt_header, _payload):
        return responses.failure(ErrorCode.TOKEN_EXPIRED)

    @jwt.invalid_token_loader
    def _invalid_token(_reason):
        return responses.failure(ErrorCode.TOKEN_INVALID)

    @jwt.unauthorized_loader
    def _unauthorized(_reason):
        return responses.failure(ErrorCode.TOKEN_INVALID)

    @jwt.revoked_token_loader
    def _revoked_token(_jwt_header, _payload):
        return responses.failure(ErrorCode.TOKEN_REVOKED)


def _register_error_handlers(app: Flask) -> None:
    """全局兜底：一切错误响应输出契约 ``{code, message, data}`` envelope。"""

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        app.logger.info("业务错误 %s: %s", err.error.code, err.message)
        return responses.failure(
            err.error, message=err.message, data=err.data, status=err.http_status
        )

    @app.errorhandler(MethodNotAllowed)
    def handle_method_not_allowed(err: MethodNotAllowed):
        # 契约 0.3.0：405 场景统一走 envelope，业务码 9007（b0 遗留清账）
        app.logger.info("方法不支持 %s %s", request.method, request.path)
        return responses.failure(ErrorCode.METHOD_NOT_ALLOWED, status=405)

    @app.errorhandler(HTTPException)
    def handle_http_exception(err: HTTPException):
        error, message = map_http_status(err.code or 500)
        return responses.failure(error, message=message, status=err.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected_error(err: Exception):
        app.logger.exception("未处理异常: %s", err)
        return responses.failure(ErrorCode.INTERNAL_ERROR)
