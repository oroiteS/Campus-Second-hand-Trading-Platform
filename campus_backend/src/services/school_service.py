"""学校域服务：公开列表（仅启用、含校区、按名称排序、不分页）。"""

from src.model import School, db


def list_enabled() -> list[dict]:
    """全部启用的学校与校区，按名称排序，返回契约 SchoolWithCampuses 裸数据。

    不分页——数据量小，注册/认证页选择器需一次取全（契约注明该取舍）；
    停用学校与停用校区一律不出现。维护入口属批次 5 管理域。
    """
    schools = list(
        db.session.scalars(
            db.select(School).where(School.status == "enabled").order_by(School.name)
        )
    )
    result: list[dict] = []
    for school in schools:
        item = school.ref_dict()
        # relationship 已按名称排序；仅暴露启用中的校区
        item["campuses"] = [
            campus.ref_dict() for campus in school.campuses if campus.status == "enabled"
        ]
        result.append(item)
    return result
