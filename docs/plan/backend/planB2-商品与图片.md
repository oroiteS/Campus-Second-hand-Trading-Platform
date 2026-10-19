# planB2 · 后端：商品与图片

_课程设计项目 · 2026-10-19 · 版本 v1.0 · 状态：待执行_

> **定位**：backend 线第二域。商品域后端全量实现，并落地 plan0 §6.2 的**同校隔离硬规则**（`scoped_query` 首次真实启用）——本域是全项目隔离正确性的主战场。
> **上游**：[plan0](../plan0-项目规范.md)（v1.3）· [plan2](../plan2-API契约.md) · planB1 已合并（T10–T13）
> **对端**：[frontend/planF2](../frontend/planF2-商品浏览与发布.md) —— 并行，于**联调点 I2**（与 B3 共同触发）汇合。

---

## 0. 目标与范围

### 目标

1. FR-GDS-01/02/03/04/07/08/10/11 后端实现（发布、编辑、列表、详情、状态管理、收藏、我的商品、商品图片接入）；
2. `scoped_query` / `scoped_key` 商品域全量落地：列表、详情、收藏、缓存键全部含 `school_id`，非本校一律 404（plan0 §6.2 五条硬规则的首轮真实执行）；
3. 商品详情与列表缓存（db2）及失效逻辑就位，为 B3 推荐缓存复用。

### 范围内

`models/product.py` 四表、商品域迁移与种子（每校 60+ 在售 + 各状态样本）、商品 CRUD 与状态机、列表筛选、详情、收藏、分类公开列表、db2 缓存三键中 detail/list 的写与失效、本域 pytest（含隔离必测）。

### 范围外

搜索与推荐（B3）；向量任何逻辑（B3，编辑后的向量重建由 B3 的 hook 任务接入）；分类管理 CRUD（B6）；信誉分计算（B4——详情返回 `seller.credit_score` 可为 null，B4 后补全）；敏感词匹配（B6 接入，本域发布时 `moderation_status` 恒 `normal`）。

---

## 1. 契约引用

`/api/products`（GET/POST）· `/api/products/{id}`（GET/PUT/DELETE）· `/api/products/{id}/status`（PATCH）· `/api/products/{id}/favorite`（POST/DELETE）· `/api/categories`（GET）。商品列表筛选参数（category_id / price_min / price_max / condition / sort / page / page_size）以 openapi 定义为准。

## 2. 对端对应关系

| 本计划任务 | 对端消费 | 汇合点 |
| --- | --- | --- |
| T16 商品 CRUD | F2·T47 发布编辑、T48 我的商品 | I2 |
| T17 列表与详情 | F2·T45 首页列表、T46 详情 | I2 |
| T18 收藏与分类 | F2·T46 收藏、T48 收藏列表 | I2 |

## 3. 任务卡（线内串行：T15 → T16 → T17 → T18）

### T15 商品域模型、迁移与种子

- **目标**：Category / Product / ProductImage / Favorite 四表 + 种子
- **前置依赖**：planB1 已合并
- **required_skills**：flask-backend
- **owns**：`campus_backend/src/models/product.py`、`migrations/versions/<商品域迁移>`、`scripts/seedlib/product.py`
- **reads**：需求 §数据设计（商品域 ER、索引要点）；plan2 schemas（Product/Category 组件）
- **forbidden**：`routes/**`、`services/**`、`campus_frontend/**`、B1 模型文件
- **验收标准**：
  1. 四表字段与 ER 图一致；索引 `idx_school_status_created`、`idx_seller_status`、`idx_category`、`uk_user_product` 就位；
  2. `db upgrade / downgrade / upgrade` 可执行、单头；
  3. 种子：全部分类（8–10 个）；**每校 ≥60 件 on_sale**（覆盖全部分类、价格散布、含多校区学校商品），另每校各状态样本（trading / sold / off_sale / deleted）≥2 件、待复核样本 1 件（`moderation_status=pending`，供 B6 演示）；商品图经 gen_images 生成并关联；幂等（标题哈希键）；
  4. 商品文本（标题+描述）由模板×分类词表生成，同分类内有语义区分度（为 B3 搜索召回留空间，需求 §种子数据）；
  5. pytest 模型冒烟全绿。
- **门禁命令**：§9 L1 + L2
- **规模预期**：约 450 行（含种子生成模板）

### T16 商品 CRUD 与状态管理

- **目标**：FR-GDS-01/02/07/10
- **前置依赖**：T15
- **required_skills**：flask-backend
- **owns**：`campus_backend/src/routes/products.py`、`campus_backend/src/services/product_service.py`、`campus_backend/tests/test_products_crud.py`
- **reads**：需求 §商品状态（状态机图）；plan2 锚点；B1 的 `@login_required` / `@verified_required`
- **forbidden**：`models/**`、`migrations/**`、`campus_frontend/**`
- **验收标准**：
  1. 发布：必填缺失 400 指明字段；1–9 张图（image_id 列表校验存在且 purpose=product）；价格非负；发布即 `on_sale`、`moderation_status=normal`；未认证 403（**商品域 403 首次落地**）；
  2. 编辑：仅发布者（他人 404）；编辑成功后调用**向量重建钩子接口**（本任务只定义 `on_product_changed(product)` 钩子并留 no-op 实现，B3 T21 替换为真实逻辑——接口签名写入交付报告）；
  3. 状态机：on_sale↔off_sale（卖家）；`admin_only` 的恢复与强制下架字段预留（B6 走 admin 路由）；非法迁移（如 sold→on_sale）409（`GDS2001`）；状态变更写 `updated_at`；
  4. 删除：卖家可删（on_sale/off_sale 态），落 `deleted` 软删；
  5. 我的商品：按状态筛选分页，只含自己发布；
  6. **一切列表查询经 `scoped_query(Product)`，审查按 plan0 §5.5 后端清单逐条对照**；
  7. pytest 全绿（状态机合法/非法迁移矩阵用例 ≥8 个）。
- **门禁命令**：§9 L1 + L2
- **规模预期**：约 400 行

### T17 商品列表与详情

- **目标**：FR-GDS-03/04 + 缓存
- **前置依赖**：T16
- **required_skills**：flask-backend
- **owns**：`campus_backend/src/services/product_query_service.py`、`campus_backend/src/common/cache.py`、`campus_backend/tests/test_products_list.py`
- **reads**：需求 §同校隔离、§Redis 键设计（db2）；plan2 锚点
- **forbidden**：`routes/products.py`（只读追加详情路由可协商——详情路由如需新增文件放 `routes/products_detail.py` 或经主代理协调）
- **验收标准**：
  1. 列表：本校 on_sale 分页；分类/价格区间/成色筛选；排序（最新/价格升降）；组合筛选缓存键 `product:list:{school}:{hash}`（TTL 120s，键含筛选参数哈希）；
  2. 详情：含图片有序列表、卖家 `display_name` / `credit_score`（**nullable，B4 前为 null**）`/ 在售数`、`favorite_count`、`view_count`；**非本校或非存在 404**；管理员可跨校读（`g.scope_all`）；
  3. 浏览计数：详情请求触发 `view_count+1`（可容忍非精确，同会话短窗口去重可选）；
  4. 缓存：`product:detail:{school}:{id}`（TTL 600s）；编辑/上下架/删除**主动失效** detail 与 list 两类键（失效用例必测）；
  5. 交易中商品：仅买卖双方与管理员可见详情，他校/无关用户 404；
  6. 隔离测试：**AC-03 断言集**——A 校用户构造 B 校商品 id 请求 404；列表/筛选不含他校；缓存键抽查不含他校 id（plan0 §9 必测 1）。
- **门禁命令**：§9 L1 + L2
- **规模预期**：约 350 行

### T18 收藏与分类列表

- **目标**：FR-GDS-08 + 分类公开查询
- **前置依赖**：T17
- **required_skills**：flask-backend
- **owns**：`campus_backend/src/routes/favorites.py`、`campus_backend/src/routes/categories.py`、`campus_backend/src/services/favorite_service.py`、`campus_backend/tests/test_favorites.py`
- **reads**：需求 §收藏与画像（MySQL 半边）；plan2 锚点
- **forbidden**：`models/**`、`migrations/**`、`campus_frontend/**`
- **验收标准**：
  1. 收藏/取消：重复收藏 409（`GDS2002`）；收藏对象必须本校 on_sale（否则 404）；`favorite_count` 增减一致；
  2. 收藏列表：本人分页，商品快照含图片、价格、状态；已下架/已售商品保留展示并标注状态；
  3. **收藏动作预留画像钩子** `on_favorite(user, product)`（no-op，B3 T23 替换——签名写入交付报告，与 T16 的 `on_product_changed` 同模式）；
  4. 分类列表：启用分类、按 sort_order，缓存 `product:category:all`（TTL 3600s）；未认证 403；
  5. pytest 全绿。
- **门禁命令**：§9 L1 + L2
- **规模预期**：约 250 行

---

## 4. 依赖与顺序

T15 → T16 → T17 → T18；与 frontend/planF2 全程并行，I2 联调需 **B3 亦合并**（plan0 §12.3）。

## 5. 验收映射

| 需求/验收 | 承载 |
| --- | --- |
| FR-GDS-01/02/03/04/07/08/10/11 | T15–T18 |
| AC-03 同校隔离（商品域） | T17（断言集） |
| AC-02 准入 403（商品域） | T16/T18 |
| plan0 §6.2 隔离硬规则首轮落地 | T16/T17 |

## 6. 退出条件

1. T15–T18 `merged`，L1/L2 全绿；
2. 隔离测试矩阵（403 准入 / 404 跨校 / 缓存键含 school）全绿并在审查报告留档；
3. `on_product_changed` / `on_favorite` 两钩子签名入档，B3 可直接替换。

## 7. 风险

| 风险 | 对策 |
| --- | --- |
| scoped_query 漏网（裸 Model.query） | 审查按 plan0 §5.5 逐条对照 + 测试断言跨校不可见 |
| 缓存失效遗漏（编辑后列表仍旧数据） | T17 验收 4 失效用例必测 |
| 卖家信誉分跨域依赖 | 契约 Seller.credit_score 定义为 nullable，B4 补全 |
