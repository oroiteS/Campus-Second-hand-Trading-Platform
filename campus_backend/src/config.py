"""集中定义全部配置项——全项目唯一读取环境变量的地方。

其他模块一律从 ``app.config`` 取值，不得散落 ``os.getenv``（唯一例外见
``src/model.py`` 的 ``prefix()``，原因见其注释）。

变量清单对齐项目规范「配置管理」；worktree 隔离参数（表前缀 / 独立
Mongo 库 / Redis 库基址 / Chroma 集合后缀）同样经环境变量注入。
"""

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


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _env_bool(key: str, default: bool) -> bool:
    """布尔型环境变量；无法识别的取值回退默认值（笔误不应导致启动失败）。"""
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return default


_UPLOAD_DIR_RAW = _env_str("UPLOAD_DIR", "uploads")
_UPLOAD_PATH = Path(_UPLOAD_DIR_RAW)


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
    MONGO_URI = _env_str(
        "MONGO_URI",
        "mongodb://root:change_me@127.0.0.1:27017/campus_market?authSource=admin",
    )
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

    # ---- Embedding（OpenAI 兼容端点；云端优先、本地侧车兜底的双模）----
    EMBEDDING_BASE_URL = _env_str("EMBEDDING_BASE_URL", "")
    EMBEDDING_API_KEY = _env_str("EMBEDDING_API_KEY", "")
    EMBEDDING_MODEL = _env_str("EMBEDDING_MODEL", "")
    EMBEDDING_DIM = _env_int("EMBEDDING_DIM", 1024)

    # ---- 本地 Embedding 侧车（tools/local_embedding，OpenAI 兼容，默认 8010）----
    # 云端不可用时按 EMBEDDING_LOCAL_ENABLED 决定是否降级到本地；三者
    # 均非敏感信息，可入 .env 与文档。
    EMBEDDING_LOCAL_BASE_URL = _env_str("EMBEDDING_LOCAL_BASE_URL", "http://127.0.0.1:8010/v1")
    EMBEDDING_LOCAL_MODEL = _env_str("EMBEDDING_LOCAL_MODEL", "qwen3_embedding_0_6b")
    EMBEDDING_LOCAL_ENABLED = _env_bool("EMBEDDING_LOCAL_ENABLED", True)

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
