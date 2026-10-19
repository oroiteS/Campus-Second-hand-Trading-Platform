# planF4 · 前端：实时聊天

_课程设计项目 · 2026-10-19 · 版本 v1.0 · 状态：待执行_

> **定位**：frontend 线第四域。Socket.IO 客户端、会话列表、聊天窗、已读与在线状态——演示脚本第 8 步双屏实时消息的舞台。
> **上游**：[plan0](../plan0-项目规范.md) · [plan2](../plan2-API契约.md)（含 `docs/api/events.md`）· planF3 已合并
> **对端**：[backend/planB5](../backend/planB5-实时聊天.md) —— 并行，与 B4、F3 共同触发**联调点 I3**。

---

## 0. 目标与范围

### 目标

1. FR-CHT-01 ~ FR-CHT-07 前端（P2 typing 不做，界面无此元素）；
2. `socket.ts` 客户端封装（token 连接、断线重连、事件类型安全）供全局复用；
3. 从商品详情与用户主页发起聊天（接通 F2 占位按钮与 F3 主页入口）。

### 范围内

socket 客户端层、会话列表页、聊天窗（历史分页、文本/图片、已读）、在线状态、聊天入口接通、未读全局角标。

### 范围外

typing 任何 UI（P2）；消息撤回（需求不支持）；管理端聊天。

---

## 1. 契约引用

REST：`/api/conversations`（GET/POST）· `…/{id}/messages` · `…/{id}/read`。WS：`events.md` 全部事件与 `connect_error` 载荷（CHT1001/CHT1002）。

## 2. 对端对应关系

| 本计划任务 | 对端实现 | 汇合点 |
| --- | --- | --- |
| T55 socket 层 | B5·T31 | I3 |
| T56 会话与聊天窗 | B5·T32/T33 | I3 |
| T57 已读与在线 | B5·T31/T33 | I3 |

## 3. mock 边界

B5 合并前 mock：socket 层用 mock 事件总线（定时假消息注入）；会话/消息走 REST mock。I3 关 mock，双浏览器实测。

## 4. 任务卡（线内串行：T55 → T56 → T57）

### T55 Socket 客户端层

- **目标**：FR-CHT-01 前端地基
- **前置依赖**：planF3 已合并
- **required_skills**：frontend-designer
- **owns**：`campus_frontend/src/api/socket.ts`、`src/hooks/useSocket.ts`、`src/store/presence.ts`、相关 `.types.ts` / 测试
- **reads**：`docs/api/events.md`（逐事件载荷）；Vite 代理 `/socket.io`（plan1 T03 已配）
- **forbidden**：`campus_backend/**`
- **验收标准**：
  1. 连接：`auth: { token }` 登录后建立、登出断开；`connect_error` 按 CHT1001/1002 区分处理（1002 引导去认证页）；
  2. 心跳：按 events.md 周期续期（对齐后端 60s TTL 的客户端半边）；
  3. 断线重连：指数退避 + 最多 5 次，重连后重拉会话列表与未读（防丢消息）；
  4. 事件类型安全：所有事件载荷有 TS 类型（从 events.md 逐字段生成），`useSocket` 订阅/退订清理无泄漏；
  5. 单测（mock io）覆盖连接、错误分流、重连上限。
- **门禁命令**：§9 L1
- **规模预期**：约 300 行

### T56 会话列表与聊天窗

- **目标**：FR-CHT-02/03/04/07 前端
- **前置依赖**：T55
- **required_skills**：frontend-designer
- **owns**：`campus_frontend/src/pages/Chat.tsx`、`src/components/ConversationList.tsx`、`src/components/ChatWindow.tsx`、`src/components/MessageBubble.tsx`、`src/api/conversations.ts`、相关测试
- **reads**：events.md（message:send/ack/new 时序）；plan2 REST 锚点
- **forbidden**：`campus_backend/**`、`src/pages/ProductDetail.tsx`（入口接通经主代理协调 owns）
- **验收标准**：
  1. 会话列表：按最后消息倒序、对方展示名、摘要（图片显示"[图片]"）、未读红点；顶栏消息图标角标全局同步；
  2. 聊天窗：历史消息向上分页加载（滚动位置保持）；文本框（Enter 发送/Shift+Enter 换行）；发送后**先乐观渲染（pending 态）收到 ack 转正**，失败标红重试；`client_msg_id` 生成去重；
  3. 图片消息：复用统一上传（purpose=chat）、预览、灯箱放大；
  4. 实时接收：`message:new` 即时追加（窗口打开时）；非当前会话进未读；
  5. 发起聊天：详情页"聊一聊"与用户主页"发消息"→POST conversations→跳窗（复用既有会话）；跨校 404 文案化；
  6. 三态 + 可访问性（消息列表 aria-live="polite"、输入框 label）；
  7. 门禁全绿 + 乐观更新与去重测试。
- **门禁命令**：§9 L1
- **规模预期**：约 550 行

### T57 已读与在线状态

- **目标**：FR-CHT-05/06 前端 + AC-14 展示
- **前置依赖**：T56
- **required_skills**：frontend-designer
- **owns**：`campus_frontend/src/hooks/useReadState.ts`、`src/components/PresenceDot.tsx`、`src/store/unread.ts`、相关测试
- **reads**：events.md（message:read / presence:update）
- **forbidden**：`campus_backend/**`
- **验收标准**：
  1. 进入会话自动上报已读（`message:read` 携最后消息 id）；本地未读清零即时；
  2. 对端已读回执：我的消息气泡显示已读/未读态；
  3. 在线状态：`presence:update` 驱动绿点/灰点；**60s 无心跳对端转离线**（AC-14 展示口径，本地兜底计时）；
  4. 未读 store：会话级未读与全局角标一致，登出清零；
  5. 门禁全绿 + 已读上报与在线切换测试。
- **门禁命令**：§9 L1
- **规模预期**：约 250 行

---

## 5. 依赖与顺序

T55 → T56 → T57；与 B5 并行。

## 6. 验收映射

| 需求/验收 | 承载 |
| --- | --- |
| FR-CHT-01~07 前端 | T55–T57 |
| AC-13 双浏览器实测（前端半边） | T56 |
| AC-14 在线离线展示 | T57 |
| 演示脚本步骤 8 | T56 |

## 7. 退出条件

1. T55–T57 `merged`，L1 全绿；
2. I3 联调点通过：双浏览器互发、刷新历史仍在、已读与在线（plan0 §12.3）。

## 8. 风险

| 风险 | 对策 |
| --- | --- |
| 乐观更新与 ack 乱序 | client_msg_id 去重 + 超时未 ack 标失败；测试覆盖 |
| 重连后消息缺口 | 重连触发会话重拉（T55 验收 3）；缺口兜底靠历史分页 |
| 详情页入口接通的 owns 交叉 | 入口按钮改动经主代理在 T56 合并时统一处理（plan0 §2.2 共享文件规则） |
