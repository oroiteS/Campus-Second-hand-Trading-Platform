"""同校作用域查询改写（隔离三件套第 3 件的首次落地，backend/00）。

商品域含 ``school_id`` 列的模型（当前为 ``Product``）查询一律经
``scoped_query(model)`` 获取起点，禁止业务代码裸 ``Model.query``——
学生自动注入 ``school_id = g.school_id`` 过滤，管理员（``g.scope_all``）
跨校直通。不含 ``school_id`` 的模型（Category / ProductImage / Favorite
等全局表或纯关联表）不适用本函数，其作用域由解析商品时的本校校验保证。
"""

from flask import g


def scoped_query(model):
    """返回注入同校过滤的查询起点（需在请求上下文内调用）。

    - ``g.scope_all=True``（管理员）→ 原样 ``model.query``（跨校只读）；
    - 否则 → ``model.query.filter_by(school_id=g.school_id)``。

    仅对含 ``school_id`` 列的模型有意义；``model`` 形参保持宽松以匹配
    Flask-SQLAlchemy 的 ``Model.query`` 风格（误传无 ``school_id`` 的模型
    会在 filter_by 处立即 AttributeError，属开发期显式失败）。
    """
    if getattr(g, "scope_all", False):
        return model.query
    return model.query.filter_by(school_id=g.school_id)
