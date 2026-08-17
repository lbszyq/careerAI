"""统一错误码与异常（对照 docs/architecture.md）。"""


class ApiError(Exception):
    """业务异常：携带业务码 + HTTP 状态码，由全局异常处理器转成统一信封。"""

    def __init__(self, code: int, message: str, http_status: int = 400):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class ErrorCode:
    """全局错误码（architecture.md）。"""

    SUCCESS = 0
    UNAUTHORIZED = 1001
    FORBIDDEN = 1002
    TOKEN_EXPIRED = 1003
    INVALID_PARAM = 2001
    MISSING_REQUIRED = 2002
    INTERNAL_ERROR = 6001


class AuthErrorCode:
    """认证模块业务错误码（1001-1999 认证段 / 3001-3999 业务段 / 4001-4999 资源段）。"""

    USERNAME_TAKEN = 3001
    PHONE_TAKEN = 3002
    USER_NOT_FOUND = 4001
    RESOURCE_NOT_FOUND = 4001


class TaskErrorCode:
    """异步任务业务错误码。"""

    TASK_TYPE_UNSUPPORTED = 3001
    TASK_NOT_FOUND = 4001
    # 1002 撞号处置（+ 仲裁方案 a）：显式别名复用全局 FORBIDDEN，
    # 同码不同名；前端 errorMapping.ts 按数值 1002 映射（P0 硬约束，禁止拆号）。
    TASK_NOT_OWNED = ErrorCode.FORBIDDEN