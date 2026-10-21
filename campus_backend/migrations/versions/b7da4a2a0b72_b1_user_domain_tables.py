"""b1 user domain tables

Revision ID: b7da4a2a0b72
Revises: 9539b1447ed4
Create Date: 2026-10-21 09:07:21.665615

表名经 ``src.model.prefix()`` 统一包裹：随 ``DB_TABLE_PREFIX`` 环境变量
变化（主仓无前缀、开发槽位 ``b1be-``、集成 ``int1-``），业务代码与
Alembic 版本表（app.py 装配时注入）保持同一前缀机制。
"""

from alembic import op
import sqlalchemy as sa

from src.model import prefix

# revision identifiers, used by Alembic.
revision = 'b7da4a2a0b72'
down_revision = '9539b1447ed4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        prefix("schools"),
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('multi_campus', sa.Boolean(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_table(
        prefix("campuses"),
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('school_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['school_id'], [prefix("schools.id")]),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table(prefix("campuses"), schema=None) as batch_op:
        batch_op.create_index('idx_school', ['school_id'], unique=False)

    op.create_table(
        prefix("users"),
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('username', sa.String(length=32), nullable=False),
        sa.Column('student_no', sa.String(length=32), nullable=False),
        sa.Column('password_hash', sa.String(length=128), nullable=False),
        sa.Column('email', sa.String(length=254), nullable=False),
        sa.Column('nickname', sa.String(length=32), nullable=False),
        sa.Column('display_name', sa.String(length=160), nullable=False),
        sa.Column('phone', sa.String(length=11), nullable=True),
        sa.Column('school_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
        sa.Column('campus_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
        sa.Column('avatar_image_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('auth_status', sa.String(length=16), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('credit_score', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['avatar_image_id'], [prefix("images.id")],
            name='fk_users_avatar_image', use_alter=True,
        ),
        sa.ForeignKeyConstraint(['campus_id'], [prefix("campuses.id")]),
        sa.ForeignKeyConstraint(['school_id'], [prefix("schools.id")]),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('student_no', name='uk_student_no'),
        sa.UniqueConstraint('username', name='uk_username'),
    )
    with op.batch_alter_table(prefix("users"), schema=None) as batch_op:
        batch_op.create_index('idx_school_auth', ['school_id', 'auth_status'], unique=False)

    op.create_table(
        prefix("images"),
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('owner_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
        sa.Column('path', sa.String(length=255), nullable=False),
        sa.Column('mime', sa.String(length=64), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('purpose', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], [prefix("users.id")]),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        prefix("auth_applications"),
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
        sa.Column('school_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
        sa.Column('campus_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
        sa.Column('student_no', sa.String(length=32), nullable=False),
        sa.Column('real_name', sa.String(length=32), nullable=False),
        sa.Column('student_card_image_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('reject_reason', sa.String(length=255), nullable=True),
        sa.Column('reviewer_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['campus_id'], [prefix("campuses.id")]),
        sa.ForeignKeyConstraint(['reviewer_id'], [prefix("users.id")]),
        sa.ForeignKeyConstraint(['school_id'], [prefix("schools.id")]),
        sa.ForeignKeyConstraint(['student_card_image_id'], [prefix("images.id")]),
        sa.ForeignKeyConstraint(['user_id'], [prefix("users.id")]),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table(prefix("auth_applications"), schema=None) as batch_op:
        batch_op.create_index('idx_user_status', ['user_id', 'status'], unique=False)

    # users ↔ images 成环 FK（use_alter）：create_table 会跳过它，
    # 两表都存在后再显式补建（列级索引由 MySQL 随约束自动创建）。
    op.create_foreign_key(
        'fk_users_avatar_image', prefix("users"), prefix("images"),
        ['avatar_image_id'], ['id'],
    )


def downgrade():
    # 成环 FK 先显式摘除；二级索引随 DROP TABLE 一并消失——MySQL 中
    # idx_user_status / idx_school_auth 同时充当外键所需索引，不能先删。
    op.drop_constraint('fk_users_avatar_image', prefix("users"), type_='foreignkey')
    op.drop_table(prefix("auth_applications"))
    op.drop_table(prefix("images"))
    op.drop_table(prefix("users"))
    op.drop_table(prefix("campuses"))
    op.drop_table(prefix("schools"))
