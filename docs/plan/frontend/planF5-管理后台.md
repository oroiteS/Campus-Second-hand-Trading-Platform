# planF5 · 前端：管理后台

_课程设计项目 · 2026-10-19 · 版本 v1.0 · 状态：待执行_

> **定位**：frontend 线第五域。管理后台全部界面：审核队列、用户管理、商品处置、待复核、学校与分类维护、批量导入、统计图表、操作日志——演示脚本第 11 步的舞台。
> **上游**：[plan0](../plan0-项目规范.md) · [plan2](../plan2-API契约.md) · planF4 已合并
> **对端**：[backend/planB6](../backend/planB6-管理后台与统计.md) —— 并行，共同触发**联调点 I4**。

---

## 0. 目标与范围

### 目标

1. FR-ADM-01 ~ FR-ADM-09 前端全部；
2. admin 布局（侧栏导航）与 `RequireAdmin` 守卫；管理员身份不出现 C 端发布/下单入口（需求 §角色定义）；
3. 统计概览 + 近 7 日趋势可视化（AC-16）。

### 范围内

admin 布局与守卫、认证审核、用户管理、商品处置与待复核、学校管理与导入、分类管理、统计两页、操作日志。

### 范围外

C 端任何改动（除 admin 身份下的入口隐藏逻辑）；聊天监管。

---

## 1. 契约引用

`/api/admin/*` 全部（certifications / users / products / takedown / schools / import / categories / stats/overview / stats/trend / logs——plan2 §3 管理组）。

## 2. 对端对应关系

| 本计划任务 | 对端实现 | 汇合点 |
| --- | --- | --- |
| T61 审核+用户管理 | B6·T36 | I4 |
| T62 处置+待复核 | B6·T37 | I4 |
| T63 学校+导入 | B6·T38 | I4 |
| T64 统计+分类+日志 | B6·T39 | I4 |

## 3. mock 边界

B6 合并前 mock：待审核队列（含学生证图）、跨校用户集、待复核商品、导入结果（含失败行）、统计数值与趋势序列。I4 关 mock。

## 4. 任务卡（线内串行：T60 → T61 → T62 → T63 → T64）

### T60 管理布局与守卫

- **目标**：admin 壳与权限入口
- **前置依赖**：planF4 已合并
- **required_skills**：frontend-designer
- **owns**：`campus_frontend/src/pages/admin/AdminLayout.tsx`、`src/components/guards.tsx`（追加 RequireAdmin）、`src/pages/admin/AdminHome.tsx`、相关测试
- **reads**：plan2 §2（role 语义）；planF1 guards
- **forbidden**：`campus_backend/**`
- **验收标准**：
  1. `RequireAdmin`：非 admin 跳首页并提示（不暴露 admin 路由存在性文案）；
  2. 侧栏：审核 / 用户 / 商品 / 待复核 / 学校 / 分类 / 统计 / 日志分组导航；当前项焦点样式；
  3. **admin 身份下隐藏 C 端发布与下单入口**（顶栏与详情页购买按钮条件渲染，需求 §角色定义；与 F2/F3 页面的条件点经主代理协调 owns）；
  4. 路由 `/admin/*` 懒加载分包；
  5. 门禁全绿 + 守卫测试。
- **门禁命令**：§9 L1
- **规模预期**：约 250 行

### T61 认证审核与用户管理

- **目标**：FR-ADM-01/02 前端 + AC-05 界面
- **前置依赖**：T60
- **required_skills**：frontend-designer
- **owns**：`campus_frontend/src/pages/admin/CertReview.tsx`、`src/pages/admin/UserManage.tsx`、`src/api/admin/users.ts`、相关测试
- **reads**：plan2 锚点；需求 FR-ADM-01/02
- **forbidden**：`campus_backend/**`
- **验收标准**：
  1. 审核队列：申请卡（展示名候选、学校/校区、真实姓名、**学生证大图预览/放大**）；通过=一键；驳回=必填原因弹窗；
  2. 用户管理：跨校列表 + 学校/认证状态筛选 + 封禁状态；**表格不出现手机号/邮箱列**（需求红线）；封禁/解封二次确认；撤销认证确认（说明后果文案）；
  3. 操作全部带 loading 与结果反馈，失败保留表单；
  4. 门禁全绿 + 驳回必填与列字段断言测试。
- **门禁命令**：§9 L1
- **规模预期**：约 400 行

### T62 商品处置与待复核

- **目标**：FR-ADM-03/04 前端
- **前置依赖**：T61
- **required_skills**：frontend-designer
- **owns**：`campus_frontend/src/pages/admin/ProductManage.tsx`、`src/pages/admin/ModerationQueue.tsx`、`src/api/admin/products.ts`、相关测试
- **reads**：plan2 锚点（`moderation=pending` 过滤）
- **forbidden**：`campus_backend/**`
- **验收标准**：
  1. 全校商品：跨校筛选 + 状态/moderation 筛选 + 分页；处置菜单（强制下架/恢复/删除）均必填原因；
  2. 待复核队列：命中词高亮（后端返回命中词则展示，未返回则仅展示待复核列表）；处置动作同上；
  3. 强制下架商品标注"管理员下架"徽标（与卖家自下架区分）；
  4. 门禁全绿 + 处置原因必填测试。
- **门禁命令**：§9 L1
- **规模预期**：约 350 行

### T63 学校管理与批量导入

- **目标**：FR-ADM-06/07 前端 + AC-06 界面
- **前置依赖**：T62
- **required_skills**：frontend-designer
- **owns**：`campus_frontend/src/pages/admin/SchoolManage.tsx`、`src/pages/admin/SchoolImport.tsx`、`src/api/admin/schools.ts`、相关测试
- **reads**：plan2 锚点（import 载荷与 failures 结构）
- **forbidden**：`campus_backend/**`
- **验收标准**：
  1. 学校 CRUD：多校区开关动态显示校区子表（增删改）；关闭多校区遇绑定用户提示后端 409 原因；
  2. 导入：模板下载按钮；csv/xlsx 上传；**逐行错误报告表（行号+原因）与成功计数**（AC-06 断言）；导入后列表刷新；
  3. 门禁全绿 + 错误行渲染测试。
- **门禁命令**：§9 L1
- **规模预期**：约 350 行

### T64 统计、分类管理与操作日志

- **目标**：FR-ADM-05/08/09 前端 + AC-16 界面
- **前置依赖**：T63
- **required_skills**：frontend-designer
- **owns**：`campus_frontend/src/pages/admin/Stats.tsx`、`src/pages/admin/CategoryManage.tsx`、`src/pages/admin/AdminLogs.tsx`、`src/api/admin/stats.ts`、相关测试
- **reads**：plan2 锚点
- **forbidden**：`campus_backend/**`
- **验收标准**：
  1. 概览：指标卡片（用户/认证/商品/订单/成交额）+ 分类分布图；**趋势：近 7 日折线（新增用户/商品/订单）**——图表用 antd 内置或轻量 SVG 组件（**不引入重型图表库**；若需 @ant-design/charts 另记 decisions.md）；
  2. 分类管理：列表排序（上移/下移）、新增/编辑/停用；停用即时反映（提示公开列表缓存刷新语义）；
  3. 操作日志：时间倒序分页 + 操作人/对象类型筛选；动作与原因列完整；
  4. 门禁全绿 + 趋势数据渲染测试。
- **门禁命令**：§9 L1
- **规模预期**：约 400 行

---

## 5. 依赖与顺序

T60 → T61 → T62 → T63 → T64；与 B6 并行。

## 6. 验收映射

| 需求/验收 | 承载 |
| --- | --- |
| FR-ADM-01~09 前端 | T60–T64 |
| AC-05 审核界面闭环 | T61 |
| AC-06 导入错误报告 | T63 |
| AC-16 统计展示 | T64 |
| 演示脚本步骤 11 | T61/T62/T64 |

## 7. 退出条件

1. T60–T64 `merged`，L1 全绿；
2. I4 联调点通过（AC-05 全链路、导入、统计对账，plan0 §12.3）；
3. frontend 线全部完成：m5-admin tag 前置就绪。

## 8. 风险

| 风险 | 对策 |
| --- | --- |
| 图表库依赖失控 | 默认 antd/SVG 自绘；引入新库必须过 decisions.md |
| admin 入口隐藏遗漏（详情页购买按钮） | T60 验收 3 列出全部条件渲染点清单，审查逐点核 |
| 学生证大图加载慢 | 缩略图+点击放大灯箱；loading 占位 |
