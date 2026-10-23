"""b2 product domain tables

Revision ID: 0ba95ef975bf
Revises: b7da4a2a0b72
Create Date: 2026-10-23 13:10:00.000000

商品域四表（categories / products / product_images / favorites）+ 索引。

- 表名经 ``src.model.prefix()`` 统一包裹（随 ``DB_TABLE_PREFIX`` 变化，
  业务代码与 Alembic 版本表保持同一前缀机制，与主库同库共存不撞名）。
- 显式命名 FK 约束名同样经前缀参数化（MySQL 8.0+ 约束名 schema 内唯一，
  重复报错 1826）：模型与迁移脚本统一引用 ``src.model`` 的 FK_* 常量，
  单一来源。索引名/唯一约束名仅表内唯一，保持裸名。
- price / original_price 的 CHECK 仅兜底（业务校验在 service），匿名约束
  由 MySQL 自动命名为 ``<前缀表名>_chk_N``，天然随表前缀隔离。
- 本批新表只引用 b1 旧表，无成环 FK，全部约束随 CREATE TABLE 内联创建；
  downgrade 按依赖逆序 DROP（约束随表消失）。
"""

from alembic import op
import sqlalchemy as sa

from src.model import (
    FK_FAVORITES_PRODUCT,
    FK_FAVORITES_USER,
    FK_PRODUCT_IMAGES_IMAGE,
    FK_PRODUCT_IMAGES_PRODUCT,
    FK_PRODUCTS_CAMPUS,
    FK_PRODUCTS_CATEGORY,
    FK_PRODUCTS_SCHOOL,
    FK_PRODUCTS_SELLER,
    prefix,
)

# revision identifiers, used by Alembic.
revision = '0ba95ef975bf'
down_revision = 'b7da4a2a0b72'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        prefix("categories"),
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uk_name'),
    )
    op.create_table(
        prefix("products"),
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('seller_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
        sa.Column('school_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
        sa.Column('campus_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
        sa.Column('category_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
        sa.Column('title', sa.String(length=50), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('original_price', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('condition', sa.String(length=16), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('moderation_status', sa.String(length=16), nullable=False),
        sa.Column('forced_off', sa.Boolean(), nullable=False),
        sa.Column('view_count', sa.Integer(), nullable=False),
        sa.Column('favorite_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sold_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint('price >= 0.01 AND price <= 99999.99'),
        sa.CheckConstraint('original_price IS NULL OR (original_price >= 0.01 AND original_price <= 99999.99)'),
        sa.ForeignKeyConstraint(['seller_id'], [prefix("users.id")], name=FK_PRODUCTS_SELLER),
        sa.ForeignKeyConstraint(['school_id'], [prefix("schools.id")], name=FK_PRODUCTS_SCHOOL),
        sa.ForeignKeyConstraint(['campus_id'], [prefix("campuses.id")], name=FK_PRODUCTS_CAMPUS),
        sa.ForeignKeyConstraint(['category_id'], [prefix("categories.id")], name=FK_PRODUCTS_CATEGORY),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table(prefix("products"), schema=None) as batch_op:
        batch_op.create_index('idx_school_status_created', ['school_id', 'status', 'created_at'], unique=False)
        batch_op.create_index('idx_seller_status', ['seller_id', 'status'], unique=False)
        batch_op.create_index('idx_category', ['category_id'], unique=False)
    op.create_table(
        prefix("product_images"),
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('product_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
        sa.Column('image_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['product_id'], [prefix("products.id")], name=FK_PRODUCT_IMAGES_PRODUCT),
        sa.ForeignKeyConstraint(['image_id'], [prefix("images.id")], name=FK_PRODUCT_IMAGES_IMAGE),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('product_id', 'image_id', name='uk_product_image'),
    )
    with op.batch_alter_table(prefix("product_images"), schema=None) as batch_op:
        batch_op.create_index('idx_image', ['image_id'], unique=False)
    op.create_table(
        prefix("favorites"),
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
        sa.Column('product_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], [prefix("users.id")], name=FK_FAVORITES_USER),
        sa.ForeignKeyConstraint(['product_id'], [prefix("products.id")], name=FK_FAVORITES_PRODUCT),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'product_id', name='uk_user_product'),
    )
    with op.batch_alter_table(prefix("favorites"), schema=None) as batch_op:
        batch_op.create_index('idx_user', ['user_id'], unique=False)


def downgrade():
    # 依赖逆序 DROP；FK 约束随表消失，无需显式 drop_constraint（无成环）。
    op.drop_table(prefix("favorites"))
    op.drop_table(prefix("product_images"))
    op.drop_table(prefix("products"))
    op.drop_table(prefix("categories"))
