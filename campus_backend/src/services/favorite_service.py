"""收藏域服务：收藏 / 取消（幂等）/ 我的收藏列表。

事务边界：收藏 = Favorite 写入 + favorite_count SQL 原子自增**同一事务**
（重复收藏靠 uk_user_product 兜底，IntegrityError 回滚后转 9003，计数不
漂移）；emit 一律在 commit 之后。防探测：非本校/不存在一律 404/9002。
"""

from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError

from src.common.errors import ApiError, ErrorCode
from src.model import Favorite, Product, db, iso8
from src.services import events
from src.services.product_service import (
    _STATUS_LABELS,
    _SUMMARY_LOADS,
    _admin_rejected,
    _product_not_found,
    invalidate_detail_cache,
)


def _scoped_product_or_404(user, product_id: int) -> Product:
    """取本校商品（学生视角）；不存在/他校一律 404/9002（防探测）。

    管理员不适用（收藏接口对管理员 9003，先于此拦下）。
    """
    product = db.session.get(Product, product_id)
    if product is None or product.school_id != user.school_id:
        raise _product_not_found()
    return product


def favorite(user, product_id: int) -> dict:
    """收藏：仅本校 on_sale；重复 → 9003（uk 兜底）；emit FAVORITE_CHANGED。"""
    if user.role == "admin":
        raise _admin_rejected("收藏商品")
    product = _scoped_product_or_404(user, product_id)
    if product.status != "on_sale":
        raise ApiError(
            ErrorCode.PRODUCT_STATUS_CONFLICT,
            message=(
                f"商品当前状态为{_STATUS_LABELS[product.status]}，仅上架商品可收藏"
            ),
        )
    db.session.add(Favorite(user_id=user.id, product_id=product.id))
    # SQL 原子自增（读改写会丢并发更新）；updated_at 显式保持。
    # 注意：execute 会先 autoflush 上面的 INSERT，故 try 须覆盖整段变更。
    try:
        db.session.execute(
            sa_update(Product)
            .where(Product.id == product.id)
            .values(
                favorite_count=Product.favorite_count + 1, updated_at=Product.updated_at
            )
        )
        db.session.commit()
    except IntegrityError:  # uk_user_product 撞唯一约束（并发重复收藏）
        db.session.rollback()
        raise ApiError(ErrorCode.CONFLICT, message="已收藏该商品") from None
    db.session.refresh(product)
    # 收藏数变化影响 detail 缓存体内的 favorite_count，顺带失效
    invalidate_detail_cache(product)
    events.emit(events.FAVORITE_CHANGED, user.id, product, True)
    return {"favorited": True, "favorite_count": product.favorite_count}


def unfavorite(user, product_id: int) -> dict:
    """取消收藏（幂等）：无记录直接返回当前计数；仅实际删除时 emit。"""
    if user.role == "admin":
        raise _admin_rejected("收藏商品")
    product = _scoped_product_or_404(user, product_id)
    if product.status == "deleted":
        raise _product_not_found()  # 已删商品不可见（防探测口径一致）
    record = (
        db.session.query(Favorite)
        .filter(Favorite.user_id == user.id, Favorite.product_id == product.id)
        .first()
    )
    if record is None:
        return {"favorited": False, "favorite_count": product.favorite_count}
    db.session.delete(record)
    db.session.execute(
        sa_update(Product)
        .where(Product.id == product.id, Product.favorite_count > 0)
        .values(favorite_count=Product.favorite_count - 1, updated_at=Product.updated_at)
    )
    db.session.commit()
    db.session.refresh(product)
    invalidate_detail_cache(product)
    events.emit(events.FAVORITE_CHANGED, user.id, product, False)
    return {"favorited": False, "favorite_count": product.favorite_count}


def my_favorites(user, page: int, page_size: int) -> dict:
    """收藏列表：join 商品排除 deleted，按收藏时间倒序；条目含 favorited_at。

    对返回的 Product 套用与商品列表同一组 ``_SUMMARY_LOADS`` 预载，
    规避 ``to_summary_dict`` 逐行懒加载的 N+1（分页语义与排序不变）。
    """
    query = (
        db.session.query(Favorite, Product)
        .join(Product, Favorite.product_id == Product.id)
        .options(*_SUMMARY_LOADS)
        .filter(Favorite.user_id == user.id, Product.status != "deleted")
        .order_by(Favorite.created_at.desc(), Favorite.id.desc())
    )
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [
            {**product.to_summary_dict(), "favorited_at": iso8(favorite.created_at)}
            for favorite, product in rows
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": (total + page_size - 1) // page_size,
    }
