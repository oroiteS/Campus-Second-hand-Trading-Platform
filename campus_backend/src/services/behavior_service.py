"""行为流水与用户画像更新（b2be2）：点击 0.82 / 收藏 0.70，购买 0.55 属 b3。

规则（需求「用户画像更新」节，任务卡钉死）：

1. **流水无条件记录**（``user_behaviors`` 只增不改）；
2. 同一 (user_id, product_id, action) 24h 内第二次起**跳过画像更新**
   （流水照记）；
3. 更新公式 ``new = product_vec × (1-w) + old × w``；无画像时
   ``new = product_vec``（w=0 特例，避免零向量污染）；
4. **L2 归一化**后 upsert ``user_profiles``（模长恒 1，与 Chroma 余弦
   距离同构），``behavior_count`` 递增（用于判断脱离冷启动）。

取消收藏（favorited=False）仅记流水、不更新画像——权重公式只会把画像
拉向商品，没有「拉离」语义（任务卡未定义负向更新，b3 购买接入时再议）。
商品向量缺失时先以 ``is_available()`` 快速探测 embedding 可用性（TCP 级
约 1s 超时），可用才现场 ``embed_texts`` 补算——探测失败直接跳过（流水
照记、画像跳过、不报错），避免请求线程内最长约 20s 的现场补算阻塞详情
响应（契约：画像记录不影响响应延迟）；探测可用但补算失败同样跳过
（向量侧已有重试队列补偿，此处不重复入队）。

陈旧画像防御（B-2 / S-3）：旧画像与新商品向量必须**同维且同模型**才能
混合——混维写库会让 Chroma 查询抛维度错误、该用户推荐永久降级。任一
不符即整条丢弃旧画像（``new = product_vec``、``behavior_count = 1``）并
记 error 日志；``dim`` 字段一律写真实向量长度，不写配置值。

熔断短路（S-4 保守缓解）：Mongo 故障期每次详情同步写画像最坏多付 2s
（``serverSelectionTimeoutMS``），与 NFR-02 冲突。模块级**连续**失败计数 +
冷却窗口：连续失败达阈值（3 次）才开启熔断——单次瞬时抖动不再影响同进程
其他用户；冷却期（30s）内直接跳过行为写入（仅 debug 日志），期满自动
**半开**：放行 1 次真实探测尝试，成功即清零关闭，失败则续期下一窗口。
不改同步语义，不加线程。
"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timedelta

from flask import current_app

from src.common import embedding_client, mongo_client
from src.services.vector_service import CST, build_text, now_cst

logger = logging.getLogger(__name__)

# 行为权重（需求「用户画像更新」节；购买 0.55 属 b3 订单接入时扩展）
ACTION_WEIGHTS = {"view": 0.82, "favorite": 0.70}
# 画像去重窗口（小时）：同 (user, product, action) 窗口内只更新一次画像
DEDUP_HOURS = 24

# 熔断参数（S-4）：连续失败达阈值后冷却 N 秒，期间行为写入直接跳过；
# 冷却期满自动半开（放行一次真实尝试，失败续期、成功关闭）。
BREAKER_THRESHOLD = 3
BREAKER_COOLDOWN_S = 30.0

_failures = 0
_open_until = 0.0


def _circuit_open() -> bool:
    """熔断是否仍生效：未达阈值或冷却期满（半开）均返回 False。"""
    return _failures >= BREAKER_THRESHOLD and time.monotonic() < _open_until


def _note_failure(exc: Exception) -> None:
    """记一次失败；连续失败达阈值才开启冷却窗口（S-4 粒度收窄）。"""
    global _failures, _open_until
    _failures += 1
    if _failures < BREAKER_THRESHOLD:
        logger.warning(
            "行为写入失败（连续 %s 次，未达熔断阈值 %s）: %s",
            _failures,
            BREAKER_THRESHOLD,
            exc,
        )
        return
    _open_until = time.monotonic() + BREAKER_COOLDOWN_S
    logger.warning(
        "行为写入失败，画像写入熔断 %ss（连续失败 %s 次）: %s",
        BREAKER_COOLDOWN_S,
        _failures,
        exc,
    )


def _note_success() -> None:
    global _failures, _open_until
    _failures = 0
    _open_until = 0.0


def _reset_circuit_for_tests() -> None:
    """仅供测试：清空熔断状态。"""
    _note_success()


def _collections():
    database = mongo_client.get_db()
    return database["user_behaviors"], database["user_profiles"]


def _product_vector(product) -> list[float] | None:
    """取商品向量：Mongo 权威副本优先，缺失时探测后现场补算（不可得返回 None）。

    补算前先 ``is_available()`` 快速探测（约 1s 超时）：不可用即跳过
    补算（流水照记、画像跳过，不报错），避免请求线程内现场 embed（最长
    约 20s）阻塞详情响应；探测可用但真实调用失败同样跳过（双判定，与
    search/recommend 降级口径一致）。
    """
    collection = mongo_client.get_db()["product_vectors"]
    doc = collection.find_one({"product_id": int(product.id)})
    if doc is not None:
        stored = list(doc["vector"])
        if len(stored) == current_app.config["EMBEDDING_DIM"]:
            return stored
        # 存量商品向量维度不符（切模型未重建）：不得参与混合，改走现场补算
        logger.error(
            "商品存量向量维度不符，画像改用现场补算 product_id=%s got=%s expect=%s",
            product.id,
            len(stored),
            current_app.config["EMBEDDING_DIM"],
        )
    available, probe_reason = embedding_client.is_available()
    if not available:
        logger.warning(
            "商品向量缺失且 embedding 不可用（%s），画像更新跳过 product_id=%s",
            probe_reason,
            product.id,
        )
        return None
    try:
        category = product.category
        category_name = category.name if category is not None else ""
        vector = embedding_client.embed_texts([build_text(product, category_name)])[0]
    except Exception as exc:  # noqa: BLE001 - 补算失败：跳过本次画像更新
        logger.warning(
            "商品向量缺失且补算失败，画像更新跳过 product_id=%s: %s", product.id, exc
        )
        return None
    dim = current_app.config["EMBEDDING_DIM"]
    if len(vector) != dim:
        logger.error("商品向量补算维度不符，画像更新跳过 product_id=%s", product.id)
        return None
    return vector


def _l2_normalize(vector: list[float]) -> list[float]:
    """L2 归一化（模长恒 1，AC-08）；零向量防御性原样返回。"""
    norm = math.sqrt(sum(component * component for component in vector))
    if norm == 0:
        return vector
    return [component / norm for component in vector]


def _update_profile(user_id: int, product, weight: float, action: str) -> None:
    """画像更新（调用方已完成去重判定）；向量不可得时静默跳过。

    旧画像与新商品向量必须同维且同模型：否则整条丢弃（``new = product_vec``、
    计数归 1）并记 error 日志——混维写库会让 Chroma 查询永久报维度错误。
    """
    product_vector = _product_vector(product)
    if product_vector is None:
        return
    dim = current_app.config["EMBEDDING_DIM"]
    model = embedding_client.active_model()
    profiles = _collections()[1]
    profile = profiles.find_one({"user_id": user_id})
    if profile is None:
        new_vector = product_vector  # 无画像：new = product_vec（w=0 特例）
        behavior_count = 1
    else:
        old = list(profile["vector"])
        old_model = profile.get("model")
        if len(old) != dim or len(product_vector) != dim or old_model != model:
            logger.error(
                "画像与当前向量口径不一致，丢弃旧画像 user_id=%s old_dim=%s "
                "new_dim=%s dim=%s old_model=%s current_model=%s",
                user_id,
                len(old),
                len(product_vector),
                dim,
                old_model,
                model,
            )
            new_vector = product_vector
            behavior_count = 1
        else:
            new_vector = [
                product_component * (1 - weight) + old_component * weight
                for product_component, old_component in zip(
                    product_vector, old, strict=True
                )
            ]
            behavior_count = int(profile.get("behavior_count", 0)) + 1
    profiles.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "vector": _l2_normalize(new_vector),
                "dim": len(new_vector),  # 与真实长度一致，不写配置值
                "model": model,
                "behavior_count": behavior_count,
                "updated_at": now_cst(),
            }
        },
        upsert=True,
    )


def _record(user_id: int, product, action: str, source: str, favorited: bool = True) -> None:
    """流水无条件记录 + 画像 24h 去重更新（收藏取消仅记流水）。

    Mongo 故障经熔断短路（S-4）：冷却期内直接返回（仅 debug 日志），不抛异常。
    """
    if _circuit_open():
        logger.debug(
            "画像写入熔断中，跳过行为记录 user_id=%s product_id=%s action=%s",
            user_id,
            product.id,
            action,
        )
        return
    try:
        _write_behavior(user_id, product, action, source, favorited)
    except Exception as exc:  # noqa: BLE001 - 行为记录绝不影响详情响应
        _note_failure(exc)
    else:
        _note_success()


def _write_behavior(
    user_id: int, product, action: str, source: str, favorited: bool
) -> None:
    """落流水 + 按需更新画像（异常上抛给 ``_record`` 的熔断兜底）。"""
    weight = ACTION_WEIGHTS[action]
    behaviors, _profiles = _collections()
    cutoff = datetime.now(CST) - timedelta(hours=DEDUP_HOURS)
    dedup_hit = False
    # 取消收藏不更新画像，也不参与去重判定（B-W-2：取消不是同一行为方向，
    # 不得吃掉 24h 窗口）；其余按 (user, product, action) 最近一条的方向判定。
    if favorited or action != "favorite":
        # 有界查询：find_one + sort/limit(1) 只回最近一条；**不得**依赖
        # 游标真值判定（pymongo.Cursor 无 __bool__/__len__，空游标恒为真，
        # `if cursor:` + max() 会在首次行为时抛 ValueError 并吞掉流水）。
        latest = behaviors.find_one(
            {
                "user_id": user_id,
                "product_id": int(product.id),
                "action": action,
                "created_at": {"$gte": cutoff},
            },
            sort=[("created_at", -1)],
        )
        if latest is not None:
            dedup_hit = latest.get("favorited", True)
    record = {
        "user_id": user_id,
        "product_id": int(product.id),
        "action": action,
        "weight": weight,
        "school_id": int(product.school_id),
        "source": source,
        "created_at": now_cst(),
    }
    if action == "favorite":
        record["favorited"] = favorited  # 方向入流水：去重按最近方向判定
    behaviors.insert_one(record)
    if dedup_hit:
        logger.info(
            "画像 24h 去重跳过（流水已记）user_id=%s product_id=%s action=%s",
            user_id,
            product.id,
            action,
        )
        return
    if not favorited:
        return  # 取消收藏：仅流水，不更新画像
    _update_profile(user_id, product, weight, action)


def record_view(user_id: int, product) -> None:
    """点击行为（PRODUCT_VIEWED 订阅入口）：流水 + 画像（w=0.82）。"""
    _record(user_id, product, "view", source="detail")


def record_favorite(user_id: int, product, favorited: bool) -> None:
    """收藏/取消行为（FAVORITE_CHANGED 订阅入口）：流水；仅收藏更新画像。"""
    _record(user_id, product, "favorite", source="favorite", favorited=favorited)
