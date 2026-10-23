"""campus_backend 源码包。

分层与依赖方向（flask-backend 规范，单向）：
main → app → router → routes → services → model；common/ 为横切件，
只被 router/routes/services 引用，不反向依赖。
"""

# 包加载自举：保证 src.config（其模块级 load_dotenv）先于任何子模块执行。
# b1 隐含缺陷修复（b2be 真机冒烟发现）：src.common.auth 会经
# ``from src.model import ...`` 先于 app.py 的 src.config 行触发 model 加载，
# 使 ``prefix()`` 在类定义期读不到 DB_TABLE_PREFIX，ORM 表名失去前缀、
# 与迁移建的 ``b2be-`` 表脱节。在此单一入口点补上该顺序保证，任何
# ``import src.*`` 路径（含迁移脚本直连 src.model）都先完成 dotenv 加载。
from src import config as _config  # noqa: F401
