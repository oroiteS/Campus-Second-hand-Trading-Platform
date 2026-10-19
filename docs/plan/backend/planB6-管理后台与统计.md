# planB6 · 后端：管理后台与统计

_课程设计项目 · 2026-10-19 · 版本 v1.0 · 状态：待执行_

> **定位**：backend 线第六域（终域）。管理侧全部能力：认证审核、用户与商品处置、敏感词、学校与分类维护、批量导入、统计、操作日志。FR-ADM-01~09 + FR-GDS-09 收口。
> **上游**：[plan0](../plan0-项目规范.md) · [plan2](../plan2-API契约.md) · planB5 已合并（backend 线全部前置就绪）
> **对端**：[frontend/planF5](../frontend/planF5-管理后台.md) —— 并行，共同触发**联调点 I4**。

---

## 0. 目标与范围

### 目标

1. FR-ADM-01 ~ FR-ADM-09 后端全部实现（含 P1 待复核队列、操作日志、分类管理）；
2. 管理员权限层：`role=admin` 校验装饰器 + 跨校只读/处置（`g.scope_all`）+ **不能发布商品或下单**（需求 §角色定义，测试断言）；
3. 敏感词匹配接入商品发布链路（替换 B2 预留点）；认证审核闭环（调 B1 `approve` 服务）。

### 范围内

`models/admin.py`（AdminLog、SensitiveWord）、迁移与种子、审核、用户管理、商品处置、待复核、敏感词服务、学校 CRUD 与 csv/xlsx 导入、分类 CRUD、统计两接口、操作日志查询、admin 权限装饰器、本域 pytest。

### 范围外

前端任何内容（F5）；聊天监管；数据导出。

---

## 1. 契约引用

`/api/admin/certifications`（GET）· `…/{id}/review`（POST）· `/api/admin/users`（GET/PATCH）· `/api/admin/products`（GET，含 `moderation=pending` 过滤）· `…/{id}/takedown`（POST）· `/api/admin/schools`（GET/POST/PUT）· `…/import`（POST）· `/api/admin/categories`（GET/POST/PUT）· `/api/admin/stats/overview` · `/api/admin/stats/trend` · `/api/admin/logs`（GET，契约增补项）。

## 2. 对端对应关系

| 本计划任务 | 对端消费 | 汇合点 |
| --- | --- | --- |
| T36 审核+用户管理 | F5·T61 | I4 |
| T37 处置+待复核 | F5·T62 | I4 |
| T38 学校+导入 | F5·T63 | I4 |
| T39 统计+分类+日志 | F5·T64 | I4 |

## 3. 任务卡（线内串行：T35 → T36 → T37 → T38 → T39）

### T35 管理域模型、迁移与种子

- **目标**：AdminLog / SensitiveWord 两表 + 敏感词种子
- **前置依赖**：planB5 已合并
- **required_skills**：flask-backend
- **owns**：`campus_backend/src/models/admin.py`、`migrations/versions/<管理域迁移>`、`scripts/seedlib/admin.py`
- **reads**：需求 FR-ADM-04/09；plan2 锚点
- **forbidden**：`routes/**`、`services/**`、`campus_frontend/**`
- **验收标准**：
  1. 两表结构与契约一致（AdminLog：操作人/对象类型/对象 id/动作/原因/时间；SensitiveWord：词、等级、启用）；
  2. 种子：敏感词 8–12 个（含演示用明显违规词与误报边界词各若干）；B2 已预置 1 件待复核商品种子；
  3. `@admin_required` 装饰器（叠加于 `@login_required`）+ 单测（学生访问 403、管理员通过）；
  4. 迁移可逆、单头；pytest 冒烟全绿。
- **门禁命令**：§9 L1 + L2
- **规模预期**：约 250 行

### T36 认证审核与用户管理

- **目标**：FR-ADM-01/02 + AC-05 审核半边
- **前置依赖**：T35
- **required_skills**：flask-backend
- **owns**：`campus_backend/src/routes/admin_certifications.py`、`campus_backend/src/routes/admin_users.py`、`campus_backend/src/services/admin_user_service.py`、`campus_backend/tests/test_admin_review.py`
- **reads**：B1 交付报告（`approve(application, admin)` 服务签名）；需求 §校园认证
- **forbidden**：`models/**`、`migrations/**`、`campus_frontend/**`
- **验收标准**：
  1. 审核队列：pending 申请倒序列表（含学生证 image_id 供前端取图）；非 pending 态不出现在队列；
  2. 通过：调 B1 `approve`（落 school_id/campus_id、重算 display_name、auth_status=approved）；驳回：必填原因，落 reject_reason；
  3. 用户管理：跨校列表、按学校/认证状态/封禁状态筛选；**响应不含手机号/邮箱等联系方式**（需求 FR-ADM-02，测试断言响应字段集）；封禁（status=banned，登录即拒 403 `USR1006`）/解封；撤销认证（回 unverified，历史订单消息保留——断言）；
  4. 每次处置写 AdminLog（操作人/对象/动作/原因）；
  5. pytest 全绿（含学生越权 403、联系方式泄漏断言）。
- **门禁命令**：§9 L1 + L2
- **规模预期**：约 350 行

### T37 商品处置与待复核队列

- **目标**：FR-ADM-03/04 + 敏感词接入发布链路
- **前置依赖**：T36
- **required_skills**：flask-backend
- **owns**：`campus_backend/src/routes/admin_products.py`、`campus_backend/src/services/moderation_service.py`、`campus_backend/src/services/product_service.py`（**仅限发布处敏感词标记接入**）、`campus_backend/tests/test_moderation.py`
- **reads**：需求 §商品状态（管理员强制下架语义）；B2 发布链路
- **forbidden**：`models/**`、`migrations/**`、`campus_frontend/**`、product_service 其他函数
- **验收标准**：
  1. 敏感词服务：标题+描述匹配（子串即可，DFA 可选）；发布时命中→照常上架且 `moderation_status=pending`，未命中 `normal`（需求 §商品状态）；接入点 diff 限于发布/编辑入口；
  2. 待复核队列：`GET /api/admin/products?moderation=pending`；处置动作：强制下架 / 恢复（置 normal）/ 删除，均填原因、写 AdminLog；
  3. 强制下架语义：`takedown` 置 off_sale 并标记**仅管理员可恢复**（卖家 re-publish 被拒 403 `GDS2003`，断言）；trading 态亦可强制下架（订单侧联动的最小处理：仅改商品状态，订单自然走取消/超时，入档说明）；
  4. 全校商品列表：跨校、按学校/状态/moderation 筛选分页；
  5. pytest 全绿（含"命中词库仍可见""卖家无法自行恢复"两断言）。
- **门禁命令**：§9 L1 + L2
- **规模预期**：约 350 行

### T38 学校管理与批量导入

- **目标**：FR-ADM-06/07 + AC-06
- **前置依赖**：T37
- **required_skills**：flask-backend
- **owns**：`campus_backend/src/routes/admin_schools.py`、`campus_backend/src/services/school_admin_service.py`、`campus_backend/tests/test_school_import.py`
- **reads**：需求 §学校与校区（导入模板列、逐行校验部分成功）
- **forbidden**：`models/**`、`migrations/**`、`campus_frontend/**`、B1 的 schools 公开路由
- **验收标准**：
  1. 学校 CRUD：新增（名称唯一，重复 409）、编辑、停用（停用后不出现在公开列表与认证选择；已有学生不受影响，入档说明）；多校区开关：开启须 ≥1 校区；关闭时若有绑定用户，返回需迁移提示（409）不强行关闭；
  2. 批量导入：csv 与 xlsx（**新增依赖 openpyxl——用途：xlsx 解析；替代方案：仅支持 csv 被需求否决，入 decisions.md**）；模板下载接口；逐行校验部分成功：返回 `{success_count, failures:[{row, reason}]}`（AC-06 断言）；校区分号分隔解析；导入幂等（同名校校跳过或更新，策略入档）；
  3. 校区维护随学校（增删改）；
  4. 处置写 AdminLog；pytest 全绿（含错误行报告用例）。
- **门禁命令**：§9 L1 + L2
- **规模预期**：约 400 行

### T39 统计、分类管理与操作日志

- **目标**：FR-ADM-05/08/09 + AC-16
- **前置依赖**：T38
- **required_skills**：flask-backend
- **owns**：`campus_backend/src/routes/admin_stats.py`、`campus_backend/src/routes/admin_categories.py`、`campus_backend/src/routes/admin_logs.py`、`campus_backend/src/services/stats_service.py`、`campus_backend/tests/test_admin_stats.py`
- **reads**：需求 FR-ADM-05/08/09
- **forbidden**：`models/**`、`migrations/**`、`campus_frontend/**`
- **验收标准**：
  1. 概览：用户数、认证通过数、待审核数、商品数、在售数、已售数、订单数、成交金额、分类分布（各分类商品计数）——**与种子数据实值核对一致（AC-16 断言：测试内 SQL 对账）**；
  2. 趋势：近 7 日按日新增用户/商品/订单/成交额（跨日边界取本地时区，入档）；
  3. 分类 CRUD：新增/编辑/排序/停用；停用分类不出现在公开列表（B2 缓存失效联动——失效 `product:category:all`，断言）；已有商品的分类不可删除只可停用；
  4. 操作日志：分页查询（按操作人/对象类型/时间过滤）；记录覆盖 T36–T38 全部处置动作（抽查断言）；
  5. pytest 全绿。
- **门禁命令**：§9 L1 + L2
- **规模预期**：约 350 行

---

## 4. 依赖与顺序

T35 → T36 → T37 → T38 → T39；与 frontend/planF5 并行。

## 5. 验收映射

| 需求/验收 | 承载 |
| --- | --- |
| FR-ADM-01~09、FR-GDS-09 | T35–T39 |
| AC-05 认证闭环（审核半边） | T36 |
| AC-06 学校导入 | T38 |
| AC-16 统计一致 | T39 |
| AC-19 P1 覆盖（操作日志/待复核/分类管理） | T37/T39 |

## 6. 退出条件

1. T35–T39 `merged`，L1/L2 全绿；
2. I4 联调点通过（AC-05 全链路：提交→审核→立即可浏览，plan0 §12.3）；
3. backend 线全部完成：m5-admin tag 前置就绪。

## 7. 风险

| 风险 | 对策 |
| --- | --- |
| admin 路由漏加装饰器（越权） | 路由注册集中审查：所有 /api/admin/* 必须挂 @admin_required，smoke 断言学生 403 |
| 敏感词接入改动越界（B2 文件） | owns 限定发布/编辑入口行；审查以 diff 核 |
| xlsx 依赖体积/兼容 | openpyxl 仅入 main 依赖；若安装受阻记 decisions.md 降级 csv-only 并回改需求 |
