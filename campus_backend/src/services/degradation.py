"""对外降级文案的**唯一来源**（S-1/S-6）：固定可读文案，不含内部细节。

``degraded_reason`` 是契约字段（字符串），但不得携带异常类型、异常消息、
主机、端口、集合名等内部信息——原始原因一律只进 ``logger.warning``。
搜索与推荐共用本模块常量，避免两套口径漂移。
"""

from __future__ import annotations

# 搜索：向量链路不可用 → MySQL 标题匹配
VECTOR_DEGRADED_REASON = "向量检索暂不可用，已按标题匹配"

# 推荐：embedding / 画像召回不可用 → 全随机
EMBEDDING_UNAVAILABLE_REASON = "向量服务暂不可用，已降级为随机推荐"
RECALL_DEGRADED_REASON = "画像召回路暂不可用，已降级为随机推荐"

# 推荐：画像存储（Mongo）不可用 → 全随机
PROFILE_STORE_UNAVAILABLE_REASON = "画像存储暂不可用，已降级为随机推荐"

# 认证：登出写黑名单失败 → 契约仍 200，附 degraded 标记
LOGOUT_DEGRADED_REASON = "注销状态暂不可用，令牌将在到期后自动失效"
