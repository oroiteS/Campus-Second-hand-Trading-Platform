# API 契约变更记录

_记录 `docs/api/` 下全部契约变更（[openapi.yaml](openapi.yaml) · [websocket-事件.md](websocket-事件.md)）。规则见[项目规范](../plan/00-项目规范.md)「API 契约规范」：开发 agent 不得直接修改契约；修订走 `feat/api/b<批次>-<主题>` 分支并经审查循环，合并后在此登记，双端同步。_

---

## 📋 条目格式

每个版本一个条目，新条目置顶；版本号与 `openapi.yaml` 的 `info.version` 一致：

```text
## [版本] - 日期 · 批次 bN · 影响端 frontend|backend|both
- 操作人：<契约任务的执行者或分支名>
- 变更摘要：
  - <新增|修改|废弃> <文件与位置>：<内容一句话>
- 影响说明：<双端需要做什么适配，无则写"无">
```

---

## [0.1.0] - 2026-10-20 · 批次 0 · both

- 操作人：主 agent（契约基线建立会话，经用户确认范围：仅批次 0；错误码采用分段业务码方案）
- 变更摘要：
  - 新增 `openapi.yaml`：OpenAPI 3.0.3 基线。统一响应体 `{ code, message, data }`；分段业务错误码（10xx 认证权限、90xx 系统通用已定义，20xx–60xx 段位预留）；分页参数（`page`/`page_size`，默认 20 上限 100）与 `PaginatedData` 容器；公共 schema（`UserSummary`、`ProductSummary`、`ImageRef`、`CategoryRef`、`SchoolRef`、`CampusRef`、`SuccessEnvelope`、`ErrorEnvelope`）与 8 个业务枚举（角色/认证/账号/商品/复核/订单/支付/消息类型，值域照需求分析状态机）；可复用错误响应（401/403/404/422/409/429/500）；批次 0 骨架接口 `GET /health`、`GET /openapi.json`、`GET /docs`。
  - 新增 `websocket-事件.md`：Socket.IO 连接与鉴权规范（握手 `auth: { token }`、`connect_error` 复用 REST 错误码、重连与在线状态语义）、事件命名规范、事件总表（8 事件基线；`typing` 标记 P2 不实现仅预留命名）、批次 4 定稿清单。
  - 新增 `CHANGELOG.md`：本文件，含条目格式约定。
- 影响说明：
  - 前端（批次 0）：以 `openapi.yaml` 建立 `openapi-typescript` 类型生成脚本与 `src/api/` 客户端骨架、mock 机制；`/api/health` 为首个可对接接口。
  - 后端（批次 0）：以 `GET /health`（四库连通 + Embedding 模式）、`GET /openapi.json`、`GET /docs`（flask-swagger-ui）为骨架交付项；`src/common/` 统一响应封装与错误码表按本契约实现。
  - 双端共同：后续批次接口须按总则（错误码、分页、时间/金额格式、403/404 隔离语义、降级标记）追加，不得偏离。
