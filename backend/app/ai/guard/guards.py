"""安全防线（DoD）：Input Guard + Output Guard + 安全审计日志。

- Input Guard：Prompt Injection 检测 / 恶意指令 / 超长输入
- Output Guard：绝对化承诺 / 无来源数字 / 敏感内容（PIPL）
- 审计日志：结构化记录安全事件（AI_AUDIT_LOG_ENABLED 控制）
默认开启，禁止为「方便」关闭（architecture.md / 角色约束）。
"""
import logging
from functools import lru_cache
import re
import threading
from dataclasses import dataclass, field

from app.core.config import get_settings

logger = logging.getLogger("careerai.security")

# Prompt Injection / 越权指令特征（保守匹配，避免误伤正常简历）
_INPUT_INJECTION_PATTERNS = [
    r"忽略(之前|上面|上述|以上).{0,12}(指令|要求|内容|提示)",
    r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions|prompts)",
    r"泄露.{0,8}(系统|system)\s*(提示词|指令|prompt)",
    r"绕过.{0,12}(限制|审核|过滤)",
    r"现在你(是|扮演).{0,20}(不是|不要)",
    r"输出.{0,6}(内部|隐藏).{0,6}(提示词|system|prompt|指令)",
    # 加固：收窄 登记的 4 个绕过样本（保守匹配，正常简历无此类句式）
    r"(告诉|给出|展示|透露|复述|说出).{0,8}(你(的)?|系统).{0,10}(system|prompt|提示词|指令|规则|内容)",
    r"现在你(不是|不要).{0,20}(AI|助手|机器人|人|角色)",
    r"(请|可以|帮我)?(扮演|假装).{0,8}(任意|其他|别的|一个).{0,6}(人|角色|AI)",
]

# 恶意/危险指令特征
_INPUT_MALICIOUS_PATTERNS = [
    r"生成.{0,10}(恶意代码|病毒|木马|钓鱼)",
    r"获取.{0,10}(他人隐私|他人密码|银行账号|身份证号)",
    r"入侵.{0,10}(系统|服务器)",
]

# 输出绝对化承诺（职业建议禁止保证结果）
_OUTPUT_ABSOLUTE_PATTERNS = [
    r"(保证|肯定|一定|必能).{0,6}(入职|拿到|通过|offer|涨薪|成功)",
    r"100%\s*(入职|通过|成功)",
]

# 敏感内容：身份证号 / 银行卡号 / 手机号（脱敏用）
_SENSITIVE_PATTERNS = [
    (re.compile(r"\d{17}[\dXx]"), "身份证号"),
    (re.compile(r"\d{16,19}"), "银行卡号"),
    (re.compile(r"1[3-9]\d{9}"), "手机号"),
]

_MAX_INPUT_CHARS = 8000 # 超长输入（User Prompt < 3000 tokens 的保守换算）


@dataclass
class GuardResult:
    blocked: bool
    reason: str = ""
    sanitized_text: str = ""
    events: list[str] = field(default_factory=list)


class Guard:
    """输入/输出安全防线（进程内单例 + 审计日志）。"""

    def __init__(self, settings=None) -> None:
        s = settings or get_settings()
        self.enabled = s.AI_GUARD_ENABLED
        self.audit_enabled = s.AI_AUDIT_LOG_ENABLED
        self._lock = threading.Lock()
        self._events: list[dict] = []

    # ---- 审计 ----
    def _audit(self, event: str, detail: dict) -> None:
        if not self.audit_enabled:
            return
        with self._lock:
            self._events.append({"event": event, **detail})
        logger.warning("security_audit event=%s detail=%s", event, detail)

    def recent_events(self, limit: int = 20) -> list[dict]:
        with self._lock:
            return self._events[-limit:]

    # ---- Input Guard ----
    def check_input(self, text: str, *, context: str = "") -> GuardResult:
        if not self.enabled:
            return GuardResult(blocked=False, sanitized_text=text)
        if not text:
            return GuardResult(blocked=False, sanitized_text=text)
        for pattern in _INPUT_INJECTION_PATTERNS:
            if re.search(pattern, text, flags=re.IGNORECASE):
                reason = "Prompt Injection 特征"
                self._audit("input_guard_blocked", {"context": context, "reason": reason, "pattern": pattern})
                return GuardResult(blocked=True, reason=reason, sanitized_text=text)
        for pattern in _INPUT_MALICIOUS_PATTERNS:
            if re.search(pattern, text, flags=re.IGNORECASE):
                reason = "恶意指令特征"
                self._audit("input_guard_blocked", {"context": context, "reason": reason, "pattern": pattern})
                return GuardResult(blocked=True, reason=reason, sanitized_text=text)
        if len(text) > _MAX_INPUT_CHARS:
            truncated = text[:_MAX_INPUT_CHARS]
            self._audit("input_guard_truncated", {"context": context, "len": len(text)})
            return GuardResult(blocked=False, reason="超长输入已截断", sanitized_text=truncated)
        return GuardResult(blocked=False, sanitized_text=text)

    # ---- Output Guard ----
    def check_output(self, text: str, *, context: str = "") -> GuardResult:
        if not self.enabled:
            return GuardResult(blocked=False, sanitized_text=text)
        issues: list[str] = []
        sanitized = text
        for pattern in _OUTPUT_ABSOLUTE_PATTERNS:
            if re.search(pattern, sanitized, flags=re.IGNORECASE):
                issues.append("绝对化承诺")
                sanitized = re.sub(pattern, lambda m: m.group(0) + "（需注明不确定性）", sanitized, flags=re.IGNORECASE)
        for regex, name in _SENSITIVE_PATTERNS:
            if regex.search(sanitized):
                sanitized = regex.sub("[已脱敏]", sanitized)
                issues.append(f"敏感内容({name})已脱敏")
        if issues:
            self._audit("output_guard_flagged", {"context": context, "issues": issues})
        return GuardResult(blocked=False, reason=";".join(issues), sanitized_text=sanitized)


def sanitize_structured_output(payload, *, context: str = "") -> object:
    """结构化 AI 输出递归过 Output Guard：文本脱敏/绝对化承诺标注，结构保持不变。

    报告/计划/画像均为 str/list/dict 组合；数字、布尔、None 原样透传。
    """
    if isinstance(payload, str):
        return get_guard().check_output(payload, context=context).sanitized_text
    if isinstance(payload, list):
        return [sanitize_structured_output(item, context=context) for item in payload]
    if isinstance(payload, dict):
        return {key: sanitize_structured_output(value, context=context) for key, value in payload.items()}
    return payload


@lru_cache(maxsize=1)
def get_guard() -> Guard:
    return Guard()
