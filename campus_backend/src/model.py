"""数据库实例与 ORM 模型集中定义（批次 1：用户域五模型）。

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
    """
    return f"{os.getenv('DB_TABLE_PREFIX', '')}{name}"


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
    # users ↔ images 双向引用成环，该侧 FK 以 use_alter 后置 ALTER 创建
    avatar_image_id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        db.ForeignKey(prefix("images.id"), name="fk_users_avatar_image", use_alter=True),
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
