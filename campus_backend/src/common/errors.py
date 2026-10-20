"""业务错误码表与业务异常。

错误码分段与 docs/api/openapi.yaml「业务错误码」表保持一致：10xx 认证与
权限、90xx 系统通用（本批次已定义）；20xx–60xx 各业务域段位已预留，
具体码随所属批次契约更新补全（先契约、后代码，不得私创新码）。
"""

from enum import Enum


class ErrorCode(Enum):
    """每个成员为 (业务码, HTTP 状态码, 默认中文提示) 三元组。"""

    # ---- 10xx 认证与权限 ----
    TOKEN_INVALID = (1001, 401, "未登录或令牌无效，请重新登录")
    TOKEN_EXPIRED = (1002, 401, "登录已过期，请重新登录")
    TOKEN_REVOKED = (1003, 401, "登录已注销，请重新登录")
    CAMPUS_VERIFICATION_REQUIRED = (1004, 403, "请先完成校园认证")
    ADMIN_REQUIRED = (1005, 403, "需要管理员权限")
    LOGIN_RATE_LIMITED = (1006, 429, "登录失败次数过多，请 10 分钟后重试")

    # ---- 90xx 系统通用 ----
    VALIDATION_ERROR = (9001, 422, "参数校验失败")
    NOT_FOUND = (9002, 404, "资源不存在")
    CONFLICT = (9003, 409, "当前状态不允许该操作")
    DEPENDENCY_UNAVAILABLE = (9004, 503, "依赖服务不可用，请稍后重试")
    INTERNAL_ERROR = (9005, 500, "服务开小差了，请稍后重试")
    RATE_LIMITED = (9006, 429, "请求过于频繁，请稍后重试")

    # ---- 20xx 用户域 / 30xx 商品域 / 40xx 交易域 / 50xx 聊天域 / 60xx 管理域 ----
    # 段位已预留，具体错误码随批次 1–5 契约更新在此追加。

    @property
    def code(self) -> int:
        return self.value[0]

    @property
    def http_status(self) -> int:
        return self.value[1]

    @property
    def message(self) -> str:
        return self.value[2]


class ApiError(Exception):
    """业务异常：由 routes / services 抛出，app.py 全局错误处理器转 envelope。

    ``data`` 用于携带补充信息（如契约 9001 的字段级错误 ``data.fields``）；
    ``http_status`` / ``message`` 缺省取错误码表默认值。
    """

    def __init__(
        self,
        error: ErrorCode,
        message: str | None = None,
        *,
        data: object = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message or error.message)
        self.error = error
        self.message = message or error.message
        self.data = data
        self.http_status = http_status or error.http_status


# Flask HTTPException 状态码 → (业务码, 覆盖文案) 的兜底映射，
# 用于把框架抛出的 HTTP 错误也转成契约 envelope。
_HTTP_STATUS_MAP: dict[int, tuple[ErrorCode, str]] = {
    400: (ErrorCode.VALIDATION_ERROR, "请求参数错误"),
    401: (ErrorCode.TOKEN_INVALID, "请先登录"),
    403: (ErrorCode.CAMPUS_VERIFICATION_REQUIRED, "无权访问该资源"),
    404: (ErrorCode.NOT_FOUND, "资源不存在"),
    405: (ErrorCode.NOT_FOUND, "请求方法不支持"),
    429: (ErrorCode.RATE_LIMITED, "请求过于频繁，请稍后重试"),
    500: (ErrorCode.INTERNAL_ERROR, "服务开小差了，请稍后重试"),
    503: (ErrorCode.DEPENDENCY_UNAVAILABLE, "依赖服务不可用，请稍后重试"),
}


def map_http_status(status_code: int) -> tuple[ErrorCode, str]:
    """把 HTTP 状态码映射为契约内业务码（5xx 未列举→9005，其余未列举→9001）。"""
    mapped = _HTTP_STATUS_MAP.get(status_code)
    if mapped is not None:
        return mapped
    if status_code >= 500:
        return (ErrorCode.INTERNAL_ERROR, "服务开小差了，请稍后重试")
    return (ErrorCode.VALIDATION_ERROR, "请求参数错误")
