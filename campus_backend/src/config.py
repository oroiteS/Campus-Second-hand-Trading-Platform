"""集中定义全部配置项——全项目唯一读取环境变量的地方。

其他模块一律从 ``app.config`` 取值，不得散落 ``os.getenv``（唯一例外见
``src/model.py`` 的 ``prefix()``，原因见其注释）。

变量清单对齐项目规范「配置管理」；worktree 隔离参数（表前缀 / 独立
Mongo 库 / Redis 库基址 / Chroma 集合后缀）同样经环境变量注入。
"""

import logging
import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

# campus_backend/ 目录；仓库根（worktree 检出根）为其上一级。
BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent

# load_dotenv 只在本模块执行一次；override=False 表示已存在的进程环境变量
# 优先于 .env 文件（便于测试与临时覆盖）。
load_dotenv(BASE_DIR / ".env", override=False)


def _env_str(key: str, default: str = "") -> str:
    value = os.getenv(key)
    return default if value is None else value


def _strip_inline_comment(raw: str) -> str:
    """剥离 ``#`` 起的行内注释并去空白。

    只用于数值 / 布尔这类「取值里不可能含 #」的变量；字符串型变量（密钥、
    密码、URI）不走这里，避免把合法的 ``#`` 当注释吃掉。
    """
    return raw.split("#", 1)[0].strip()


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None:
        return default
    value = _strip_inline_comment(raw)
    if value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _env_bool(key: str, default: bool) -> bool:
    """布尔型环境变量；无法识别的取值回退默认值（笔误不应导致启动失败）。

    兼容两种写法：``true`` 与带行内注释的 ``true # 说明``。``python-dotenv``
    对不带引号的值会把 ``#`` 之后的内容原样保留，若不做剥离，
    ``EMBEDDING_LOCAL_ENABLED=true # false=...`` 会被当成未知值而回落到默认，
    行为与字面相反。
    """
    raw = os.getenv(key)
    if raw is None:
        return default
    normalized = _strip_inline_comment(raw).lower()
    if normalized == "":
        return default
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return default


_UPLOAD_DIR_RAW = _env_str("UPLOAD_DIR", "uploads")
_UPLOAD_PATH = Path(_UPLOAD_DIR_RAW)


def _env_choice(key: str, default: str, allowed: tuple[str, ...]) -> str:
    """枚举型环境变量；取值非法（含空串）回退默认值并落 WARNING。

    与 ``_env_int`` / ``_env_bool`` 同一容错哲学：笔误不应让应用起不来，
    但也绝不能静默——非法取值必须留下 WARNING，否则「以为切了 cloud
    实际还在 local」这类问题极难排查。取值大小写不敏感，且剥离行内注释
    （``local # 默认`` 视为 ``local``）。
    """
    if key not in os.environ:  # 未设置：静默用默认值
        return default
    value = _strip_inline_comment(_env_str(key)).lower()
    if value in allowed:
        return value
    logging.getLogger(__name__).warning(
        "%s 取值非法（%r），回退默认值 %r；合法取值：%s",
        key,
        value,
        default,
        " | ".join(allowed),
    )
    return default


class Config:
    """基础配置：全部配置项集中于此。"""

    # ---- 应用与运行 ----
    HOST = "127.0.0.1"  # 监听地址（本地开发默认仅绑回环，不走环境变量）
    PORT = _env_int("PORT", 5000)
    SECRET_KEY = _env_str("SECRET_KEY", "dev-insecure-secret-key")
    JWT_EXPIRE_MINUTES = _env_int("JWT_EXPIRE_MINUTES", 1440)
    DEBUG = False
    TESTING = False

    # ---- MySQL（SQLAlchemy / Alembic）----
    MYSQL_HOST = _env_str("MYSQL_HOST", "127.0.0.1")
    MYSQL_PORT = _env_int("MYSQL_PORT", 3306)
    MYSQL_DB = _env_str("MYSQL_DB", "campus_trading")
    MYSQL_USER = _env_str("MYSQL_USER", "campus_app")
    MYSQL_PASSWORD = _env_str("MYSQL_PASSWORD", "")
    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{quote_plus(MYSQL_USER)}:{quote_plus(MYSQL_PASSWORD)}"
        f"@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}?charset=utf8mb4"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 3600}

    # ---- worktree 表前缀（业务表与 Alembic 版本表共用）----
    DB_TABLE_PREFIX = _env_str("DB_TABLE_PREFIX", "")

    # ---- MongoDB ----
    # 默认值只指向本机（无认证、无 authSource 歧义）；库名由 MONGO_DB 决定。
    # 远端集群凭据只写本地 .env，绝不入仓（NFR-13）。
    MONGO_URI = _env_str("MONGO_URI", "mongodb://127.0.0.1:27017/campus_market")
    MONGO_DB = _env_str("MONGO_DB", "campus_market")

    # ---- Redis ----
    REDIS_HOST = _env_str("REDIS_HOST", "127.0.0.1")
    REDIS_PORT = _env_int("REDIS_PORT", 6379)
    REDIS_PASSWORD = _env_str("REDIS_PASSWORD", "")
    REDIS_DB_BASE = _env_int("REDIS_DB_BASE", 0)

    # ---- Chroma ----
    CHROMA_HOST = _env_str("CHROMA_HOST", "127.0.0.1")
    CHROMA_PORT = _env_int("CHROMA_PORT", 8000)
    CHROMA_COLLECTION_SUFFIX = _env_str("CHROMA_COLLECTION_SUFFIX", "")

    # ---- Embedding（OpenAI 兼容端点；生效策略由 EMBEDDING_MODE 决定）----
    # EMBEDDING_MODE：local（默认，只打本地侧车、零云端请求）|
    # cloud（只探云端）| auto（旧行为：云端优先、本地兜底）。
    EMBEDDING_MODE = _env_choice("EMBEDDING_MODE", "local", ("local", "cloud", "auto"))
    # 以下三项仅在 EMBEDDING_MODE=cloud|auto 时读取；默认 local 不读、不请求。
    EMBEDDING_BASE_URL = _env_str("EMBEDDING_BASE_URL", "")
    EMBEDDING_API_KEY = _env_str("EMBEDDING_API_KEY", "")
    EMBEDDING_MODEL = _env_str("EMBEDDING_MODEL", "")
    EMBEDDING_DIM = _env_int("EMBEDDING_DIM", 1024)

    # ---- 本地 Embedding 侧车（tools/local_embedding，OpenAI 兼容，默认 8010）----
    # 默认 local 模式下生效；auto 模式下作为云端不可用时的兜底。
    # EMBEDDING_LOCAL_ENABLED 只在 auto 模式下用于关闭兜底，local 模式恒探测。
    # 三者均非敏感信息，可入 .env 与文档。
    EMBEDDING_LOCAL_BASE_URL = _env_str("EMBEDDING_LOCAL_BASE_URL", "http://127.0.0.1:8010/v1")
    EMBEDDING_LOCAL_MODEL = _env_str("EMBEDDING_LOCAL_MODEL", "qwen3_embedding_0_6b")
    EMBEDDING_LOCAL_ENABLED = _env_bool("EMBEDDING_LOCAL_ENABLED", True)

    # ---- b2be2 向量与推荐 ----
    # 检索指令前缀：搜索时拼在用户查询前（Qwen3 为指令感知模型）。默认取
    # Qwen3 官方检索指令；切模型时按模型卡调整——修改后须全量重建向量。
    EMBEDDING_QUERY_PREFIX = _env_str(
        "EMBEDDING_QUERY_PREFIX",
        "Given a web search query, retrieve relevant passages that answer the query",
    )
    # 向量重试补偿线程开关（默认开）：1/true 开，0/false 关
    VECTOR_RETRY_WORKER = _env_bool("VECTOR_RETRY_WORKER", True)

    # ---- 上传 ----
    UPLOAD_DIR = str(_UPLOAD_PATH if _UPLOAD_PATH.is_absolute() else BASE_DIR / _UPLOAD_PATH)
    MAX_UPLOAD_MB = _env_int("MAX_UPLOAD_MB", 5)

    # ---- 契约文档（供 /api/openapi.json 读取；相对 worktree 检出根定位）----
    OPENAPI_YAML_PATH = str(REPO_ROOT / "docs" / "api" / "openapi.yaml")

    # ---- JWT（flask-jwt-extended）----
    JWT_SECRET_KEY = SECRET_KEY
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=JWT_EXPIRE_MINUTES)


class DevConfig(Config):
    """开发环境（FLASK_ENV=development，默认）。"""

    DEBUG = True


class ProdConfig(Config):
    """生产环境（FLASK_ENV=production）。"""

    DEBUG = False


def get_config_class() -> type[Config]:
    """按 FLASK_ENV 选择配置类；未知取值一律按开发处理。"""
    env = os.getenv("FLASK_ENV", "development")
    return ProdConfig if env == "production" else DevConfig
