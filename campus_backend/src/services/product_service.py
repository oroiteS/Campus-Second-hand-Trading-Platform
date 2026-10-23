"""商品域服务：发布 / 详情（含缓存与浏览计数）/ 在售列表 / 我的商品。

事务边界在本层：发布 = products + product_images 同一事务；全部事件
**先 commit 后 emit**（订阅者异常由总线隔离）。隔离三件套：查询经
``scoped_query``（零裸 ``Product.query``）；缓存键经 ``scoped_key`` 且
detail 键含 school_id；防探测一致性（非本人/他校/不存在一律 404/9002）。

b2be2 依赖的三个查询函数（``get_on_sale_by_ids`` / ``list_on_sale_random``
/ ``get_active_by_id``）以**显式 scope 参数**为签名（Interfaces 节钉死），
不读请求上下文，故不经 ``scoped_query``。
"""

import json
import random
from decimal import Decimal, InvalidOperation

from flask import current_app, g
from sqlalchemy import update as sa_update
from sqlalchemy.orm import selectinload

from src.common import redis_client
from src.common.auth import scoped_key
from src.common.errors import ApiError, ErrorCode
from src.common.redis_client import PRODUCT_DB_OFFSET
from src.common.scope import scoped_query
from src.model import (
    PRODUCT_CONDITIONS,
    PRODUCT_STATUSES,
    Campus,
    Category,
    Favorite,
    Image,
    Product,
    ProductImage,
    User,
    db,
)
from src.services import events

# ---- 契约常量（3.0 字段校验对照表）----
PRICE_MIN = Decimal("0.01")
PRICE_MAX = Decimal("99999.99")
SORT_OPTIONS = ("newest", "price_asc", "price_desc")
TITLE_MAX = 50
DESCRIPTION_MAX = 2000
KEYWORD_MAX = 100
IMAGE_MIN, IMAGE_MAX = 1, 9

# 商品状态中文标签（仅出现在 message 文案）
_STATUS_LABELS = {
    "on_sale": "上架",
    "trading": "交易中",
    "sold": "已售",
    "off_sale": "已下架",
    "deleted": "已删除",
}

# detail 缓存 TTL（任务卡：600s；category 见 category_service）
DETAIL_CACHE_TTL = 600


def _fields_error(fields: dict[str, str]) -> ApiError:
    return ApiError(ErrorCode.VALIDATION_ERROR, data={"fields": fields})


def _product_not_found() -> ApiError:
    """防探测统一口径：不存在 / 他校 / 越权一律 404/9002，不区分三种情况。"""
    return ApiError(ErrorCode.NOT_FOUND, message="商品不存在")


def _admin_rejected(action: str) -> ApiError:
    """管理员无交易能力（发布/编辑/收藏/上传），与 b1 认证提交口径一致。"""
    return ApiError(ErrorCode.CONFLICT, message=f"管理员无交易能力，不能{action}")


# ---- 字段校验（service 独立复验，绝不信任客户端）----


def _parse_price(value: object, field: str, fields: dict[str, str]) -> Decimal | None:
    """价格 → Decimal：数字类型、两位小数内、0.01–99999.99（全链路禁 float）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        fields[field] = "价格必须为数字"
        return None
    try:
        price = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        fields[field] = "价格格式不正确"
        return None
    if not price.is_finite() or price.as_tuple().exponent < -2:
        fields[field] = "价格最多两位小数"
        return None
    if price < PRICE_MIN or price > PRICE_MAX:
        fields[field] = "价格须在 0.01–99999.99 元之间"
        return None
    return price


def _resolve_category(payload: dict, fields: dict[str, str]) -> int | None:
    category_id = payload.get("category_id")
    if isinstance(category_id, bool) or not isinstance(category_id, int):
        fields["category_id"] = "分类 id 必须为整数"
        return None
    category = db.session.get(Category, category_id)
    if category is None or category.status != "enabled":
        fields["category_id"] = "分类不存在或已停用"
        return None
    return category_id


def _resolve_campus(user: User, payload: dict, fields: dict[str, str]) -> int | None:
    """campus_id 缺省取发布者校区；填写时须为本人学校的启用校区。"""
    campus_id = payload.get("campus_id")
    if campus_id is None:
        return user.campus_id
    if isinstance(campus_id, bool) or not isinstance(campus_id, int):
        fields["campus_id"] = "校区 id 必须为整数"
        return None
    campus = db.session.get(Campus, campus_id)
    if campus is None or campus.status != "enabled" or campus.school_id != user.school_id:
        fields["campus_id"] = "校区须为本人学校的启用校区"
        return None
    return campus_id


def _resolve_image_ids(user: User, payload: dict, fields: dict[str, str]) -> list[int] | None:
    """image_ids：1–9 张、去重、逐个存在且 purpose=product 且上传者本人。"""
    image_ids = payload.get("image_ids")
    if not isinstance(image_ids, list):
        fields["image_ids"] = "图片 id 列表必填（1–9 张）"
        return None
    if not IMAGE_MIN <= len(image_ids) <= IMAGE_MAX:
        fields["image_ids"] = "图片须为本人上传的商品图，数量 1–9 张"
        return None
    if any(isinstance(i, bool) or not isinstance(i, int) for i in image_ids):
        fields["image_ids"] = "图片 id 必须为整数"
        return None
    if len(set(image_ids)) != len(image_ids):
        fields["image_ids"] = "图片 id 不得重复"
        return None
    for image_id in image_ids:
        image = db.session.get(Image, image_id)
        if image is None or image.purpose != "product" or image.owner_id != user.id:
            fields["image_ids"] = "图片须为本人上传的商品图，数量 1–9 张"
            return None
    return list(image_ids)


def _validate_product_payload(user: User, payload: dict) -> dict:
    """发布/编辑共用校验（3.0 对照表逐项）；全部失败一次性收集为 9001。"""
    fields: dict[str, str] = {}
    title = payload.get("title")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= TITLE_MAX:
        fields["title"] = f"标题长度须为 1–{TITLE_MAX} 字符"
    description = payload.get("description")
    if not isinstance(description, str) or not 1 <= len(description) <= DESCRIPTION_MAX:
        fields["description"] = f"描述长度须为 1–{DESCRIPTION_MAX} 字符"
    price = _parse_price(payload.get("price"), "price", fields)
    original_price = None
    if payload.get("original_price") is not None:
        original_price = _parse_price(
            payload.get("original_price"), "original_price", fields
        )
    category_id = _resolve_category(payload, fields)
    condition = payload.get("condition")
    if condition not in PRODUCT_CONDITIONS:
        fields["condition"] = "成色取值非法"
    campus_id = _resolve_campus(user, payload, fields)
    image_ids = _resolve_image_ids(user, payload, fields)
    if fields:
        raise _fields_error(fields)
    return {
        "title": title.strip(),
        "description": description,
        "price": price,
        "original_price": original_price,
        "category_id": category_id,
        "condition": condition,
        "campus_id": campus_id,
        "image_ids": image_ids,
    }


# ---- 发布 ----


def create(user: User, payload: dict) -> Product:
    """发布：字段复验 → products + product_images 同一事务 → emit PUBLISHED。

    管理员一律 9003；发布即上架（status=on_sale），moderation_status=normal
    （敏感词库 b5 接入，钩子占位）。
    """
    if user.role == "admin":
        raise _admin_rejected("发布商品")
    normalized = _validate_product_payload(user, payload)
    product = Product(
        seller_id=user.id,
        school_id=user.school_id,
        campus_id=normalized["campus_id"],
        category_id=normalized["category_id"],
        title=normalized["title"],
        description=normalized["description"],
        price=normalized["price"],
        original_price=normalized["original_price"],
        condition=normalized["condition"],
        status="on_sale",
        moderation_status="normal",
    )
    for sort_order, image_id in enumerate(normalized["image_ids"]):
        product.product_images.append(
            ProductImage(image_id=image_id, sort_order=sort_order)
        )
    db.session.add(product)
    db.session.commit()
    events.emit(events.PRODUCT_PUBLISHED, product)
    return product


# ---- 详情 ----


def _get_visible_product(viewer: User, product_id: int) -> Product:
    """可见性矩阵（越权/他校/不存在一律 404/9002，防探测）：

    - on_sale 本校全员（管理员跨校）；off_sale / trading 仅卖家与管理员
      （trading 的买方本批无订单恒不满足）；sold / deleted 无人可见。
    """
    product = db.session.get(Product, product_id)
    if product is None or product.status in ("sold", "deleted"):
        raise _product_not_found()
    is_admin = viewer.role == "admin"
    if product.status == "on_sale":
        if not is_admin and product.school_id != viewer.school_id:
            raise _product_not_found()
    elif product.seller_id != viewer.id and not is_admin:
        raise _product_not_found()
    return product


def _is_favorited(viewer: User, product_id: int) -> bool:
    """当前用户是否已收藏（管理员恒 false：管理员无法收藏，恒无记录）。"""
    if viewer.role == "admin":
        return False
    return (
        db.session.query(Favorite)
        .filter(Favorite.user_id == viewer.id, Favorite.product_id == product_id)
        .first()
        is not None
    )


def detail_payload(product: Product, viewer: User) -> dict:
    """组装契约 ProductDetail 响应（view_count/is_favorited 组装时补齐；
    发布/编辑成功响应与详情共用本入口）。"""
    body = product.to_detail_dict()
    body["view_count"] = product.view_count
    body["is_favorited"] = _is_favorited(viewer, product.id)
    return body


def _increment_view_count(product: Product) -> None:
    """浏览量 SQL 原子自增（updated_at 显式保持，浏览不改内容时间戳）。"""
    db.session.execute(
        sa_update(Product)
        .where(Product.id == product.id)
        .values(view_count=Product.view_count + 1, updated_at=Product.updated_at)
    )
    db.session.commit()
    db.session.refresh(product)


def _detail_cache_key(product: Product) -> str:
    return scoped_key("product:detail", product.school_id, product.id)


def _cached_detail_body(product: Product) -> dict:
    """detail 缓存：只缓存商品本体序列化（不含 view_count/is_favorited）；
    Redis 故障降级直查直算（业务照常，仅告警日志）。"""
    key = _detail_cache_key(product)
    try:
        raw = redis_client.get_redis(PRODUCT_DB_OFFSET).get(key)
    except Exception as exc:  # noqa: BLE001 - 缓存降级：可用性优先
        current_app.logger.warning("detail 缓存读取失败，降级直算 key=%s: %s", key, exc)
        raw = None
    if raw is not None:
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            current_app.logger.warning("detail 缓存反序列化失败，按未命中处理 key=%s", key)
    body = product.to_detail_dict()
    try:
        redis_client.get_redis(PRODUCT_DB_OFFSET).setex(
            key, DETAIL_CACHE_TTL, json.dumps(body, ensure_ascii=False)
        )
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning("detail 缓存写入失败 key=%s: %s", key, exc)
    return body


def invalidate_detail_cache(product: Product) -> None:
    """失效 detail 缓存（编辑/状态/删除后调用；含 school 段的键）。"""
    try:
        redis_client.get_redis(PRODUCT_DB_OFFSET).delete(_detail_cache_key(product))
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning("detail 缓存失效失败（降级容忍）: %s", exc)


def get_detail(viewer: User, product_id: int) -> dict:
    """详情：可见性 → 浏览 +1（commit）→ emit VIEWED → 缓存体组装响应。"""
    product = _get_visible_product(viewer, product_id)
    _increment_view_count(product)
    events.emit(events.PRODUCT_VIEWED, viewer.id, product)
    body = _cached_detail_body(product)
    body["view_count"] = product.view_count
    body["is_favorited"] = _is_favorited(viewer, product.id)
    return body


# ---- 列表 / 我的商品 ----

# 概要序列化所需的关联预载（列表 N+1 规避）
_SUMMARY_LOADS = (
    selectinload(Product.product_images).selectinload(ProductImage.image),
    selectinload(Product.seller).selectinload(User.avatar),
    selectinload(Product.category),
    selectinload(Product.campus),
)


def _parse_filter_decimal(raw: object, field: str, fields: dict[str, str]) -> Decimal | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        fields[field] = "价格必须为数字"
        return None
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        fields[field] = "价格必须为数字"
        return None
    if not value.is_finite() or value < 0:
        fields[field] = "价格不得为负"
        return None
    return value


def _validate_list_filters(filters: dict) -> dict:
    """列表筛选校验（条件组合 price_min ≤ price_max → 9001 fields）。"""
    fields: dict[str, str] = {}
    category_id = filters.get("category_id")
    if category_id not in (None, ""):
        try:
            category_id = int(category_id)
        except (TypeError, ValueError):
            fields["category_id"] = "分类 id 必须为整数"
        else:
            category = db.session.get(Category, category_id)
            if category is None or category.status != "enabled":
                fields["category_id"] = "分类不存在或已停用"
    condition = filters.get("condition")
    if condition not in (None, "") and condition not in PRODUCT_CONDITIONS:
        fields["condition"] = "成色取值非法"
    price_min = _parse_filter_decimal(filters.get("price_min"), "price_min", fields)
    price_max = _parse_filter_decimal(filters.get("price_max"), "price_max", fields)
    if (
        price_min is not None
        and price_max is not None
        and price_min > price_max
    ):
        fields["price_min"] = "价格下界不得大于价格上界"
    campus_id = filters.get("campus_id")
    if campus_id not in (None, ""):
        try:
            campus_id = int(campus_id)
        except (TypeError, ValueError):
            fields["campus_id"] = "校区 id 必须为整数"
        else:
            campus = db.session.get(Campus, campus_id)
            # 管理员（scope_all）跨校可见，校区筛选允许任一启用校区
            if (
                campus is None
                or campus.status != "enabled"
                or (not g.scope_all and campus.school_id != g.school_id)
            ):
                fields["campus_id"] = "校区不存在或非本校启用校区"
    keyword = filters.get("keyword")
    if keyword not in (None, "") and (
        not isinstance(keyword, str) or len(keyword) > KEYWORD_MAX
    ):
        fields["keyword"] = f"关键词长度不得超过 {KEYWORD_MAX} 字符"
    sort = filters.get("sort") or "newest"
    if sort not in SORT_OPTIONS:
        fields["sort"] = "排序方式必须为 newest / price_asc / price_desc"
    if fields:
        raise _fields_error(fields)
    return {
        "category_id": category_id if category_id not in (None, "") else None,
        "condition": condition or None,
        "price_min": price_min,
        "price_max": price_max,
        "campus_id": campus_id if campus_id not in (None, "") else None,
        "keyword": (keyword or None) or None,
        "sort": sort,
    }


def _paginate(query, page: int, page_size: int, loads: tuple) -> dict:
    """分页执行 + 概要序列化（PaginatedData 容器）。"""
    total = query.count()
    rows = (
        query.options(*loads)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "items": [p.to_summary_dict() for p in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": (total + page_size - 1) // page_size,
    }


def list_on_sale(filters: dict, page: int, page_size: int) -> dict:
    """本校在售列表（经 scoped_query；筛选全参数化；sort 三态）。

    管理员 scope_all 跨校全量；学生自动注入本校过滤。
    """
    normalized = _validate_list_filters(filters)
    query = scoped_query(Product).filter(Product.status == "on_sale")
    if normalized["category_id"] is not None:
        query = query.filter(Product.category_id == normalized["category_id"])
    if normalized["condition"] is not None:
        query = query.filter(Product.condition == normalized["condition"])
    if normalized["price_min"] is not None:
        query = query.filter(Product.price >= normalized["price_min"])
    if normalized["price_max"] is not None:
        query = query.filter(Product.price <= normalized["price_max"])
    if normalized["campus_id"] is not None:
        query = query.filter(Product.campus_id == normalized["campus_id"])
    if normalized["keyword"]:
        # LIKE 标题直配（全角不转义），参数化无注入面
        query = query.filter(Product.title.like(f"%{normalized['keyword']}%"))
    order = {
        "newest": Product.created_at.desc(),
        "price_asc": Product.price.asc(),
        "price_desc": Product.price.desc(),
    }[normalized["sort"]]
    query = query.order_by(order, Product.id.desc())
    return _paginate(query, page, page_size, _SUMMARY_LOADS)


def mine(user: User, status: str | None, page: int, page_size: int) -> dict:
    """我的商品：只看自己的（seller 过滤；created_at 倒序）。

    status 缺省返回除 deleted 外全部；显式传某状态（含 deleted）则按该
    状态过滤——本人数据无探测面，按请求如实返回。
    """
    if status not in (None, "") and status not in PRODUCT_STATUSES:
        raise _fields_error({"status": "商品状态取值非法"})
    query = scoped_query(Product).filter(Product.seller_id == user.id)
    if status:
        query = query.filter(Product.status == status)
    else:
        query = query.filter(Product.status != "deleted")
    query = query.order_by(Product.created_at.desc(), Product.id.desc())
    return _paginate(query, page, page_size, _SUMMARY_LOADS)


# ---- 编辑 / 上下架 / 删除 ----

# 可编辑状态：off_sale 编辑后仍 off_sale；trading/sold → 3001；deleted → 404
_EDITABLE_STATUSES = ("on_sale", "off_sale")
# 可删除状态：软删，图片与收藏记录保留（不可见，YAGNI）
_DELETABLE_STATUSES = ("on_sale", "off_sale")


def _own_product_or_404(user: User, product_id: int) -> Product:
    """本人本校商品，否则 404/9002（非本人/他校/不存在不区分，防探测）。

    仅编辑/上下架/删除调用；管理员在此口径下恒非本人（admin 无交易能力，
    不可发布即无自有商品）。
    """
    product = db.session.get(Product, product_id)
    if (
        product is None
        or product.seller_id != user.id
        or product.school_id != user.school_id
    ):
        raise _product_not_found()
    return product


def update(user: User, product_id: int, payload: dict) -> Product:
    """编辑：全量替换（含 image_ids 重写）→ emit UPDATED(product, changed)。

    ``changed`` 为实际变化字段名集合（比对请求与原值；image_ids 变化不进
    集合——向量订阅方不关心图片）。失效 detail 缓存。
    """
    if user.role == "admin":
        raise _admin_rejected("编辑商品")
    product = _own_product_or_404(user, product_id)
    if product.status == "deleted":
        raise _product_not_found()
    if product.status not in _EDITABLE_STATUSES:
        raise ApiError(
            ErrorCode.PRODUCT_STATUS_CONFLICT,
            message=(
                f"商品当前状态为{_STATUS_LABELS[product.status]}，不允许编辑；"
                "仅上架或已下架商品可编辑"
            ),
        )
    normalized = _validate_product_payload(user, payload)

    # changed 集合：比对请求与原值（Decimal 与 int 均按值比较）
    changed: set[str] = set()
    if product.title != normalized["title"]:
        changed.add("title")
    if product.description != normalized["description"]:
        changed.add("description")
    if product.price != normalized["price"]:
        changed.add("price")
    if product.original_price != normalized["original_price"]:
        changed.add("original_price")
    if product.category_id != normalized["category_id"]:
        changed.add("category_id")
    if product.condition != normalized["condition"]:
        changed.add("condition")
    if product.campus_id != normalized["campus_id"]:
        changed.add("campus_id")

    product.title = normalized["title"]
    product.description = normalized["description"]
    product.price = normalized["price"]
    product.original_price = normalized["original_price"]
    product.category_id = normalized["category_id"]
    product.condition = normalized["condition"]
    product.campus_id = normalized["campus_id"]
    # image_ids 全量替换（数组序=排序）；delete-orphan 清理旧关联
    product.product_images = [
        ProductImage(image_id=image_id, sort_order=i)
        for i, image_id in enumerate(normalized["image_ids"])
    ]
    db.session.commit()
    invalidate_detail_cache(product)
    events.emit(events.PRODUCT_UPDATED, product, changed)
    return product


def change_status(user: User, product_id: int, new_status: str) -> Product:
    """上下架：仅本人；非法流转 3001；forced_off 重上架 3002。

    目标态与当前态相同视为幂等成功（无状态变化则不 emit、不失效缓存）。
    """
    if new_status not in ("on_sale", "off_sale"):
        raise _fields_error({"status": "目标状态必须为 on_sale 或 off_sale"})
    product = _own_product_or_404(user, product_id)
    if product.status == "deleted":
        raise _product_not_found()
    if product.status not in _EDITABLE_STATUSES:
        raise ApiError(
            ErrorCode.PRODUCT_STATUS_CONFLICT,
            message=(
                f"商品当前状态为{_STATUS_LABELS[product.status]}，"
                "仅上架或已下架商品可执行上下架"
            ),
        )
    if new_status == "on_sale" and product.forced_off:
        raise ApiError(
            ErrorCode.PRODUCT_FORCED_OFF,
            message="商品已被管理员强制下架，无法重新上架；如有疑问请联系管理员",
        )
    if product.status == new_status:
        return product  # 幂等：已是目标状态
    old_status = product.status
    product.status = new_status
    db.session.commit()
    invalidate_detail_cache(product)
    events.emit(events.PRODUCT_STATUS_CHANGED, product, old_status)
    return product


def delete(user: User, product_id: int) -> None:
    """软删：status=deleted，图片与收藏记录保留（不可见）；emit DELETED(id)。"""
    product = _own_product_or_404(user, product_id)
    if product.status == "deleted":
        raise _product_not_found()
    if product.status not in _DELETABLE_STATUSES:
        raise ApiError(
            ErrorCode.PRODUCT_STATUS_CONFLICT,
            message=(
                f"商品当前状态为{_STATUS_LABELS[product.status]}，不允许删除；"
                "仅上架或已下架商品可删除"
            ),
        )
    product.status = "deleted"
    db.session.commit()
    invalidate_detail_cache(product)
    # emit 载荷只有 product_id（Interfaces 节）
    events.emit(events.PRODUCT_DELETED, product.id)


# ---- b2be2 接口（Interfaces 节钉死签名；显式 scope 参数，不读 g）----


def get_on_sale_by_ids(
    school_id: int | None, ids: list[int], *, scope_all: bool = False
) -> list[Product]:
    """按传入 id 顺序返回本校（或 scope_all 全部）在售商品；供向量召回后精筛。"""
    if not ids:
        return []
    stmt = db.select(Product).where(Product.id.in_(ids), Product.status == "on_sale")
    if not scope_all:
        stmt = stmt.where(Product.school_id == school_id)
    products = db.session.execute(stmt).scalars().all()
    by_id = {p.id: p for p in products}
    return [by_id[i] for i in ids if i in by_id]


def list_on_sale_random(
    school_id: int | None, exclude_ids: list[int], limit: int, *, scope_all: bool = False
) -> list[Product]:
    """随机补足：id 池抽样（量小池浅，避免方言差异的 RAND()）。"""
    if limit <= 0:
        return []
    stmt = db.select(Product.id).where(Product.status == "on_sale").limit(500)
    if not scope_all:
        stmt = stmt.where(Product.school_id == school_id)
    if exclude_ids:
        stmt = stmt.where(~Product.id.in_(exclude_ids))
    pool = list(db.session.execute(stmt).scalars())
    random.shuffle(pool)
    chosen = pool[:limit]
    if not chosen:
        return []
    products = db.session.query(Product).filter(Product.id.in_(chosen)).all()
    by_id = {p.id: p for p in products}
    return [by_id[i] for i in chosen if i in by_id]


def get_active_by_id(product_id: int) -> Product | None:
    """任意非 deleted 商品（含本校校验由调用方 scope 决定）。"""
    product = db.session.get(Product, product_id)
    if product is None or product.status == "deleted":
        return None
    return product
