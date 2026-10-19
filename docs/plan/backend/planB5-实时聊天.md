# planB5 · 后端：实时聊天

_课程设计项目 · 2026-10-19 · 版本 v1.0 · 状态：待执行_

> **定位**：backend 线第五域。Socket.IO 实时层 + 聊天 REST，消息全量持久化（反目标红线：重启丢失即失败）。
> **上游**：[plan0](../plan0-项目规范.md) · [plan2](../plan2-API契约.md)（含 `docs/api/events.md`）· planB4 已合并
> **对端**：[frontend/planF4](../frontend/planF4-实时聊天.md) —— 并行，与 B4、F3/F4 共同触发**联调点 I3**。

---

## 0. 目标与范围

### 目标

1. FR-CHT-01 ~ FR-CHT-07（P2 输入中提示不做，契约已排除）；
2. `realtime/` 事件层落地（flask-backend skill 结构）：握手 JWT 校验、在线状态、消息收发、已读；
3. Redis db0 聊天缓存（最近 50 / 未读 / 在线键 / 会话 ZSET）作为**可丢弃加速层**，MySQL 为唯一权威。

### 范围内

`models/chat.py` 两表、迁移与种子（2 会话 20 消息）、Socket.IO 事件处理、会话与消息 REST、已读、在线状态、图片消息（复用 B1 uploads）、聊天域 pytest。

### 范围外

typing 事件（P2）；消息撤回（需求明确不支持）；管理端聊天监管（无此需求）。

---

## 1. 契约引用

REST：`/api/conversations`（GET/POST）· `/api/conversations/{id}/messages` · `/api/conversations/{id}/read`。WS：`docs/api/events.md` 全部事件（connect / connect_error / conversation:join / message:send / message:ack / message:new / message:read / presence:update）。

## 2. 对端对应关系

| 本计划任务 | 对端消费 | 汇合点 |
| --- | --- | --- |
| T31 连接层 | F4·T55 Socket 客户端 | I3 |
| T32 消息收发 | F4·T56 聊天窗 | I3 |
| T33 会话 REST 与已读 | F4·T56/T57 | I3 |

## 3. 任务卡（线内串行：T30 → T31 → T32 → T33）

### T30 聊天域模型、迁移与种子

- **目标**：Conversation / ChatMessage 两表 + 种子
- **前置依赖**：planB4 已合并
- **required_skills**：flask-backend
- **owns**：`campus_backend/src/models/chat.py`、`migrations/versions/<聊天域迁移>`、`scripts/seedlib/chat.py`
- **reads**：需求 §数据设计（会话规范化唯一约束）、§聊天
- **forbidden**：`routes/**`、`services/**`、`realtime/**`、`campus_frontend/**`
- **验收标准**：
  1. 两表字段与 ER 一致；`uk_user_pair`（user_a_id<user_b_id 规范化）、`idx_user_a`、`idx_user_b`、`idx_conversation_created` 就位；两表冗余 `school_id`；
  2. 种子：2 组同校会话 + 20 条消息（含文本与图片各若干、已读未读混合、时间递增）；幂等；
  3. 迁移可逆、单头；pytest 冒烟全绿。
- **门禁命令**：§9 L1 + L2
- **规模预期**：约 250 行

### T31 Socket.IO 连接层与在线状态

- **目标**：FR-CHT-01/06；realtime/ 目录首建
- **前置依赖**：T30
- **required_skills**：flask-backend
- **owns**：`campus_backend/src/realtime/__init__.py`、`campus_backend/src/realtime/connection.py`、`campus_backend/src/realtime/presence.py`、`campus_backend/tests/test_socket_connection.py`
- **reads**：需求 §聊天（时序图）；`docs/api/events.md`
- **forbidden**：`models/**`、`migrations/**`、`campus_frontend/**`、routes/services
- **验收标准**：
  1. 握手 `auth.token` 校验 JWT 与认证状态：无效/黑名单→`connect_error CHT1001`；未认证→`connect_error CHT1002`（plan2 §4）；
  2. 在线键 `chat:online:{user_id}` TTL 60s，客户端每 30s 心跳续期（事件或 ping，按 events.md）；断开即删键；
  3. `presence:update` 向**同校关注方**推送（订阅了共同会话的对端）；离线判定=键过期，AC-14 断言路径可测（测试用短 TTL）；
  4. Socket.IO 挂载走应用工厂（flask-backend skill：`init_socketio(app)` 模式），CORS 与 HTTP 一致；
  5. pytest（Flask-SocketIO 测试客户端）全绿。
- **门禁命令**：§9 L1 + L2
- **规模预期**：约 300 行

### T32 消息收发与持久化

- **目标**：FR-CHT-02/03（消息侧）
- **前置依赖**：T31
- **required_skills**：flask-backend
- **owns**：`campus_backend/src/realtime/messaging.py`、`campus_backend/src/services/chat_service.py`、`campus_backend/tests/test_messaging.py`
- **reads**：需求 §聊天；events.md 时序（send→ack→new）
- **forbidden**：`models/**`、`migrations/**`、`campus_frontend/**`
- **验收标准**：
  1. `message:send`：会话必须存在且本人是成员（否则 error 回执）；内容校验（文本 1–2000 字 / 图片 image_id 须 purpose=chat）；同校已在会话创建时保证（T33），此处二次校验；
  2. 落库 MySQL（权威）→ Redis db0 `chat:conv:{id}:recent` 追加（LPUSH+LTRIM 保 50）与 `chat:conv:{id}:meta` 未读+1 → 发 `message:ack`（携 client_msg_id 幂等）给发送者、`message:new` 给对端（在线即推）；
  3. **Redis 不可用时消息仍落库并投递**（缓存层可丢弃，需求 §降级策略）；
  4. `conversation:join` 房间管理（会话成员校验）；
  5. 顺序保证：同一会话消息按 id 递增，ack/new 载荷与 events.md 逐字段一致；
  6. pytest 全绿（含 Redis 故障注入、非成员发送拒绝）。
- **门禁命令**：§9 L1 + L2
- **规模预期**：约 350 行

### T33 会话 REST、历史消息与已读

- **目标**：FR-CHT-02/03/04/05/07
- **前置依赖**：T32
- **required_skills**：flask-backend
- **owns**：`campus_backend/src/routes/conversations.py`、`campus_backend/src/services/conversation_service.py`、`campus_backend/tests/test_conversations.py`
- **reads**：需求 §聊天、§Redis 键设计（db0）
- **forbidden**：`models/**`、`migrations/**`、`campus_frontend/**`、realtime/**
- **验收标准**：
  1. 创建/复用：POST 携 target_user_id；**同校校验（跨校 404）**；规范化唯一约束命中即复用（返回既有 id）；
  2. 会话列表：本人会话按 last_message_at 倒序；含对方展示名、最后消息摘要（图片显示"[图片]"）、未读数（Redis meta，缺失回源 MySQL 计数）；
  3. 历史消息：分页（游标或页码按契约）；**Redis 最近 50 命中则直接返回，否则 MySQL 回源并回填缓存**；**清空 Redis 后历史仍在（AC-13 断言）**；
  4. 已读上报：更新 MySQL read_at 与 Redis 未读清零，实时向对端推已读回执（events.md）；重复上报幂等；
  5. 聊天域 Redis 键全部落 db0（AC-15 抽查点）；键经 `scoped_key`；
  6. pytest 全绿。
- **门禁命令**：§9 L1 + L2
- **规模预期**：约 350 行

---

## 4. 依赖与顺序

T30 → T31 → T32 → T33；与 frontend/planF4 并行。

## 5. 验收映射

| 需求/验收 | 承载 |
| --- | --- |
| FR-CHT-01~07（除 P2） | T30–T33 |
| AC-13 聊天实时与持久化 | T32/T33（清 Redis 断言） |
| AC-14 在线状态 | T31 |
| AC-15 缓存分库（db0） | T32/T33 |

## 6. 退出条件

1. T30–T33 `merged`，L1/L2 全绿；
2. 双客户端 Socket.IO 集成测试（测试客户端模拟双方收发与已读）留档；
3. I3 联调点通过（含双浏览器实测，plan0 §12.3）。

## 7. 风险

| 风险 | 对策 |
| --- | --- |
| Socket.IO 测试与真实客户端行为差异 | I3 双浏览器实测兜底；events.md 逐字段对齐 |
| 未读数 Redis/MySQL 不一致 | Redis 为加速层、列表未读数允许最终一致；详情以 MySQL 回源路径为准 |
| 心跳实现遗漏导致 AC-14 失败 | T31 验收 2 明确续期事件与周期，联调断言 60s 离线 |
