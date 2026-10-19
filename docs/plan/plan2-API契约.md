# plan2 · API 契约

_课程设计项目 · 2026-10-19 · 版本 v1.0 · 状态：待执行_

> **定位**：产出前后端双线唯一共同依赖的接口契约（`docs/api/`），使 D9 的"契约先行、双线并行"成立。本计划是**双线开工的硬前提**。
> **上游**：[plan0-项目规范.md](plan0-项目规范.md)（v1.3，§7.4 契约条款）· [需求分析.md](../需求分析.md)（接口契约表 + 数据模型）· [plan1](plan1-基础设施与工程基线.md)（T06 已合并）
> **下游**：`backend/planB1` 与 `frontend/planF1` 同时开工，此后两线全部 plan 只引用本契约。

---

## 0. 目标与范围

### 目标

1. `docs/api/openapi.yaml` 覆盖需求"接口契约"表全部接口 + 本计划识别的增补接口，每个接口含：请求参数（类型/必填/校验规则/示例）、响应 `data` 完整 schema、错误码与 HTTP 状态、可调用角色。
2. `docs/api/events.md` 覆盖全部 Socket.IO 事件的载荷、时序与错误回执。
3. `docs/api/index.html` 提供零依赖的 Swagger UI 浏览页；后端启动后可 Try it out。
4. 双视角审查通过：前端视角确认"每个页面所需字段齐备无歧义"，后端视角确认"每个接口可从 ER 模型直接实现"。

### 范围内

契约文档本体、Swagger UI 页面、错误码总表、全局约定、联调点断言锚点清单。

### 范围外（D10 明确不做）

- 任何业务代码、任何 mock server、代码生成（flask-smorest / APIFlask）；
- 契约的机器化测试工具（校验以 Swagger UI 成功渲染为准，不引入额外依赖）。

---

## 1. 产物结构

```text
docs/api/
├── openapi.yaml      # REST 全量契约（OpenAPI 3.0，手写、design-first）
├── events.md         # Socket.IO 事件契约（OpenAPI 不覆盖 WS）
└── index.html        # Swagger UI 静态页（CDN 引 swagger-ui-dist，指向 openapi.yaml）
```

维护规则：契约只在此处修改（plan0 §7.4）；`openapi.yaml` 头部注释标版本与变更摘要，每次变更同步 `decisions.md`。

---

## 2. 全局约定（契约的"宪法"）

以下约定写入 `openapi.yaml` 的 `info.description` 与 `events.md` 开头，所有接口默认继承，接口级另有说明者从其说明：

| 主题 | 约定 |
| --- | --- |
| 响应体 | 统一 envelope `{code, message, data}`；`code = 0` 成功，非 0 为业务错误码（`<模块缩写><4位>`，如 `USR1001`） |
| 分页 | 请求 `page` / `page_size`（默认 20、上限 100）；响应 `data` 含 `items` / `total` / `page` / `page_size` |
| 时间 | ISO 8601 带时区（如 `2026-10-19T08:30:00+08:00`）；数据库存 UTC |
| 金额 | **字符串两位小数**（`"125.50"`）——避免 JSON number 精度歧义；评分等整数用 number |
| 鉴权 | `Authorization: Bearer <JWT>`；JWT 载荷含 `sub` / `role` / `auth_status` / `jti` / `exp` |
| 请求追踪 | 所有响应带 `X-Request-Id` 头（NFR-14），前端 client 层有则透传记录 |
| 未认证访问商品域 | **403**（HTTP 403 + 业务码）；非本校资源统一 **404**（防探测） |
| HTTP 映射 | 400 参数校验（message 指出字段名）· 401 未登录/令牌无效/已登出 · 403 未认证或角色不足 · 404 不存在或非本校 · 409 业务冲突（状态机非法迁移/重复收藏/重复申请等）· 429 限流 · 500 服务器错误 |
| 降级标记 | 降级路径成功响应的 `data` 内追加 `degraded: true` 与 `degraded_reason`（AC-17） |
| 图片上传 | 统一 `POST /api/uploads`（multipart/form-data：`file` + `purpose`∈`avatar/student_card/product/chat`）；响应 `{id, url}`，`url` 为相对路径；业务接口只传 `image_id` / `image_ids`，不重复定义上传 |
| 图片读取 | `GET /api/uploads/{id}` 按 `purpose` 分级：`avatar`→任何登录用户；`student_card`→**仅本人与管理员**（NFR-08）；`product`/`chat`→认证学生 |
| 枚举值 | 认证状态 `unverified/pending/approved/rejected`；商品状态 `on_sale/trading/sold/off_sale/deleted`；订单状态 `pending_payment/paid/completed/cancelled/closed`——以 `openapi.yaml` 的 enums 为唯一出处 |

> 金额用字符串、图片统一上传、409 承载业务冲突，是本计划做的三项裁量决策，双视角审查时重点确认。

---

## 3. REST 接口清单与两线映射

`实现` 列 = 后端任务，`消费` 列 = 前端任务。此表是双线对应关系的权威（plan0 §12.1 推进模型）：

| 分组 | 接口（方法 路径） | 实现 | 消费 |
| --- | --- | --- | --- |
| 认证 | POST `/api/auth/register` · POST `/api/auth/login` · POST `/api/auth/logout` · POST `/api/auth/password/reset` | B1·T11 | F1·T41 |
| 用户 | GET/PUT `/api/users/me` · PUT `/api/users/me/password` · POST `/api/users/me/avatar` | B1·T12 | F1·T42 |
| 上传 ★ | POST `/api/uploads` · GET `/api/uploads/{id}` | B1·T12 | F1·T42、F2、F4 |
| 认证申请 | POST `/api/certification/applications` · GET `/api/certification/applications/mine` | B1·T13 | F1·T42 |
| 学校 | GET `/api/schools`（公开，含校区） | B1·T13 | F1·T42 |
| 商品 | GET/POST `/api/products` · GET/PUT/DELETE `/api/products/{id}` · PATCH `/api/products/{id}/status` · POST/DELETE `/api/products/{id}/favorite` · GET `/api/categories` | B2 | F2 |
| 搜索 | GET `/api/products/search` | B3 | F2 |
| 推荐 | GET `/api/recommendations/home` | B3 | F2 |
| 订单 | POST `/api/orders` · GET `/api/orders` · GET `/api/orders/{id}` · POST `…/pay-intent` · GET `…/pay-status` · POST `…/complete` · POST `…/cancel` · POST `…/review` | B4 | F3 |
| 用户主页 | GET `/api/users/{id}` | B4 | F2、F3 |
| 聊天 REST | GET/POST `/api/conversations` · GET `/api/conversations/{id}/messages` · POST `/api/conversations/{id}/read` | B5 | F4 |
| 管理 | GET `/api/admin/certifications` · POST `…/{id}/review` · GET/PATCH `/api/admin/users` · GET `/api/admin/products` · POST `…/{id}/takedown` · GET/POST/PUT `/api/admin/schools` · POST `/api/admin/schools/import` · GET/POST/PUT `/api/admin/categories` · GET `/api/admin/stats/overview` · GET `/api/admin/stats/trend` | B6 | F5 |

★ = 契约对需求接口表的**增补**。增补共四处（撰写时落入契约）：

1. `POST /api/uploads` + `GET /api/uploads/{id}`：统一上传与读取（需求隐含、接口表未列）；
2. `GET /api/admin/logs`：操作日志查询（FR-ADM-09 需要、接口表未列）；
3. `GET /api/admin/products?moderation=pending`：待复核队列过滤参数（FR-ADM-04）；
4. WS `connect_error` 载荷（invalid_token / not_verified），见 §4。

---

## 4. WebSocket 事件契约要点（events.md 承载）

- 连接：`io(API_BASE, { auth: { token } })`；校验失败触发 `connect_error`，载荷 `{ code, message }`（`CHT1001` 无效令牌 / `CHT1002` 未认证）。
- 事件对：`message:send → message:ack`（携 `client_msg_id` 幂等）、`message:new`、`message:read`、`presence:update`；`typing` 为 P2 **不写入契约**。
- 每个事件给出：载荷 schema（字段/类型/必填）、成功与失败示例 JSON、时序说明（谁发、谁收、何时）。

---

## 5. 任务卡

### T07 契约撰写（主代理执行，产物入库走一次审查）

- **目标**：产出 §1 全部三个文件，覆盖 §3 清单与 §4 事件
- **前置依赖**：plan1 全部合并（T06 文档已建）；**不需要**任何业务代码存在
- **required_skills**：无（纯文档；撰写时对照需求分析的数据模型与业务规则章节）
- **owns**：`docs/api/**`、`docs/plan/plan2-API契约.md`
- **reads**：需求分析 §接口契约、§数据设计、§关键业务规则、§推荐与搜索；plan0 §6.2
- **forbidden**：`campus_backend/**`、`campus_frontend/**`、`scripts/**`、`docker-compose.yml`
- **验收标准**：
  1. `openapi.yaml` 覆盖 §3 清单全部接口（含 ★ 增补），每接口齐备：参数表、`data` schema、错误码列表、角色标注、请求/响应示例 JSON；
  2. 全局约定（§2）逐条落入 `info.description`；错误码总表成节；
  3. `events.md` 覆盖 §4 全部事件与 `connect_error`；
  4. 浏览器打开 `docs/api/index.html`：Swagger UI 成功渲染、全部分组可见、schema 无解析错误（渲染失败即结构无效，以此代替机器校验）；
  5. 为 I1–I4 每个联调点输出**断言锚点清单**（该点涉及的接口 + 必查字段），供 smoke.py 后续实现；
  6. 双视角审查各一轮 PASS：前端视角（页面所需字段齐备、无歧义命名）、后端视角（可从 ER 模型直接实现、状态码与错误码完备）。
- **门禁命令**：无代码门禁；以验收 4 的渲染结果为结构校验
- **交付物**：`docs/api/` 三文件 + 双视角审查报告（存 `docs/plan/reviews/`）
- **规模预期**：openapi.yaml 约 1500–2000 行 + events.md 约 200 行
- **备注**：撰写顺序建议——先全局约定与 schemas（User/School/Product/Order/Conversation 等公共组件），再按分组填充 paths，最后 events.md 与锚点清单。

---

## 6. 契约变更流程（双线并行期间生效）

1. 任何接口变更**先改 `docs/api/`，再改代码**（plan0 §7.4）；
2. 变更提交信息带 `Contract:` 前缀，并在 `decisions.md` 登记；
3. 主代理评估影响面：仅本线→本线任务消化；跨线→在下一个联调点之前通知对端 plan，必要时新增对端修复任务；
4. 已合并域的契约变更，其 smoke 断言同步更新。

## 7. 验收映射

本计划不直接覆盖任何 AC，但为 AC-02/03/05/07~19 的**前后端一致性**提供唯一依据；`docs/api/index.html` 本身支撑答辩讲解（接口全貌一页可见）。

## 8. 退出条件

1. T07 合并，双视角审查报告均 PASS 且无未关闭阻塞项；
2. Swagger UI 渲染验收通过（验收标准 4）；
3. I1–I4 锚点清单就位，smoke.py 具备可对接的断言依据；
4. `backend/planB1` 与 `frontend/planF1` 可立即开工：任务卡契约引用有效、无环境阻塞。

## 9. 与规范的双向核对

- plan0 §7.4 的五条契约条款逐条落实（唯一源、锚点引用、先契约后代码、smoke 以契约为准、WS 受约束）；
- 若撰写中发现需求分析本身的接口缺口（如 §3 的 ★ 项），在本文档登记增补理由，**不回改需求文档的表格**，以 `docs/api/` 为字段级权威。
