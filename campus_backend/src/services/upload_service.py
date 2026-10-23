"""上传域服务：商品图上传（五件套复用）与孤儿清理。

上传经 ``common/uploads.validate_and_save(file, purpose="product")`` 落
``uploads/product/<年月>/``；images 记录随本层事务提交。孤儿清理在应用
启动时执行一次（app.py 装配，TESTING 跳过），日志输出结果。
"""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import current_app

from src.common import uploads
from src.common.errors import ApiError, ErrorCode
from src.model import Image, ProductImage, db

logger = logging.getLogger(__name__)

# 孤子判定：purpose=product 且超龄且无 product_images 引用
ORPHAN_DEFAULT_HOURS = 24
_CST = timezone(timedelta(hours=8))


def save_product_image(user, file_storage) -> Image:
    """五件套校验落盘 + images 入库（owner=本人；发布前即孤儿）。

    管理员一律 9003（无交易能力，与发布/编辑/收藏同口径）。
    """
    if user.role == "admin":
        raise ApiError(ErrorCode.CONFLICT, message="管理员无交易能力，不能上传商品图片")
    image = uploads.validate_and_save(file_storage, purpose="product")
    image.owner_id = user.id
    db.session.add(image)
    db.session.commit()
    return image


def cleanup_orphan_product_images(older_than_hours: int = ORPHAN_DEFAULT_HOURS) -> int:
    """清理超龄无引用的商品图记录，返回清理数。

    三分支：
    - 无引用且超龄且 path 无其他记录共享 → 删记录 + 删文件；
    - 无引用且超龄但 path 被其他 images 记录共享（哈希改名致内容去重）→
      仅删记录不删文件；
    - 有 product_images 引用或未超龄 → 保留。
    """
    cutoff = datetime.now(_CST) - timedelta(hours=older_than_hours)
    referenced_ids = {row[0] for row in db.session.query(ProductImage.image_id).distinct()}
    candidates = (
        db.session.query(Image)
        .filter(
            Image.purpose == "product",
            Image.created_at < cutoff,
            ~Image.id.in_(referenced_ids),  # 空集时恒真（无任何引用）
        )
        .all()
    )
    cleaned = 0
    paths_to_unlink: list[str] = []
    for image in candidates:
        shared = (
            db.session.query(Image.id)
            .filter(Image.path == image.path, Image.id != image.id)
            .first()
            is not None
        )
        db.session.delete(image)
        if not shared:
            paths_to_unlink.append(image.path)
        cleaned += 1
    if cleaned:
        # 先 commit（记录删除生效）再删文件：若 commit 失败，文件仍在，
        # 记录与磁盘状态一致；反向顺序会造成「文件已删、记录仍在」。
        db.session.commit()
    for rel_path in paths_to_unlink:
        try:
            (Path(current_app.config["UPLOAD_DIR"]) / rel_path).unlink(missing_ok=True)
        except OSError as exc:  # 单个文件删除失败不中断其余清理
            logger.warning("孤儿文件删除失败（跳过）：%s: %s", rel_path, exc)
    logger.info(
        "孤儿商品图清理完成：删除 %d 条记录（older_than=%dh）", cleaned, older_than_hours
    )
    return cleaned


def run_startup_tasks() -> None:
    """应用启动任务入口（create_app 末尾调用，TESTING 跳过）。"""
    try:
        cleaned = cleanup_orphan_product_images()
        logger.info("启动任务：孤儿商品图清理 %d 条", cleaned)
    except Exception:  # noqa: BLE001 - 启动任务失败不阻断应用起服务
        logger.exception("启动任务失败（孤儿清理），已跳过")
