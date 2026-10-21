"""校园认证域服务：申请提交与我的历史（事务边界在本层提交）。

提交 = 图片记录 + 申请记录 + 用户状态置 pending，同一事务 commit，
部分失败全回滚；审核动作属批次 5，本批次经造数覆盖 approved 态。
"""

from typing import TYPE_CHECKING

from src.common import uploads
from src.common.errors import ApiError, ErrorCode
from src.model import AuthApplication, Campus, School, User, db

if TYPE_CHECKING:
    from werkzeug.datastructures import FileStorage

# 允许提交的认证状态（契约：pending / approved 不允许，管理员无需认证）
_SUBMITTABLE_STATUSES = ("unverified", "rejected")


def _fields_error(fields: dict[str, str]) -> ApiError:
    return ApiError(ErrorCode.VALIDATION_ERROR, data={"fields": fields})


def _parse_id(form, name: str, fields: dict[str, str], *, required: bool) -> int | None:
    """解析表单整数 id（multipart 字段均为字符串），异常写入字段错误。"""
    raw = form.get(name)
    if raw is None or raw == "":
        if required:
            fields[name] = "必填"
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        fields[name] = "必须为整数"
        return None
    if value < 1:
        fields[name] = "必须为正整数"
        return None
    return value


def submit(
    user: User, form, file_storage: "FileStorage | None"
) -> AuthApplication:
    """提交认证申请；表单复验 9001，状态闸门 9003（管理员提交亦 9003）。"""
    # 1) 状态闸门（先于文件校验，避免无谓的落盘）
    if user.role == "admin":
        raise ApiError(ErrorCode.CONFLICT, message="管理员无需校园认证")
    if (
        user.role != "student"
        or user.auth_status not in _SUBMITTABLE_STATUSES
    ):
        raise ApiError(ErrorCode.CONFLICT)  # pending / approved 重复提交

    # 2) 表单字段独立复验（不信任客户端）
    fields: dict[str, str] = {}
    school_id = _parse_id(form, "school_id", fields, required=True)
    campus_id = _parse_id(form, "campus_id", fields, required=False)

    real_name = form.get("real_name")
    if not isinstance(real_name, str) or not 1 <= len(real_name) <= 32:
        fields["real_name"] = "真实姓名长度须为 1–32 字符"

    student_no = form.get("student_no")
    if student_no != user.student_no:  # 防代认证：须与注册学号完全一致
        fields["student_no"] = "学号须与注册学号完全一致"

    school = db.session.get(School, school_id) if school_id is not None else None
    if school is None or school.status != "enabled":
        fields["school_id"] = "学校不存在或已停用"
    elif school.multi_campus:
        campus = db.session.get(Campus, campus_id) if campus_id is not None else None
        if campus is None or campus.school_id != school.id or campus.status != "enabled":
            fields["campus_id"] = "多校区学校必须选择该校启用中的校区"
    elif campus_id is not None:
        fields["campus_id"] = "单校区学校必须省略校区"

    if fields:
        raise _fields_error(fields)

    # 3) 学生证照片四件套（类型/大小不符 → 9001 fields.file）
    image = uploads.validate_and_save(file_storage, "student_card")
    image.owner_id = user.id

    # 4) 同一事务：图片 + 申请 + 用户状态 pending，部分失败全回滚
    application = AuthApplication(
        user_id=user.id,
        school_id=school.id,
        campus_id=campus_id,
        student_no=user.student_no,
        real_name=real_name,
        status="pending",
    )
    application.student_card = image
    user.auth_status = "pending"
    db.session.add(image)
    db.session.add(application)
    db.session.commit()
    return application


def my_applications(user_id: int) -> list[AuthApplication]:
    """我的全部认证申请，created_at 倒序；不分页（个人历史量小，契约注明）。"""
    return list(
        db.session.scalars(
            db.select(AuthApplication)
            .where(AuthApplication.user_id == user_id)
            .order_by(AuthApplication.created_at.desc(), AuthApplication.id.desc())
        )
    )
