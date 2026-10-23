"""数据库实例与 ORM 模型集中定义（b1 用户域五模型 + b2 商品域四模型）。

分层规则：本文件是依赖链最底层，禁止 import 本项目任何其他模块；
模型方法仅放单行数据行为（序列化 ``to_dict`` / 纯计算 ``display_name_recalc``），
跨行业务一律在 services。
"""

import os
from datetime import datetime, timedelta, timezone

from flask_sqlalchemy import SQLAlchemy

# db 实例全项目唯一，只能在 model.py 创建；app.py 仅做 init_app。
db = SQLAlchemy()

# 契约格式约定：时间一律 ISO 8601 含 +08:00 偏移（统一东八区）。
_CST = timezone(timedelta(hours=8))

# 主键列：契约 id 为 int64，MySQL 用 BIGINT 自增；SQLite 测试库退回 INTEGER
# （SQLite 仅 INTEGER PRIMARY KEY 才是 rowid 别名，BIGINT 主键不会自增）。
_PK = db.BigInteger().with_variant(db.Integer, "sqlite")


def prefix(name: str) -> str:
    """表名前缀助手：业务模型统一写 ``__tablename__ = prefix("users")``。

    唯一例外点：``__tablename__`` 在类定义期求值，早于任何应用上下文，
    无法读 ``app.config``，故此处直接 ``os.getenv``。其成立的前提是
    ``src/app.py`` 的 import 顺序保证 ``src.config``（load_dotenv）先于
    本模块加载；除本函数外，项目任何位置不得直接读环境变量。

    同机制也适用于 **schema 级唯一**的显式命名：外键约束名在 MySQL 8.0+
    要求数据库内唯一（重复报错 1826），不随表名加前缀会让主仓与同库
    worktree 各自 upgrade 撞名，因此同样经 ``prefix()`` 生成（见下方
    ``FK_USERS_AVATAR_IMAGE``）。普通/唯一索引名仅要求表内唯一
    （MySQL 跨表同名索引合法），保持裸名，不参与前缀。
    """
    return f"{os.getenv('DB_TABLE_PREFIX', '')}{name}"


# users.avatar_image_id → images.id 成环 FK 的显式约束名：模型与迁移脚本
# （ForeignKeyConstraint 声明 / create_foreign_key / drop_constraint 三处）
# 一律引用本常量，单一来源；主仓空前缀 → ``fk_users_avatar_image``，
# worktree ``b1be-`` → ``b1be-fk_users_avatar_image``。
FK_USERS_AVATAR_IMAGE = prefix("fk_users_avatar_image")

# ---- b2 商品域 FK 约束名（模型与迁移建/删两处统一引用，单一来源）----
# MySQL 8.0+ 外键约束名 schema 内唯一（重复报错 1826），与同库并存的
# 主仓/其他 worktree 不撞名必须随前缀参数化；普通/唯一索引名仅表内唯一，
# 保持裸名（backend/00「迁移纪律」）。
FK_PRODUCTS_SELLER = prefix("fk_products_seller")            # products.seller_id → users
FK_PRODUCTS_SCHOOL = prefix("fk_products_school")            # products.school_id → schools
FK_PRODUCTS_CAMPUS = prefix("fk_products_campus")        # products.campus_id → campuses
FK_PRODUCTS_CATEGORY = prefix("fk_products_category")    # products.category_id → categories
# product_images.product_id → products / product_images.image_id → images
FK_PRODUCT_IMAGES_PRODUCT = prefix("fk_product_images_product")
FK_PRODUCT_IMAGES_IMAGE = prefix("fk_product_images_image")
FK_FAVORITES_USER = prefix("fk_favorites_user")          # favorites.user_id → users
FK_FAVORITES_PRODUCT = prefix("fk_favorites_product")    # favorites.product_id → products


def _cst_now() -> datetime:
    """建行列默认值：当前东八区时间。"""
    return datetime.now(_CST)


def _iso8(value: datetime | None) -> str | None:
    """datetime → 契约 ISO 8601 字符串（+08:00）。

    naive 值视为库内东八区墙钟时间（写入侧恒为 ``_cst_now``），补挂偏移后
    归一到东八区输出；MySQL DATETIME 不保存时区，读回 naive 即此情形。
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=_CST)
    # 契约示例为秒级精度，序列化统一去掉微秒
    return value.astimezone(_CST).replace(microsecond=0).isoformat()


def iso8(value: datetime | None) -> str | None:
    """``_iso8`` 的公开别名：b2 起 services 组装响应（如 ``favorited_at``）
    需要同一套「naive 视为东八区 + 秒级精度」归一逻辑，公开复用而非各自实现。
    """
    return _iso8(value)


def _money(value) -> float | None:
    """金额 Decimal → 契约 number（两位小数语义由 DECIMAL(10,2) 列保证）。

    仅作序列化输出；业务比较/计算一律在 Decimal 域完成，禁 float 直比。
    """
    return None if value is None else float(value)


class School(db.Model):
    """学校（认证与展示用的公开基础数据，维护入口属批次 5 管理域）。"""

    __tablename__ = prefix("schools")

    id = db.Column(_PK, primary_key=True, autoincrement=True)
    name = db.Column(db.String(64), nullable=False, unique=True)
    multi_campus = db.Column(db.Boolean, nullable=False, default=False)
    status = db.Column(db.String(16), nullable=False, default="enabled")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_cst_now)

    campuses = db.relationship(
        "Campus", back_populates="school", order_by="Campus.name"
    )

    def ref_dict(self) -> dict:
        """契约 SchoolRef 概要形态。"""
        return {
            "id": self.id,
            "name": self.name,
            "multi_campus": bool(self.multi_campus),
        }


class Campus(db.Model):
    """校区；多校区不构成隔离边界，只影响展示与可选筛选。"""

    __tablename__ = prefix("campuses")
    __table_args__ = (db.Index("idx_school", "school_id"),)

    id = db.Column(_PK, primary_key=True, autoincrement=True)
    school_id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        db.ForeignKey(prefix("schools.id")),
        nullable=False,
    )
    name = db.Column(db.String(64), nullable=False)
    status = db.Column(db.String(16), nullable=False, default="enabled")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_cst_now)

    school = db.relationship("School", back_populates="campuses")

    def ref_dict(self) -> dict:
        """契约 CampusRef 概要形态。"""
        return {"id": self.id, "school_id": self.school_id, "name": self.name}


class Image(db.Model):
    """图片实体记录（文件落 uploads/，经鉴权路由 GET /api/images/{id} 访问）。"""

    __tablename__ = prefix("images")

    id = db.Column(_PK, primary_key=True, autoincrement=True)
    owner_id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        db.ForeignKey(prefix("users.id")),
        nullable=False,
    )
    # 相对 UPLOAD_DIR 的路径：<purpose>/<年月>/<内容哈希>.<扩展名>
    path = db.Column(db.String(255), nullable=False)
    mime = db.Column(db.String(64), nullable=False)
    size_bytes = db.Column(db.BigInteger, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    # 值域批次内为 avatar / student_card，批次 2 起商品图等随契约扩展
    purpose = db.Column(db.String(32), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_cst_now)

    def ref_dict(self) -> dict:
        """契约 ImageRef 概要形态（指向鉴权访问路由）。"""
        return {"id": self.id, "url": f"/api/images/{self.id}"}


class User(db.Model):
    """用户。username / student_no 注册后不可改；phone 空串清除存 NULL。"""

    __tablename__ = prefix("users")
    __table_args__ = (
        db.UniqueConstraint("username", name="uk_username"),
        db.UniqueConstraint("student_no", name="uk_student_no"),
        db.Index("idx_school_auth", "school_id", "auth_status"),
    )

    id = db.Column(_PK, primary_key=True, autoincrement=True)
    username = db.Column(db.String(32), nullable=False)
    student_no = db.Column(db.String(32), nullable=False)
    # bcrypt 加盐哈希（NFR-05），任何链路不得明文/可逆
    password_hash = db.Column(db.String(128), nullable=False)
    email = db.Column(db.String(254), nullable=False)
    nickname = db.Column(db.String(32), nullable=False)
    display_name = db.Column(db.String(160), nullable=False)
    # ^1\d{10}$；空串 = 清除（存 NULL），列本身 nullable
    phone = db.Column(db.String(11), nullable=True)
    school_id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        db.ForeignKey(prefix("schools.id")),
        nullable=True,
    )
    campus_id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        db.ForeignKey(prefix("campuses.id")),
        nullable=True,
    )
    # users ↔ images 双向引用成环，该侧 FK 以 use_alter 后置 ALTER 创建；
    # 约束名与迁移脚本共用 FK_USERS_AVATAR_IMAGE（MySQL 8.0+ schema 级唯一）
    avatar_image_id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        db.ForeignKey(prefix("images.id"), name=FK_USERS_AVATAR_IMAGE, use_alter=True),
        nullable=True,
    )
    role = db.Column(db.String(16), nullable=False, default="student")
    auth_status = db.Column(db.String(16), nullable=False, default="unverified")
    status = db.Column(db.String(16), nullable=False, default="active")
    # 信誉分：批次 3 起有评价后非空；两位小数
    credit_score = db.Column(db.Numeric(5, 2), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_cst_now)

    school = db.relationship("School", foreign_keys=[school_id])
    campus = db.relationship("Campus", foreign_keys=[campus_id])
    avatar = db.relationship("Image", foreign_keys=[avatar_image_id])

    def display_name_recalc(self, school: "School | None", campus: "Campus | None") -> str:
        """FR-USR-10 展示名生成（全项目单处实现）。

        认证通过（approved）后为「昵称-学校名称」，多校区学校再补
        「(校区名称)」；未认证为昵称。本批次经 approved 造数覆盖，
        批次 5 审核服务复用本入口。
        """
        if school is None:
            self.display_name = self.nickname
        else:
            name = f"{self.nickname}-{school.name}"
            if campus is not None:
                name = f"{name}({campus.name})"
            self.display_name = name
        return self.display_name

    def to_profile_dict(self) -> dict:
        """契约 UserProfile 完整形态（个人中心 / 注册 / 登录 / 更新响应）。"""
        return {
            "id": self.id,
            "username": self.username,
            "student_no": self.student_no,
            "email": self.email,
            "nickname": self.nickname,
            "display_name": self.display_name,
            "phone": self.phone,
            "avatar": self.avatar.ref_dict() if self.avatar is not None else None,
            "school": self.school.ref_dict() if self.school is not None else None,
            "campus": self.campus.ref_dict() if self.campus is not None else None,
            "role": self.role,
            "auth_status": self.auth_status,
            "status": self.status,
            "credit_score": (
                float(self.credit_score) if self.credit_score is not None else None
            ),
            "created_at": _iso8(self.created_at),
        }


class AuthApplication(db.Model):
    """校园认证申请；历史保留，驳回后可重提（审核动作属批次 5）。"""

    __tablename__ = prefix("auth_applications")
    __table_args__ = (db.Index("idx_user_status", "user_id", "status"),)

    id = db.Column(_PK, primary_key=True, autoincrement=True)
    user_id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        db.ForeignKey(prefix("users.id")),
        nullable=False,
    )
    school_id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        db.ForeignKey(prefix("schools.id")),
        nullable=False,
    )
    campus_id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        db.ForeignKey(prefix("campuses.id")),
        nullable=True,
    )
    # 提交时须与注册学号完全一致（防代认证）；快照存申请时的值
    student_no = db.Column(db.String(32), nullable=False)
    real_name = db.Column(db.String(32), nullable=False)
    student_card_image_id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        db.ForeignKey(prefix("images.id")),
        nullable=False,
    )
    # pending / approved / rejected
    status = db.Column(db.String(16), nullable=False, default="pending")
    reject_reason = db.Column(db.String(255), nullable=True)
    reviewer_id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        db.ForeignKey(prefix("users.id")),
        nullable=True,
    )
    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_cst_now)

    school = db.relationship("School", foreign_keys=[school_id])
    campus = db.relationship("Campus", foreign_keys=[campus_id])
    student_card = db.relationship("Image", foreign_keys=[student_card_image_id])

    def to_dict(self) -> dict:
        """契约 AuthApplication 形态。"""
        return {
            "id": self.id,
            "school": self.school.ref_dict(),
            "campus": self.campus.ref_dict() if self.campus is not None else None,
            "student_no": self.student_no,
            "real_name": self.real_name,
            "student_card": self.student_card.ref_dict(),
            "status": self.status,
            "reject_reason": self.reject_reason,
            "reviewed_at": _iso8(self.reviewed_at),
            "created_at": _iso8(self.created_at),
        }


# ============================================================
# b2 商品域四模型（Category / Product / ProductImage / Favorite）
# ============================================================


class Category(db.Model):
    """商品分类（全局单级，维护入口属批次 5 管理域；本批仅读侧）。"""

    __tablename__ = prefix("categories")
    __table_args__ = (db.UniqueConstraint("name", name="uk_name"),)

    id = db.Column(_PK, primary_key=True, autoincrement=True)
    name = db.Column(db.String(64), nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    # enabled / disabled
    status = db.Column(db.String(16), nullable=False, default="enabled")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_cst_now)

    def ref_dict(self) -> dict:
        """契约 CategoryRef 概要形态。"""
        return {"id": self.id, "name": self.name}


# 成色 5 档（契约 ProductCondition，2026-10-21 用户确认定稿，双端不得私改）
PRODUCT_CONDITIONS = ("brand_new", "as_new", "excellent", "good", "fair")
# 商品状态机（契约 ProductStatus；trading/sold 流入边属 b3，forced_off 写入属 b5）
PRODUCT_STATUSES = ("on_sale", "trading", "sold", "off_sale", "deleted")
# 敏感词复核状态（契约 ModerationStatus；词库与匹配属 b5，本批恒 normal）
MODERATION_STATUSES = ("normal", "pending_review", "handled")


class Product(db.Model):
    """商品。``school_id`` 为冗余隔离列（写入时落，读取侧 scoped_query 单列过滤）。

    ``forced_off`` 为管理员强下标记（b5 写入）：卖家重新上架时 service 据此
    拒绝（3002）。价格全链路 Decimal（DECIMAL(10,2)），模型 CHECK 仅兜底，
    业务校验在 service（模型层不抛业务码）。
    """

    __tablename__ = prefix("products")
    __table_args__ = (
        db.Index("idx_school_status_created", "school_id", "status", "created_at"),
        db.Index("idx_seller_status", "seller_id", "status"),
        db.Index("idx_category", "category_id"),
        db.CheckConstraint("price >= 0.01 AND price <= 99999.99"),
        db.CheckConstraint(
            "original_price IS NULL OR (original_price >= 0.01 AND original_price <= 99999.99)"
        ),
    )

    id = db.Column(_PK, primary_key=True, autoincrement=True)
    seller_id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        db.ForeignKey(prefix("users.id"), name=FK_PRODUCTS_SELLER),
        nullable=False,
    )
    school_id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        db.ForeignKey(prefix("schools.id"), name=FK_PRODUCTS_SCHOOL),
        nullable=False,
    )
    campus_id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        db.ForeignKey(prefix("campuses.id"), name=FK_PRODUCTS_CAMPUS),
        nullable=True,
    )
    category_id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        db.ForeignKey(prefix("categories.id"), name=FK_PRODUCTS_CATEGORY),
        nullable=False,
    )
    title = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    original_price = db.Column(db.Numeric(10, 2), nullable=True)
    condition = db.Column(db.String(16), nullable=False)
    status = db.Column(db.String(16), nullable=False, default="on_sale")
    moderation_status = db.Column(db.String(16), nullable=False, default="normal")
    forced_off = db.Column(db.Boolean, nullable=False, default=False)
    view_count = db.Column(db.Integer, nullable=False, default=0)
    favorite_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_cst_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_cst_now, onupdate=_cst_now
    )
    # 成交时间（b3 订单完成时写入）
    sold_at = db.Column(db.DateTime(timezone=True), nullable=True)

    seller = db.relationship("User", foreign_keys=[seller_id])
    category = db.relationship("Category", foreign_keys=[category_id])
    campus = db.relationship("Campus", foreign_keys=[campus_id])
    # 图集关联（数组序=展示排序）；重写图集经 reassign 交给 delete-orphan
    product_images = db.relationship(
        "ProductImage",
        order_by="ProductImage.sort_order",
        cascade="all, delete-orphan",
        back_populates="product",
    )

    def _seller_summary_dict(self) -> dict:
        """契约 UserSummary 形态（卖家卡片；b3 前信誉分恒 null）。"""
        seller = self.seller
        return {
            "id": seller.id,
            "display_name": seller.display_name,
            "nickname": seller.nickname,
            "avatar": seller.avatar.ref_dict() if seller.avatar is not None else None,
            "credit_score": (
                float(seller.credit_score) if seller.credit_score is not None else None
            ),
            "auth_status": seller.auth_status,
            "role": seller.role,
        }

    def to_summary_dict(self) -> dict:
        """契约 ProductSummary 概要形态（列表/搜索/推荐/状态变更响应共用）。"""
        first = self.product_images[0].image if self.product_images else None
        return {
            "id": self.id,
            "title": self.title,
            "price": _money(self.price),
            "original_price": _money(self.original_price),
            "condition": self.condition,
            "status": self.status,
            "cover": first.ref_dict() if first is not None else None,
            "favorite_count": self.favorite_count,
            "category": self.category.ref_dict() if self.category is not None else None,
            "seller": self._seller_summary_dict(),
            "campus": self.campus.ref_dict() if self.campus is not None else None,
            "created_at": _iso8(self.created_at),
        }

    def to_detail_dict(self) -> dict:
        """契约 ProductDetail 的商品本体形态。

        **不含** ``view_count``（每次详情 +1）与 ``is_favorited``（随观看者
        变化）：两者由 service 组装响应时补齐，缓存亦只落本方法输出
        （任务卡「缓存商品本体序列化」约定）。
        """
        data = self.to_summary_dict()
        data.update(
            {
                "description": self.description,
                "images": [pi.image.ref_dict() for pi in self.product_images],
                "updated_at": _iso8(self.updated_at),
            }
        )
        return data


class ProductImage(db.Model):
    """商品-图片关联（数组序=展示排序；孤儿清理经 idx_image 反查引用）。"""

    __tablename__ = prefix("product_images")
    __table_args__ = (
        db.UniqueConstraint("product_id", "image_id", name="uk_product_image"),
        db.Index("idx_image", "image_id"),
    )

    id = db.Column(_PK, primary_key=True, autoincrement=True)
    product_id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        db.ForeignKey(prefix("products.id"), name=FK_PRODUCT_IMAGES_PRODUCT),
        nullable=False,
    )
    image_id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        db.ForeignKey(prefix("images.id"), name=FK_PRODUCT_IMAGES_IMAGE),
        nullable=False,
    )
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    product = db.relationship("Product", back_populates="product_images")
    image = db.relationship("Image")


class Favorite(db.Model):
    """商品收藏（重复收藏靠 uk_user_product 兜底转 9003；软删商品的收藏保留）。"""

    __tablename__ = prefix("favorites")
    __table_args__ = (
        db.UniqueConstraint("user_id", "product_id", name="uk_user_product"),
        db.Index("idx_user", "user_id"),
    )

    id = db.Column(_PK, primary_key=True, autoincrement=True)
    user_id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        db.ForeignKey(prefix("users.id"), name=FK_FAVORITES_USER),
        nullable=False,
    )
    product_id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        db.ForeignKey(prefix("products.id"), name=FK_FAVORITES_PRODUCT),
        nullable=False,
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_cst_now)
