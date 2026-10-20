"""分页参数解析助手（契约：page 从 1 起；page_size 默认 20、上限 100）。"""

from collections.abc import Mapping
from dataclasses import dataclass

from flask import request

from src.common.errors import ApiError, ErrorCode

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class Pagination:
    """归一化后的分页参数。"""

    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def parse_pagination(args: Mapping[str, str] | None = None) -> Pagination:
    """解析分页查询参数；非法取值抛 9001（``data.fields`` 携带字段级错误）。

    传入 ``args`` 时直接解析该映射（便于作为纯函数测试）；缺省读当前
    请求的 ``request.args``。
    """
    source: Mapping[str, str] = request.args if args is None else args
    page = _parse_int_field(source, "page", default=DEFAULT_PAGE, minimum=1, label="页码")
    page_size = _parse_int_field(
        source,
        "page_size",
        default=DEFAULT_PAGE_SIZE,
        minimum=1,
        maximum=MAX_PAGE_SIZE,
        label="每页条数",
    )
    return Pagination(page=page, page_size=page_size)


def _parse_int_field(
    source: Mapping[str, str],
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int | None = None,
    label: str,
) -> int:
    raw = source.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise _field_error(name, f"{label}必须为整数") from None
    if value < minimum:
        raise _field_error(name, f"{label}不得小于 {minimum}")
    if maximum is not None and value > maximum:
        raise _field_error(name, f"{label}不得大于 {maximum}")
    return value


def _field_error(field: str, reason: str) -> ApiError:
    return ApiError(ErrorCode.VALIDATION_ERROR, data={"fields": {field: reason}})
