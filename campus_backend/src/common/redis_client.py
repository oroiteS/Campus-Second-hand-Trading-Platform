"""Redis 客户端：懒初始化单例（系统库 = REDIS_DB_BASE + 3）。

全项目仅本模块 import redis；其他模块一律经 ``get_redis()`` 取用。
库号分配约定（项目规范「数据与端口隔离」）：自 ``REDIS_DB_BASE`` 起
4 库一组（聊天/评价/商品/系统），系统库固定 +3——登录限流
``rate:login:{ip}`` 与 jti 黑名单 ``auth:blacklist:{jti}`` 落这里。
"""

import redis as redis_lib
from flask import current_app

# 系统库相对 REDIS_DB_BASE 的偏移
SYSTEM_DB_OFFSET = 3

# 懒初始化的单例与建库签名（配置变化时重建，便于测试切换配置）
_client: redis_lib.Redis | None = None
_client_signature: tuple[str, int, str, int] | None = None


def get_redis() -> redis_lib.Redis:
    """返回系统库 Redis 客户端；需在应用上下文内调用（读 app.config）。

    连接惰性建立：本函数不触网，Redis 不可用时首次真实命令才报错，
    由调用方按各自的降级语义处理（黑名单 fail-open、限流放行）。
    """
    global _client, _client_signature
    config = current_app.config
    signature = (
        config["REDIS_HOST"],
        config["REDIS_PORT"],
        config["REDIS_PASSWORD"],
        config["REDIS_DB_BASE"] + SYSTEM_DB_OFFSET,
    )
    if _client is None or _client_signature != signature:
        _client = redis_lib.Redis(
            host=signature[0],
            port=signature[1],
            password=signature[2] or None,
            db=signature[3],
            decode_responses=True,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )
        _client_signature = signature
    return _client
