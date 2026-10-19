# planB3 · 后端：搜索推荐与向量

_课程设计项目 · 2026-10-19 · 版本 v1.0 · 状态：待执行_

> **定位**：backend 线第三域，项目的**算法核心**。Embedding 双模端点、向量化管道、画像系统、语义搜索、首页推荐与全部降级路径——答辩技术含量主要出自本域。
> **上游**：[plan0](../plan0-项目规范.md) · [plan2](../plan2-API契约.md) · planB2 已合并（含 `on_product_changed` / `on_favorite` 钩子）
> **对端**：[frontend/planF2](../frontend/planF2-商品浏览与发布.md) —— 并行，与 B2 共同触发**联调点 I2**。

---

## 0. 目标与范围

### 目标

1. FR-GDS-05（向量搜索）/ FR-GDS-06（首页推荐）后端实现；
2. Embedding 端点双模（云端优先、本地兜底，AC-18）与显式降级（AC-17）；
3. MongoDB 三集合（user_profiles / user_behaviors / product_vectors）与 Chroma 集合的读写链路、向量一致性（重试队列 + 全量重建）；
4. 画像更新算法落地（AC-08）与推荐配比（AC-07）。

### 前置条件（用户负责，D11）

`.env` 中 `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL` / `EMBEDDING_DIM` 已配置且端点可用（云端或本地兜底服务任一）。本域任务**不包含**模型下载与推理环境搭建；本地兜底服务脚本属交付物（T20），运行环境由用户提供。

### 范围内

extensions 的 mongo/chroma 客户端真实化、Embedding 客户端与探测、向量管道与补偿任务、搜索、画像与行为埋点（**替换 B2 两钩子 + 详情点击埋点**）、首页推荐、种子向量批量构建、降级测试。

### 范围外

订单/评价（B4）；聊天（B5）；管理域（B6）；购买行为埋点的**触发点**（订单完成时调用，归 B4，本域只提供 `behavior_service.record_purchase`）。

---

## 1. 契约引用

`/api/products/search`（GET）· `/api/recommendations/home`（GET，含 `refresh` 参数）；`data.degraded` / `degraded_reason` 字段约定（plan2 §2）；`/api/health` 的 `embedding.mode`。

## 2. 对端对应关系

| 本计划任务 | 对端消费 | 汇合点 |
| --- | --- | --- |
| T22 搜索 | F2·T45 搜索框 | I2 |
| T24 首页推荐 | F2·T45 推荐区 + 换一批 | I2 |

## 3. 任务卡（线内串行：T20 → T21 → T22 → T23 → T24）

### T20 Embedding 客户端与端点探测

- **目标**：AC-18 双模；health 真实化
- **前置依赖**：planB2 已合并
- **required_skills**：flask-backend
- **owns**：`campus_backend/src/services/embedding_client.py`、`campus_backend/src/services/health_service.py`、`scripts/serve_embedding.py`、`campus_backend/tests/test_embedding.py`
- **reads**：需求 §Embedding 端点；plan2 `/api/health` 定义
- **forbidden**：`models/**`、`migrations/**`、`campus_frontend/**`
- **验收标准**：
  1. OpenAI 兼容客户端：`/v1/embeddings` 调用、超时与重试（1 次）、异常分类（网络/鉴权/限流）；
  2. 启动探测：云端配置且探测通过→`cloud`；否则本地端点探测→`local`；均失败→`unavailable`（不阻止应用启动）；模式写日志并进 `/api/health` 的 `data.embedding.mode`；
  3. **运行中故障切换**：请求失败时按配置降级并置进程级标记，恢复探测每 60s 一次；
  4. `scripts/serve_embedding.py`：进程内加载本地模型的 OpenAI 兼容服务（`/v1/embeddings` `/v1/models`），模型路径/端口走 env；**本机无模型权重时给出明确启动失败信息**（权重由用户准备，D11）；
  5. 维度自检：探测时校验返回维度 == `EMBEDDING_DIM`，不一致报错并指引重建集合（需求 §维度说明）；
  6. pytest（fake 端点注入，不依赖真实服务）全绿。
- **门禁命令**：§9 L1 + L2
- **规模预期**：约 350 行

### T21 向量化管道与一致性

- **目标**：发布/编辑→Mongo 权威副本→Chroma upsert；失败补偿；全量重建
- **前置依赖**：T20
- **required_skills**：flask-backend
- **owns**：`campus_backend/src/services/vector_service.py`、`campus_backend/src/tasks/vector_retry.py`、`campus_backend/src/services/product_service.py`（**仅限替换 `on_product_changed` 钩子实现**）、`scripts/rebuild_vectors.py`、`scripts/seed.py`（向量批量构建接入）、`campus_backend/tests/test_vector_pipeline.py`
- **reads**：需求 §商品向量化、§向量一致性约定；planB2 交付报告（钩子签名）
- **forbidden**：`models/**`、`migrations/**`、`campus_frontend/**`、product_service 其他函数
- **验收标准**：
  1. 文本模板拼接（标题/分类/成色/描述）与 `text_hash` 记录；**hash 未变跳过重建**；
  2. 写序：先 Mongo `product_vectors`（权威），再 Chroma upsert（含 metadata：school/campus/category/price/status/seller）；Chroma 失败→Redis db3 `queue:vector:retry` + 日志告警，60s 补偿任务重放（APScheduler）；
  3. 商品状态变更（sold/off_sale/deleted）同步更新 Chroma metadata 的 status（或从集合移除，二选一入档）；
  4. `scripts/rebuild_vectors.py`：以 Mongo 为准全量重建 Chroma（清空集合→批量 upsert），180 商品可执行并输出耗时；
  5. 种子接入：`seed.py` 完成后商品向量全部就位（Mongo 与 Chroma 计数一致）；README 注明云端/本地两种模式预期耗时（需求 §种子数据）；
  6. Embedding 不可用时发布**仍成功**、商品标记"向量待生成"（重试队列承接），接口不报错（降级表第 1 行）；
  7. pytest 全绿（含 Chroma 写失败注入用例）。
- **门禁命令**：§9 L1 + L2
- **规模预期**：约 400 行

### T22 语义搜索

- **目标**：FR-GDS-05 + 降级
- **前置依赖**：T21
- **required_skills**：flask-backend
- **owns**：`campus_backend/src/services/search_service.py`、`campus_backend/src/routes/search.py`（或在 products 路由文件新增——与 B2 owns 协商）、`campus_backend/tests/test_search.py`
- **reads**：需求 §搜索（两段式链路、召回 60、指令前缀）；plan2 锚点
- **forbidden**：`models/**`、`migrations/**`、`campus_frontend/**`
- **验收标准**：
  1. 查询拼接指令前缀（前缀为配置项 `EMBEDDING_QUERY_PREFIX`，随端点可调——需求 §商品向量化）→ 向量化 → Chroma 召回 top 60（`where` 固定注入 `school_id` + `status=on_sale`，plan0 §6.2 规则 3）；
  2. MySQL 精筛（分类/价格/成色），按原始相似度排序分页；**结果全部同校**（AC-09 断言）；
  3. 空关键词退化为普通列表接口语义（调用 B2 查询服务）；
  4. 降级：Embedding/Chroma 不可用→MySQL `LIKE` 标题匹配 + `degraded: true` + `degraded_reason`（AC-17 半边）；
  5. 语义验证：AC-09 场景——搜"机械键盘"能召回标题不含该词但描述相关的种子商品（测试用种子数据固定断言 ≥1 条）；
  6. 搜索结果**不写缓存**（需求 §搜索）；pytest 全绿。
- **门禁命令**：§9 L1 + L2
- **规模预期**：约 300 行

### T23 画像与行为系统

- **目标**：AC-08 画像更新；三类行为埋点
- **前置依赖**：T21
- **required_skills**：flask-backend
- **owns**：`campus_backend/src/services/behavior_service.py`、`campus_backend/src/services/profile_service.py`、`campus_backend/src/services/product_query_service.py`（**仅限详情点击埋点接入**）、`campus_backend/src/services/favorite_service.py`（**仅限替换 `on_favorite` 钩子**）、`campus_backend/tests/test_profile.py`
- **reads**：需求 §用户画像更新（权重表、公式、L2、24h 去重、behavior_count）
- **forbidden**：`models/**`、`migrations/**`、`campus_frontend/**`、两 service 文件的其他函数
- **验收标准**：
  1. `user_behaviors` 流水：click/favorite/purchase 三类，含 weight/source/school_id，只增不改；索引 `(user_id, created_at)`、`(product_id)` 就位（Mongo 初始化脚本或首次写入时建）；
  2. 画像更新：公式 `new = product_vec×(1-w) + old×w`（购买 0.55 / 收藏 0.70 / 点击 0.82）；无画像首次直接取商品向量；更新后 **L2 归一化（模长=1，AC-08 断言）**；`behavior_count` 递增；
  3. 24h 同用户同商品同行为只更新一次画像（流水照记）；
  4. 埋点接入：详情接口（click）、收藏钩子（favorite）真实生效；`record_purchase(user, product)` 供 B4 调用（签名入档）；
  5. 画像更新失败不阻塞主流程（收藏/下单照常成功，进入重试，需求 §收藏与画像）；
  6. 行为权重、去重窗口做成 `common/constants.py` 常量；
  7. pytest 全绿（含归一化、24h 去重、首行为特例）。
- **门禁命令**：§9 L1 + L2
- **规模预期**：约 350 行

### T24 首页推荐

- **目标**：FR-GDS-06 + AC-07
- **前置依赖**：T22、T23
- **required_skills**：flask-backend
- **owns**：`campus_backend/src/services/recommend_service.py`、`campus_backend/src/routes/recommendations.py`、`campus_backend/tests/test_recommend.py`
- **reads**：需求 §首页推荐（40=32+8、冷启动、过滤规则、缓存、换一批）
- **forbidden**：`models/**`、`migrations/**`、`campus_frontend/**`
- **验收标准**：
  1. 有画像：Chroma 以用户向量为查询召回 top 60 → 过滤（已售/自己发布/重复）取 32 + MySQL 随机补足 8，合并去重 40；召回不足随机补齐缺口；
  2. 冷启动（无画像文档）：40 全随机本校 on_sale；
  3. `where` 注入 school_id + on_sale；**结果绝不含他校与自己发布**（断言）；
  4. 缓存 `product:home:{school}:{user}` TTL 300s；`?refresh=1` 强制重算（换一批）；
  5. 降级：Embedding/Chroma/Mongo 任一不可用→全随机 + `degraded` 标记（AC-17 完整落地）；
  6. 随机部分占比可观测：响应 data 带 `mix: {profiled: n, random: m}`（演示与 AC-07 断言用，契约已含此字段则对齐）；
  7. pytest 全绿。
- **门禁命令**：§9 L1 + L2
- **规模预期**：约 300 行

---

## 4. 依赖与顺序

T20 → T21 → T22 → T23 → T24（T22/T23 可在 T21 后由主代理视并行度安排，二者 owns 无交集）。

## 5. 验收映射

| 需求/验收 | 承载 |
| --- | --- |
| FR-GDS-05 / FR-GDS-06 | T22 / T24 |
| AC-07 推荐配比 | T24 |
| AC-08 画像更新与归一化 | T23 |
| AC-09 语义搜索跨词召回 | T22 |
| AC-17 降级可见 | T22 / T24 |
| AC-18 端点双模 | T20 |
| NFR-01 首页 P95<1.5s | T24（终验压测在 planI1） |

## 6. 退出条件

1. T20–T24 `merged`，L1/L2 全绿；
2. **真实端点验证一次**（cloud 或 local 模式，任一）：种子 180 商品向量化成功、搜索与推荐返回语义合理结果（用户 .env 就位后执行，证据入审查报告）；
3. I2 联调点通过（与 B2、F2 共同，plan0 §12.3）。

## 7. 风险

| 风险 | 对策 |
| --- | --- |
| 用户端点在任务执行时不可用 | 测试全部走 fake 注入；真实端点验证留到 I2 前置，不阻塞合并 |
| 本地兜底模型内存/耗时超预期 | serve_embedding 独立进程隔离主应用；README 注明首次运行耗时 |
| 维度切换导致集合不一致 | T20 维度自检 + rebuild 脚本兜底 |
| 埋点改动越界（触碰 B2 文件其他函数） | owns 限定"仅钩子行"，审查以 diff 范围核 |
