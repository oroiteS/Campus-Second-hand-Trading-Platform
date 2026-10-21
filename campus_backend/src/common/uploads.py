"""上传校验与落盘（NFR-07）。

五件套：扩展名（jpg/png/webp）+ MIME（与扩展名配对）+ 大小（≤
MAX_UPLOAD_MB）+ 内容魔数嗅探（客户端 MIME 可伪造，以文件头字节为
准）+ 文件名重写为内容 sha256。实体文件落
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


# ---- 内容魔数嗅探（联调 P2 修复）----
# 客户端声明的 MIME 与扩展名均可伪造，落盘前按文件头字节校验真实类型；
# 手写字节比较即可，不引入 python-magic 等新依赖。
def _match_png(head: bytes) -> bool:
    """PNG 签名：8 字节固定序列。"""
    return head.startswith(b"\x89PNG\r\n\x1a\n")


def _match_jpeg(head: bytes) -> bool:
    """JPEG SOI：前 3 字节 FF D8 FF。"""
    return head.startswith(b"\xff\xd8\xff")


def _match_webp(head: bytes) -> bool:
    """RIFF 容器：0-3 字节 RIFF，4-7 为小端长度（任意），8-11 为 WEBP。"""
    return head[:4] == b"RIFF" and head[8:12] == b"WEBP"


_MAGIC_BY_EXT = {
    "jpg": _match_jpeg,
    "png": _match_png,
    "webp": _match_webp,
}

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
    # 一次性读入（读后即持有全部字节）：魔数比较与 sha256 均基于同一
    # data，无需二次读流，也就不存在 seek(0) 复位问题。
    data = file_storage.read(max_bytes + 1)
    if len(data) == 0:
        raise _file_error("文件为空")
    if len(data) > max_bytes:
        raise _file_error(f"文件不得超过 {max_mb} MB")
    if not _MAGIC_BY_EXT[ext](data[:12]):
        raise _file_error("文件内容与声明类型不符，请上传真实的 jpg / png / webp 图片")

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
