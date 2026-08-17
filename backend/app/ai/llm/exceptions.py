"""AI 模块异常定义（对齐 architecture.md / 错误映射）。"""


class AIError(Exception):
    """AI 模块基础异常。"""


class LLMError(AIError):
    """LLM 调用层基础异常（调用方捕获后走兜底模板）。"""


class LLMUnavailableError(LLMError):
    """LLM 不可用：API key 未配置 / 服务不可达。调用方应走兜底模板。"""


class LLMTimeoutError(LLMError):
    """LLM 单次调用超时（>30s）。"""


class LLMRateLimitError(LLMError):
    """LLM 限流（429），重试耗尽后抛出。"""


class LLMFormatError(LLMError):
    """LLM 输出格式异常（JSON 解析失败，重试 1 次后抛出）。"""


class AIGuardBlockedError(AIError):
    """输入被安全防线拦截。"""
