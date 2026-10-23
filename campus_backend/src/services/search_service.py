"""向量搜索服务（b2be2）：Chroma 余弦召回 → MySQL 精筛保序分页 + LIKE 降级。

四要素（契约 §3.1 search）：① q 拼检索指令前缀（``EMBEDDING_QUERY_PREFIX``）
→ embedding；② Chroma ``query(n_results=90)``（召回上限 60 的 1.5 倍供
过滤损耗），where 本校 + ``status=on_sale`` 双条件（防跨校召回与已售泄
漏；管理员 scope_all 跨校只读，仅 status 条件——与列表口径一致）；③ 业
务精筛（分类/价格/成色/校区）在 MySQL 侧数据上进行；④ 结果按相似度
（召回序）保序分页。结果不写缓存（条件组合爆炸）。

**降级**（``is_available`` + 异常双判定）：MySQL ``LIKE %q%`` 标题匹配
（created_at 倒序），响应附加 ``degraded: true`` + ``degraded_reason``，
info 日志。LIKE 与列表 keyword 同口径：``%``/``_`` 不转义直配（参数化
无注入面，既有备案口径，b2be 评审记录）。
"""

from __future__ import annotations

import logging

from flask import g

from src.common import chroma_client, embedding_client
from src.common.errors import ApiError, ErrorCode
from src.model import Product
from src.services import product_service

logger = logging.getLogger(__name__)

# 召回上限：搜索召回 60 × 1.5 倍过滤损耗余量（任务卡钉死 90）
RECALL_LIMIT = 90
# 指令前缀与查询的拼接分隔（Qwen3 指令感知格式：指令独占一行在前）
_INSTRUCTION_SEP = "\n"
# q 长度上限（契约 §3.0 对照表）
QUERY_MAX = 100


def _fields_error(fields: dict[str, str]) -> ApiError:
    return ApiError(ErrorCode.VALIDATION_ERROR, data={"fields": fields})


def _validate_q(q: object) -> str:
    """q 必填 1–100 字符；空白视为未填写（契约 9001）。"""
    if not isinstance(q, str):
        raise _fields_error({"q": "搜索词长度须为 1–100 字符"})
    normalized = q.strip()
    if not normalized or len(normalized) > QUERY_MAX:
        raise _fields_error({"q": "搜索词长度须为 1–100 字符"})
    return normalized


def _apply_business_filters(products: list[Product], filters: dict) -> list[Product]:
    """MySQL 精筛的业务条件（保序过滤；价格 Decimal 直比，禁 float）。"""
    result = []
    for product in products:
        if filters["category_id"] is not None and product.category_id != filters["category_id"]:
            continue
        if filters["condition"] is not None and product.condition != filters["condition"]:
            continue
        if filters["price_min"] is not None and product.price < filters["price_min"]:
            continue
        if filters["price_max"] is not None and product.price > filters["price_max"]:
            continue
        if filters["campus_id"] is not None and product.campus_id != filters["campus_id"]:
            continue
        result.append(product)
    return result


def _paginate_items(items: list[Product], page: int, page_size: int) -> dict:
    """保序内存分页（候选 ≤ 90，无 N+1 顾虑；序列化复用概要形态）。"""
    total = len(items)
    offset = (page - 1) * page_size
    return {
        "items": [p.to_summary_dict() for p in items[offset : offset + page_size]],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": (total + page_size - 1) // page_size,
    }


def _where_clause() -> dict:
    """Chroma where：学生本校 + on_sale 双条件；管理员仅 on_sale（跨校只读）。"""
    status_condition = {"status": "on_sale"}
    if getattr(g, "scope_all", False):
        return status_condition
    return {"$and": [{"school_id": int(g.school_id)}, status_condition]}


def _vector_search(normalized_q: str, filters: dict, page: int, page_size: int) -> dict:
    """向量召回 → 精筛 → 保序分页；任何一步异常上抛给调用方降级。"""
    prefixed = f"{_query_prefix()}{_INSTRUCTION_SEP}{normalized_q}"
    vector = embedding_client.embed_texts([prefixed])[0]
    response = chroma_client.get_collection().query(
        query_embeddings=[vector],
        n_results=RECALL_LIMIT,
        where=_where_clause(),
    )
    ids = [int(item_id) for item_id in response["ids"][0]]
    # MySQL 精筛：id 保序取回（相似度序），再过业务条件
    products = product_service.get_on_sale_by_ids(
        g.school_id, ids, scope_all=getattr(g, "scope_all", False)
    )
    return _paginate_items(_apply_business_filters(products, filters), page, page_size)


def _query_prefix() -> str:
    """检索指令前缀（app.config 唯一读取处约定经 config）。"""
    from flask import current_app

    return current_app.config["EMBEDDING_QUERY_PREFIX"]


def _like_fallback(
    normalized_q: str, raw_filters: dict, reason: str, page: int, page_size: int
) -> dict:
    """LIKE 降级：MySQL 标题匹配（created_at 倒序）+ degraded 标记。

    复用公开的 ``product_service.list_on_sale``（scoped_query + on_sale +
    keyword LIKE 同口径 + newest 序 + 同分页与概要预载），不依赖其私有
    ``_paginate``/``_SUMMARY_LOADS``（跨 service 只用公开名）；``raw_filters``
    为路由层原始（未归一化）字典，值均为 str，由 list_on_sale 内的首次
    （唯一一次）校验完成归一化——不得透传已归一化值，否则 Decimal 过
    不 ``_parse_filter_decimal`` 的类型门 → 误 9001（N-1）。``sort`` 钉死
    newest，与原降级实现的固定排序保持一致。
    """
    result = product_service.list_on_sale(
        {**raw_filters, "keyword": normalized_q, "sort": "newest"}, page, page_size
    )
    result["degraded"] = True
    result["degraded_reason"] = reason
    return result


def search(user, q: str, filters: dict, page: int, page_size: int) -> dict:
    """向量搜索主入口（``GET /api/products/search``）。

    降级判定为 ``is_available`` + 异常双判定：探测不可用直接降级；探测
    可用但真实调用（embed/chroma query）失败同样降级，绝不 5xx。
    归一化校验仅向量路径需要（``_apply_business_filters`` 消费 Decimal 等
    强类型值）；降级路径传原始 filters，归一化由 ``list_on_sale`` 内的
    校验完成（N-1：避免归一化后二次校验类型门拒收 Decimal）。
    """
    normalized_q = _validate_q(q)

    available, probe_reason = embedding_client.is_available()
    if available:
        normalized_filters = product_service._validate_list_filters(filters)
        try:
            return _vector_search(normalized_q, normalized_filters, page, page_size)
        except Exception as exc:  # noqa: BLE001 - 向量链路异常 → LIKE 降级
            reason = f"向量检索异常，已降级为 MySQL LIKE 检索: {type(exc).__name__}: {exc}"
    else:
        reason = f"embedding 不可用（{probe_reason}），已降级为 MySQL LIKE 检索"
    logger.info("搜索降级 q=%r user_id=%s: %s", normalized_q, user.id, reason)
    return _like_fallback(normalized_q, filters, reason, page, page_size)
