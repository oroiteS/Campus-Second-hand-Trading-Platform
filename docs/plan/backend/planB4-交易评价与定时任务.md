# planB4 · 后端：交易评价与定时任务

_课程设计项目 · 2026-10-19 · 版本 v1.0 · 状态：待执行_

> **定位**：backend 线第四域。订单状态机、模拟支付、超时关单、评价信誉、用户主页——交易闭环的全部后端。
> **上游**：[plan0](../plan0-项目规范.md) · [plan2](../plan2-API契约.md) · planB2/B3 已合并
> **对端**：[frontend/planF3](../frontend/planF3-交易流程.md) —— 并行，与 B5、F3/F4 共同触发**联调点 I3**。

---

## 0. 目标与范围

### 目标

1. FR-ORD-01 ~ FR-ORD-10 全部后端实现（含 P1 的已支付取消、超时关单）；
2. FR-USR-11 用户主页（依赖本域评价数据就位，从 B1 移入）；
3. 订单状态机测试矩阵与并发下单锁（plan0 §9 必测 3/4）；
4. 卖家信誉分（Redis db1 缓存 + 增量重算），回填 B2 详情页 `seller.credit_score`。

### 范围内

`models/trade.py` 四表（Order / OrderStatusLog / Payment / Review）、迁移与种子（30 历史订单评价）、下单锁、支付模拟、确认/取消/超时、评价与信誉、用户主页、购买行为埋点接入（调 B3 `record_purchase`）、订单域缓存失效。

### 范围外

聊天（B5）；管理域处置（B6）；支付渠道任何真实对接（反目标）；`pay-status` 恒成功以外的任何支付逻辑（需求 §模拟支付规则）。

---

## 1. 契约引用

`/api/orders`（POST/GET）· `/api/orders/{id}`（GET）· `…/pay-intent` · `…/pay-status` · `…/complete` · `…/cancel` · `…/review`（均 POST）· `/api/users/{id}`（GET，用户主页）。

## 2. 对端对应关系

| 本计划任务 | 对端消费 | 汇合点 |
| --- | --- | --- |
| T26 下单与订单列表 | F3·T50 | I3 |
| T27 支付与完成 | F3·T51 | I3 |
| T28 取消/超时/评价/主页 | F3·T52、F2·T46 | I3 |

## 3. 任务卡（线内串行：T25 → T26 → T27 → T28）

### T25 交易域模型、迁移与种子

- **目标**：Order / OrderStatusLog / Payment / Review 四表 + 历史数据种子
- **前置依赖**：planB3 已合并（种子商品已有向量，购买行为埋点可联动）
- **required_skills**：flask-backend
- **owns**：`campus_backend/src/models/trade.py`、`migrations/versions/<交易域迁移>`、`scripts/seedlib/trade.py`
- **reads**：需求 §数据设计（交易与沟通域 ER、索引要点）
- **forbidden**：`routes/**`、`services/**`、`campus_frontend/**`、B1/B2 模型文件
- **验收标准**：
  1. 四表字段与 ER 图一致；索引 `uk_order_no`、`idx_buyer_status`、`idx_seller_status`、`idx_school_created`、`uk_order`（reviews）、`idx_reviewee` 就位；
  2. 种子：30 条历史订单（覆盖 completed/cancelled/closed 各态）+ 对应评价（评分分布拉开，使信誉分有区分度）+ 状态流水 + 支付记录；幂等；
  3. 种子订单的 `school_id` 冗余与商品一致；订单号 `order_no` 规则统一（日期+序列，入 constants）；
  4. 迁移 upgrade/downgrade 可执行、单头；pytest 模型冒烟全绿。
- **门禁命令**：§9 L1 + L2
- **规模预期**：约 400 行

### T26 订单创建与列表详情

- **目标**：FR-ORD-01/02/03/10 + AC-10 并发锁
- **前置依赖**：T25
- **required_skills**：flask-backend
- **owns**：`campus_backend/src/routes/orders.py`、`campus_backend/src/services/order_service.py`、`campus_backend/tests/test_orders.py`
- **reads**：需求 §订单与支付（状态机图）；plan2 锚点；B2 缓存失效约定
- **forbidden**：`models/**`、`migrations/**`、`campus_frontend/**`
- **验收标准**：
  1. 下单：商品必须本校 on_sale（否则 404）；**不能买自己商品**（409 `ORD3001`）；deal_place/buyer_remark 可选；订单即 `pending_payment`、商品置 `trading`、写首条状态流水；
  2. 并发锁：Redis db3 `lock:product:{id}`（TTL 10s）+ DB 状态二次校验；**两并发仅一单成功，另一 409"商品已被锁定"（AC-10 断言，并发测试用例必测）**；
  3. 锁获取失败/超时的释放路径有测试；
  4. 列表：`role=buyer|seller` 区分我买到/我卖出，状态筛选分页；仅本人订单；
  5. 详情：商品快照（标题/图片/价格，取下单时点字段——快照字段冗余进 order 或 join 现值，**采用冗余快照**入档）、金额、状态、时间线（状态流水列表）；
  6. 下单成功失效商品 detail/list/home 缓存；
  7. pytest 全绿。
- **门禁命令**：§9 L1 + L2
- **规模预期**：约 400 行

### T27 模拟支付与交易确认

- **目标**：FR-ORD-04/05 + AC-11/AC-12 前半
- **前置依赖**：T26
- **required_skills**：flask-backend
- **owns**：`campus_backend/src/services/payment_service.py`、`campus_backend/src/routes/payments.py`（或并入 orders 路由文件）、`campus_backend/tests/test_payment.py`
- **reads**：需求 §模拟支付规则、§模拟支付时序图；plan2 锚点
- **forbidden**：`models/**`、`migrations/**`、`campus_frontend/**`
- **验收标准**：
  1. `pay-intent`：仅买家、仅 pending_payment 态（否则 409）；创建 Payment 记录（channel 微信/支付宝由请求指定）、返回固定二维码资源（内容为固定一句话文案，需求规则 2）；
  2. `pay-status`：**一律返回成功**并推进订单 `paid`、写支付流水与状态流水、记录 paid_at、失效缓存；重复轮询幂等（已 paid 再查不重复推进）；
  3. `complete`：仅买家、仅 paid 态；订单 `completed`、商品 `sold` + sold_at、写流水、失效缓存；
  4. 状态机矩阵测试：全部合法边（pending→paid/cancelled/closed、paid→completed/cancelled）通过，全部非法边（completed→*、cancelled→* 等）409；
  5. 完成时调用 B3 `behavior_service.record_purchase`（购买画像，AC-08 链路终点；失败不阻塞订单）；
  6. pytest 全绿。
- **门禁命令**：§9 L1 + L2
- **规模预期**：约 350 行

### T28 取消、超时、评价与用户主页

- **目标**：FR-ORD-06/07/08/09 + FR-USR-11；P1 三件套收口
- **前置依赖**：T27
- **required_skills**：flask-backend
- **owns**：`campus_backend/src/services/review_service.py`、`campus_backend/src/tasks/order_timeout.py`、`campus_backend/src/routes/reviews.py`、`campus_backend/src/routes/users_public.py`、`campus_backend/src/services/credit_service.py`、`campus_backend/tests/test_review_timeout.py`
- **reads**：需求 §订单与支付（取消与超时规则）、§评价与信誉；plan2 锚点
- **forbidden**：`models/**`、`migrations/**`、`campus_frontend/**`
- **验收标准**：
  1. 待支付取消：买家可取消，商品回 `on_sale`、订单 `cancelled`、写流水；
  2. 已支付取消：买家发起，订单 `cancelled`、商品回 `on_sale`、Payment 置 `refunded`、写流水（协商取消语义，需求 §取消与超时规则）；
  3. 超时关单：APScheduler 每 60s 扫描 `pending_payment` 且 `created_at + 30min < now`（窗口做成常量，测试可调），置 `closed`、释放商品、写流水；测试环境注入时钟验证；**测试环境禁用调度**（plan0 §3.1）以手动触发函数测试；
  4. 评价：仅 completed 订单买家、30 天窗口、一单一评（重复 409 `ORD3002`）、1–5 星必填、文字 0–500 字；无评价卖家展示"暂无"（FR-ORD-09）；
  5. 信誉分：算术平均两位小数，缓存 Redis db1 `review:user:{id}:stats`（HASH：条数/均值/星级分布），新增评价增量重算；**回填 B2 详情 `seller.credit_score`**（修改点限 product_query_service 读取处）；
  6. 用户主页 `GET /api/users/{id}`：仅同校认证学生（他校 404）；返回展示名、信誉分、在售商品数（本校 on_sale 计数）、收到的评价分页列表；
  7. pytest 全绿（含超时窗口、重复评价、他校主页 404）。
- **门禁命令**：§9 L1 + L2
- **规模预期**：约 450 行

---

## 4. 依赖与顺序

T25 → T26 → T27 → T28；与 frontend/planF3 并行，I3 联调需 **B5、F4 亦合并**（plan0 §12.3）。

## 5. 验收映射

| 需求/验收 | 承载 |
| --- | --- |
| FR-ORD-01~10、FR-USR-11 | T25–T28 |
| AC-10 并发下单 | T26 |
| AC-11 模拟支付、AC-12 交易闭环 | T27/T28 |
| AC-16 统计数据源（订单/成交额） | T25 种子 + B6 消费 |
| plan0 §9 必测 3（状态机）/4（并发）/5（信誉分） | T26/T27/T28 |

## 6. 退出条件

1. T25–T28 `merged`，L1/L2 全绿；
2. 状态机矩阵（全部合法/非法边）与并发锁测试在审查报告留档；
3. 信誉分在商品详情可见（B2 回填生效）、用户主页四要素齐备。

## 7. 风险

| 风险 | 对策 |
| --- | --- |
| Redis 锁与 DB 事务双重保障的边界（锁内事务失败） | 锁释放放 finally；DB 状态二次校验兜底；并发测试覆盖锁内失败路径 |
| 超时任务与取消竞态（同时触发） | 状态推进统一走"当前态校验 + UPDATE where status"乐观并发；测试注入双触发 |
| 快照语义歧义（编辑商品后订单详情） | 采用冗余快照并在契约 examples 标注"下单时点" |
