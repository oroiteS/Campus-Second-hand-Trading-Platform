"""Redis 客户端：懒初始化、按库偏移缓存连接（0-3 四库一组）。

全项目仅本模块 import redis；其他模块一律经 ``get_redis(db_offset)``
取用。库号分配约定（项目规范「数据与端口隔离」）：自 ``REDIS_DB_BASE``
起 4 库一组——0 聊天 / 1 评价 / 2 商品 / 3 系统。系统库固定 +3：登录
限流 ``rate:login:{ip}`` 与 jti 黑名单 ``auth:blacklist:{jti}`` 落这里；
商品库 +2：商品 detail/category 缓存（b2be）；向量重试队列落系统库
+3（b2be2，任务卡「向量同步」节钉死）。
"""

import redis as redis_lib
from flask import current_app

# 系统库相对 REDIS_DB_BASE 的偏移（既有 b1 调用点 get_redis() 的默认值）
SYSTEM_DB_OFFSET = 3
# 商品库相对 REDIS_DB_BASE 的偏移
PRODUCT_DB_OFFSET = 2
# 一组 4 库的合法偏移域
_DB_OFFSET_RANGE = range(0, 4)

# 懒初始化的连接池：offset → (client, 建库签名)；配置变化时按 offset 重建
_clients: dict[int, redis_lib.Redis] = {}
_client_signatures: dict[int, tuple[str, int, str, int]] = {}


def get_redis(db_offset: int = SYSTEM_DB_OFFSET) -> redis_lib.Redis:
    """返回指定偏移库的 Redis 客户端；需在应用上下文内调用（读 app.config）。

    b1 既有 ``get_redis()`` 调用点等价于 ``db_offset=3``（系统库），行为
    不变。连接惰性建立：本函数不触网，Redis 不可用时首次真实命令才报错，
    由调用方按各自的降级语义处理（黑名单 fail-open、限流放行、缓存降级）。
    """
    if db_offset not in _DB_OFFSET_RANGE:
        raise ValueError(f"db_offset 必须在 0-3 内（聊天/评价/商品/系统），收到 {db_offset}")
    config = current_app.config
    signature = (
        config["REDIS_HOST"],
        config["REDIS_PORT"],
        config["REDIS_PASSWORD"],
        config["REDIS_DB_BASE"] + db_offset,
    )
    cached = _clients.get(db_offset)
    if cached is None or _client_signatures.get(db_offset) != signature:
        cached = redis_lib.Redis(
            host=signature[0],
            port=signature[1],
            password=signature[2] or None,
            db=signature[3],
            decode_responses=True,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )
        _clients[db_offset] = cached
        _client_signatures[db_offset] = signature
    return cached
