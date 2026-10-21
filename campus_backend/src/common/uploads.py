"""上传四件套校验与落盘（NFR-07）。

四件套：扩展名（jpg/png/webp）+ MIME（与扩展名配对）+ 大小（≤
MAX_UPLOAD_MB）+ 文件名重写为内容 sha256。实体文件落
``UPLOAD_DIR/<purpose>/<年月>/``；images 表记录由调用方 service 随业务
同一事务提交（本模块只写文件、不碰 db.session）。
"""

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from flask import current_app

from src.common.errors import ApiError, ErrorCode
from src.model import Image

if TYPE_CHECKING:
    from werkzeug.datastructures import FileStorage

# 扩展名与 MIME 两两配对（契约：仅 jpg / png / webp）
_EXT_MIME = {
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}
# 值域随批次扩展（批次 2 起商品图等），当前与模型 purpose 注释一致
_PURPOSES = ("avatar", "student_card")

# 契约格式约定：统一东八区
_CST = timezone(timedelta(hours=8))


def _file_error(reason: str) -> ApiError:
    """契约 9001：字段级错误挂在 data.fields.file。"""
    return ApiError(ErrorCode.VALIDATION_ERROR, data={"fields": {"file": reason}})


def validate_and_save(file_storage: "FileStorage | None", purpose: str) -> Image:
    """校验并保存上传文件，返回**未入库**的 Image（owner 由 service 补齐提交）。"""
    if purpose not in _PURPOSES:
        raise ValueError(f"未知的上传用途: {purpose}")
    if file_storage is None or not file_storage.filename:
        raise _file_error("缺少上传文件")

    filename = file_storage.filename
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    expected_mime = _EXT_MIME.get(ext)
    if expected_mime is None:
        raise _file_error("仅支持 jpg / png / webp 图片")
    mime = (file_storage.mimetype or "").lower()
    if mime != expected_mime:
        raise _file_error("文件实际类型与扩展名不符或不受支持")

    max_mb = int(current_app.config["MAX_UPLOAD_MB"])
    max_bytes = max_mb * 1024 * 1024
    data = file_storage.read(max_bytes + 1)
    if len(data) == 0:
        raise _file_error("文件为空")
    if len(data) > max_bytes:
        raise _file_error(f"文件不得超过 {max_mb} MB")

    digest = hashlib.sha256(data).hexdigest()
    month_dir = datetime.now(_CST).strftime("%Y-%m")
    rel_path = f"{purpose}/{month_dir}/{digest}.{ext}"
    abs_dir = Path(current_app.config["UPLOAD_DIR"]) / purpose / month_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    (abs_dir / f"{digest}.{ext}").write_bytes(data)

    return Image(
        path=rel_path,
        mime=expected_mime,
        size_bytes=len(data),
        sha256=digest,
        purpose=purpose,
    )
