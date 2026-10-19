# planF2 · 前端：商品浏览与发布

_课程设计项目 · 2026-10-19 · 版本 v1.0 · 状态：待执行_

> **定位**：frontend 线第二域，**面向用户的主界面**。首页（推荐+列表+搜索）、商品详情、发布编辑、我的商品、收藏——演示脚本第 4–8 步的全部舞台。
> **上游**：[plan0](../plan0-项目规范.md) · [plan2](../plan2-API契约.md) · planF1 已合并（client.ts / 守卫 / AppLayout 可复用）
> **对端**：[backend/planB2](../backend/planB2-商品与图片.md) + [planB3](../backend/planB3-搜索推荐与向量.md) —— 并行，共同触发**联调点 I2**。

---

## 0. 目标与范围

### 目标

1. FR-GDS-01/02/03/04/08/10/11 的前端半边 + FR-GDS-05（搜索框）/06（推荐区）；
2. 首页三区（推荐栅格 / 筛选列表 / 搜索入口）与 `RequireVerified` 守卫的真实业务化；
3. 演示关键位：40 商品 5×8 栅格、换一批、语义搜索结果页、图片上传多图管理。

### 范围内

首页（推荐区+列表区+搜索）、商品详情、发布/编辑、我的商品、收藏列表、商品卡片与图片轮播等可复用组件、api 域封装。

### 范围外

聊天入口的真实逻辑（本域只放占位按钮，F4 接通）；下单/支付（F3）；管理端任何页面（F5）；发布页的敏感词提示（后端静默标记，前端无感）。

---

## 1. 契约引用

`/api/recommendations/home`（含 `refresh`、`mix` 字段）· `/api/products`（GET/POST）· `/api/products/{id}`（GET/PUT/DELETE）· `/api/products/{id}/status` · `/api/products/{id}/favorite` · `/api/products/search` · `/api/categories` · `/api/uploads`（POST，purpose=product）。

## 2. 对端对应关系

| 本计划任务 | 对端实现 | 汇合点 |
| --- | --- | --- |
| T45 首页三区 | B3·T24（推荐）/ B2·T17（列表） | I2 |
| T46 商品详情 | B2·T17 / B3·T22 | I2 |
| T47 发布编辑 | B2·T16 | I2 |
| T48 我的商品+收藏 | B2·T16/T18 | I2 |

## 3. mock 边界

B2/B3 合并前 mock：商品 60+ 条（多分类多价格）、推荐含 `mix` 字段、搜索返回语义结果样本、上传返回固定 `{id,url}`；**B3 的 `degraded` 响应也要 mock 一份**（前端降级提示展示需要）。I2 关 mock。

## 4. 任务卡（线内串行：T45 → T46 → T47 → T48）

### T45 首页：推荐、列表与搜索

- **目标**：FR-GDS-03/06 + FR-GDS-05 前端半边
- **前置依赖**：planF1 已合并
- **required_skills**：frontend-designer
- **owns**：`campus_frontend/src/pages/Home.tsx`、`src/components/ProductGrid.tsx`、`src/components/ProductCard.tsx`、`src/components/ProductFilters.tsx`、`src/api/products.ts`、`src/api/recommendations.ts`、相关 `.types.ts` / 测试
- **reads**：plan2 锚点；需求 §首页推荐（5×8、换一批）
- **forbidden**：`campus_backend/**`、`src/api/client.ts`（只读）
- **验收标准**：
  1. 推荐区：40 商品 5 行×8 列栅格（窄屏自适应降列，移动优先不破）；"换一批"触发 `refresh=1`；角标可展示 `mix`（演示讲解用，样式低调）；
  2. 列表区：分类/价格区间/成色筛选 + 排序 + 分页（上拉或页码）；筛选状态进 URL query（可分享/回退）；
  3. 搜索框：提交跳搜索结果页（复用列表组件，带关键词态与相似度排序说明位）；`degraded` 时横幅提示"语义搜索暂不可用，已降级为关键词匹配"；
  4. 三态齐全：骨架屏（栅格与列表各自）、空态（含"暂无商品"引导发布）、错误态可重试；
  5. 卡片可访问性：整卡键盘可达、图片 alt=商品标题、价格语义标签；
  6. 门禁全绿 + 列表分页与筛选联动测试 ≥2 个。
- **门禁命令**：§9 L1
- **规模预期**：约 500 行

### T46 商品详情

- **目标**：FR-GDS-04 前端半边 + 收藏 + 聊天占位
- **前置依赖**：T45
- **required_skills**：frontend-designer
- **owns**：`campus_frontend/src/pages/ProductDetail.tsx`、`src/components/ImageCarousel.tsx`、`src/components/SellerCard.tsx`、`src/components/FavoriteButton.tsx`、`src/pages/SearchResult.tsx`、相关测试
- **reads**：plan2 锚点；需求 FR-GDS-04
- **forbidden**：`campus_backend/**`
- **验收标准**：
  1. 轮播：多图有序、键盘左右、缩略图指示；单图直出；
  2. 信息区：价格、成色、分类、发布时间、浏览量、收藏数；卖家卡（展示名、信誉分或"暂无"、在售数、**主页链接占位**——真实主页 F3 后接，若契约 `/api/users/{id}` 未就绪则隐藏，入档）；
  3. 收藏：乐观更新 + 失败回滚；未收藏/已收藏两态 aria 标注；
  4. **404 空态**（非本校或不存在）：明确文案"商品不存在或不可见"，不暴露原因区分；
  5. 交易中/已售/已下架商品的状态横幅（本人或管理员可见场景）；
  6. 聊天入口按钮占位（disabled + title 说明 F4 接通）；
  7. 门禁全绿 + 404 与收藏回滚测试。
- **门禁命令**：§9 L1
- **规模预期**：约 450 行

### T47 发布与编辑

- **目标**：FR-GDS-01/02/11 前端半边
- **前置依赖**：T46
- **required_skills**：frontend-designer
- **owns**：`campus_frontend/src/pages/ProductPublish.tsx`、`src/pages/ProductEdit.tsx`、`src/components/ImageUploader.tsx`、`src/api/uploads.ts`（若 F1 未建则建）、相关测试
- **reads**：plan2 锚点；需求 FR-GDS-01/11（1–9 图、5MB、jpg/png/webp）
- **forbidden**：`campus_backend/**`
- **验收标准**：
  1. 表单：标题/描述/价格/分类（拉取 categories）/成色必填；原价可选；价格输入校验（≥0 两位小数）；
  2. 多图上传：1–9 张；前端预校验（类型/大小，超限即拦并提示）；上传中进度态；失败单张重试；**排序调整**（左移/右移按钮，拖拽可选）；首图为封面标识；
  3. 编辑页：回显现值与图片；仅发布者可进（他人 id 被后端 404，前端空态）；
  4. 发布成功跳详情页；编辑成功返回来源页；
  5. 三态 + 表单可访问性（错误提示 aria-describedby、必填标识）；
  6. 门禁全绿 + 上传校验与排序测试。
- **门禁命令**：§9 L1
- **规模预期**：约 500 行

### T48 我的商品与收藏列表

- **目标**：FR-GDS-10/08 前端半边
- **前置依赖**：T47
- **required_skills**：frontend-designer
- **owns**：`campus_frontend/src/pages/MyProducts.tsx`、`campus_frontend/src/pages/Favorites.tsx`、`src/api/my.ts`（或并入 products.ts）、相关测试
- **reads**：plan2 锚点；需求 FR-GDS-10/08
- **forbidden**：`campus_backend/**`
- **验收标准**：
  1. 我的商品：状态 tabs（在售/交易中/已售/已下架）；行内操作：编辑 / 上架↔下架（确认弹窗）/ 删除（二次确认，注明不可恢复）；
  2. 收藏列表：卡片栅格复用 ProductCard；已下架/已售角标；取消收藏即时移除（乐观+回滚）；
  3. 两页均分页 + 三态；空态引导（"还没有发布过商品→去发布"）；
  4. 顶栏用户菜单接入两页入口；
  5. 门禁全绿 + 状态筛选与删除确认测试。
- **门禁命令**：§9 L1
- **规模预期**：约 350 行

---

## 5. 依赖与顺序

T45 → T46 → T47 → T48；与 B2/B3 并行。

## 6. 验收映射

| 需求/验收 | 承载 |
| --- | --- |
| FR-GDS-01~05/08/10/11 前端 | T45–T48 |
| AC-07 推荐配比（展示与 mix） | T45 |
| AC-09 搜索体验（降级横幅） | T45 |
| 演示脚本步骤 5–8 的界面 | T45–T47 |

## 7. 退出条件

1. T45–T48 `merged`，L1 全绿；
2. I2 联调点通过（关 mock：推荐 40 配比、列表筛选、搜索语义召回、发布→搜索到新商品，plan0 §12.3）。

## 8. 风险

| 风险 | 对策 |
| --- | --- |
| 5×8 栅格与响应式冲突（320px） | grid 自动降列 + minmax；T45 验收 1 明确移动优先 |
| 推荐区与列表区数据双份请求性能 | React Query 缓存键分离；图片 lazy loading |
| 编辑回显图片排序错乱 | 契约返回 sort_order；编辑页按序渲染并保留调整能力 |
