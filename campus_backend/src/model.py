"""数据库实例与 ORM 模型集中定义（批次 0 暂无业务模型，模型自批次 1 起）。

分层规则：本文件是依赖链最底层，禁止 import 本项目任何其他模块。
"""

import os

from flask_sqlalchemy import SQLAlchemy

# db 实例全项目唯一，只能在 model.py 创建；app.py 仅做 init_app。
db = SQLAlchemy()


def prefix(name: str) -> str:
    """表名前缀助手：业务模型统一写 ``__tablename__ = prefix("users")``。

    唯一例外点：``__tablename__`` 在类定义期求值，早于任何应用上下文，
    无法读 ``app.config``，故此处直接 ``os.getenv``。其成立的前提是
    ``src/app.py`` 的 import 顺序保证 ``src.config``（load_dotenv）先于
    本模块加载；除本函数外，项目任何位置不得直接读环境变量。
    """
    return f"{os.getenv('DB_TABLE_PREFIX', '')}{name}"
