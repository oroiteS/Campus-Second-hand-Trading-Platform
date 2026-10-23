"""scoped_query 首次落地测试：scope_all 直通 / 学生过滤注入 / 组合查询链可用。"""

from flask import g

from src.common.scope import scoped_query
from src.model import Category, Product


def _make_products(db, seller_id: int, category_id: int, school_ids: list[int]) -> list[int]:
    """给每所学校造一件在售商品（引用真实 seller/category），返回商品 id 列表。"""
    ids = []
    for i, school_id in enumerate(school_ids):
        product = Product(
            seller_id=seller_id,
            school_id=school_id,
            category_id=category_id,
            title=f"商品{i}",
            description="描述",
            price=100,
            condition="excellent",
            status="on_sale",
        )
        db.session.add(product)
        db.session.flush()
        ids.append(product.id)
    db.session.commit()
    return ids


def _seed(db, school_fixtures) -> tuple[int, int]:
    seller_id = 1
    category = Category(name="数码电子", sort_order=1, status="enabled")
    db.session.add(category)
    db.session.commit()
    return seller_id, category.id


class TestScopedQuery:
    def test_scope_all_passes_through(self, app, db_create_all, school_fixtures):
        """管理员（g.scope_all=True）→ 原样 model.query，跨校全量可见。"""
        seller_id, category_id = _seed(db_create_all, school_fixtures)
        _make_products(
            db_create_all,
            seller_id,
            category_id,
            [school_fixtures.multi.id, school_fixtures.single.id],
        )
        with app.test_request_context():
            g.scope_all = True
            g.school_id = None
            assert scoped_query(Product).count() == 2

    def test_student_scope_filters_by_school(self, app, db_create_all, school_fixtures):
        """学生（g.school_id 注入）→ 只查到本校商品，他校不可见。"""
        seller_id, category_id = _seed(db_create_all, school_fixtures)
        _make_products(
            db_create_all,
            seller_id,
            category_id,
            [school_fixtures.multi.id, school_fixtures.single.id],
        )
        with app.test_request_context():
            g.scope_all = False
            g.school_id = school_fixtures.multi.id
            query = scoped_query(Product)
            assert query.count() == 1
            assert query.all()[0].school_id == school_fixtures.multi.id

    def test_chained_query_composition(self, app, db_create_all, school_fixtures):
        """组合查询链可用：scoped_query 起点可继续 filter / order_by / offset。"""
        seller_id, category_id = _seed(db_create_all, school_fixtures)
        ids = _make_products(
            db_create_all, seller_id, category_id, [school_fixtures.multi.id] * 3
        )
        with app.test_request_context():
            g.scope_all = False
            g.school_id = school_fixtures.multi.id
            query = (
                scoped_query(Product)
                .filter(Product.status == "on_sale", Product.id.in_(ids))
                .order_by(Product.id.desc())
                .offset(1)
                .limit(2)
            )
            rows = query.all()
            assert len(rows) == 2
            assert rows[0].id > rows[1].id  # 倒序生效
            assert all(p.school_id == school_fixtures.multi.id for p in rows)
