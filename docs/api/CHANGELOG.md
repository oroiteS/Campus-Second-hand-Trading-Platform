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

## [0.3.0] - 2026-10-21 · 批次 2 · both

- 操作人：b2api（契约增量任务 agent，worktree `.worktree/b2api`；规格：[02-商品域](../plan/02-商品域.md)「契约增量全案」节）
- 变更摘要：
  - 新增 `openapi.yaml` 商品域接口 14 个（`paths:`）：products 8——`GET /products`（本校在售分页列表，列表缓存 TTL 120s 为可选优化）、`POST /products`（发布，成功不依赖向量写入结果）、`GET /products/{id}`（详情，异步记录点击行为）、`PUT /products/{id}`（编辑，`image_ids` 全量替换）、`PATCH /products/{id}/status`（上下架流转）、`DELETE /products/{id}`（软删，图片与收藏记录保留）、`GET /products/mine`、`GET /products/search`（向量召回 top 60 + LIKE 降级 + `degraded` 字段，不写缓存）；favorites 3——`POST /products/{id}/favorite`、`DELETE /products/{id}/favorite`（取消幂等）、`GET /favorites/mine`（条目含 `favorited_at`，含 off_sale/sold/trading，deleted 不返回）；categories 1——`GET /categories`（仅启用、不分页、缓存 TTL 3600s）；uploads 1——`POST /uploads`（multipart，`purpose` 本批次仅 `product`，b4 聊天图扩展 `image_message`）；recommendations 1——`GET /recommendations/home`（画像 32 + 随机 8 补足、冷启动全随机 40、`refresh` 换一批）。
  - 新增业务错误码并写入 `info.description` 错误码表：30xx 段二码——3001 商品状态不允许该操作（409）/ 3002 商品已被管理员强制下架（403，仅管理员可恢复）；90xx 段补 9007 方法不支持（405 场景统一走 envelope）。
  - 新增 `components/schemas`：`ProductCondition`（成色 5 档枚举）/ `ProductDetail`（继承 ProductSummary 全字段）/ `ProductCreateInput`（发布/编辑共用，pattern/约束双端同源）/ `ProductStatusActionInput` / `FavoriteActionData`。
  - 新增 `tags`：`products` / `categories` / `favorites` / `recommendations` / `uploads`（`uploads` 为标签规划扩充的通用 tag，b4 聊天图复用）。
  - 修订：上传校验表述四件套 → 五件套（补内容魔数嗅探：PNG 8 字节签名 / JPEG SOI / WEBP RIFF+WEBP）；鉴权节补「图片 Cookie 通道」（login `Set-Cookie img_token` / `GET /images/{id}` 双通道 / logout 清除，仅图片路由接受 Cookie 认证）；`ProductSummary.condition` 由留白 string 定稿为 `ProductCondition` 枚举引用；错误码表 30xx 行由「批次 2 定义」具体化为二码；标签规划行标注批次 2 已建立商品域部分。
  - 修订补登（2026-10-23，P3 用户裁定「禁止收藏自家商品」，提交 `590359be`）：`POST /products/{id}/favorite` 描述与错误示例增补 409/9003「不能收藏自己发布的商品」语义及 `own_product` 示例——纯语义澄清、无 schema 结构变化，版本保持 0.3.0 不 bump；后端校验链、mock 同构与详情页 UI 已随 `fix/b2-fav-own` 五层落地。
- 影响说明：
  - 双端共同：本版本即 b2 双端开发基线，契约冻结为 0.3.0（记入看板「契约冻结版本」列）；任一端发现契约缺陷 → 停手上报契约修订任务，不得私改。
  - 前端：重新生成 `src/api/types.ts` 并同步契约同构 mock 5 个模块（商品发布/详情/列表搜索、收藏、分类选择器、图片上传、首页推荐）。
  - 后端：按冻结契约实现商品域 14 接口（字段校验双端同源独立复验、五件套上传、30xx 错误码、降级标记、Decimal 金额纪律）；b1 存量三处微改——auth 登录 `Set-Cookie img_token`、`GET /images/{id}` 双通道鉴权、405 全局错误统一 envelope（9007）。

---

## [0.2.0] - 2026-10-21 · 批次 1 · both

- 操作人：b1api（契约增量任务 agent，分支 `feat/api/b1-user-domain`；规格：[01-用户域](../plan/01-用户域.md)「契约增量全案」节）
- 变更摘要：
  - 新增 `openapi.yaml` 用户域接口 12 个（`paths:`）：auth 4——`POST /auth/register`、`POST /auth/login`、`POST /auth/logout`（Redis 故障时降级返回 `degraded` 结构）、`POST /auth/password/reset`（凭证不匹配与用户名不存在一律 `422 / 2004`，防探测）；users 4——`GET|PUT /users/me`、`PUT /users/me/password`、`POST /users/me/avatar`（multipart）；certification 2——`POST /certification/applications`（multipart）、`GET /certification/applications/mine`（不分页，个人历史申请量小）；schools 1——`GET /schools`（公开、仅启用、含校区、不分页）；images 1——`GET /images/{id}`（实体二进制不走 envelope；`student_card` 仅本人与管理员可读，越权/不存在一律 `404 / 9002`）。
  - 新增业务错误码 20xx 段六码并写入 `info.description` 错误码表：2001 用户名已存在（409）/ 2002 学号已被注册（409）/ 2003 原密码错误（400）/ 2004 重置凭证不匹配（422）/ 2005 用户名或密码错误（401）/ 2006 账号已被封禁（403）。
  - 新增 `components/schemas`：响应数据 `UserProfile` / `LoginData` / `AuthApplication` / `SchoolWithCampuses`；请求体 `RegisterInput` / `LoginInput` / `PasswordResetInput` / `ProfileUpdateInput` / `PasswordChangeInput`（`username` / `password` / `phone` 等校验 pattern 双端同源落入 schema）。
  - 新增 `tags`：`auth` / `users` / `certification` / `schools` / `images`。
  - 修订文档级遗留：规范引用 v0.4 → v0.5；错误码表 20xx 行由「批次 1 定义」具体化为六码并补「20xx 段为本版本新增」说明；标签规划行标注批次 1 已建立用户域部分（`images` 商品图用途批次 2 扩展）；`bearerAuth` 描述改为「由 `POST /api/auth/login` 签发」；`ImageRef` 描述改为「见 `GET /api/images/{id}`」；`UserSummary.credit_score` 描述补「批次 3 起有评价后非空」。
- 影响说明：
  - 双端共同：本版本即 b1 双端开发基线，契约冻结为 0.2.0（记入看板「契约冻结版本」列）；任一端发现契约缺陷 → 停手上报契约修订任务（`feat/api/b1-<主题>`，代号 `b1api2`），不得私改。
  - 前端：重新生成 `src/api/types.ts` 并同步契约同构 mock（登录 / 注册 / 找回密码 / 认证提交与状态 / 个人中心）。
  - 后端：按冻结契约实现用户域 12 接口（bcrypt 存储纪律、上传四件套、jti 黑名单与登录限流、学生证照片访问控制）。

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
