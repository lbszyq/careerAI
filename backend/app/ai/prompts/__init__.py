"""Prompt 加载器（architecture.md ：独立文件 + Git 版本管理 + 变量注入）。"""
import re
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=32)
def load_prompt(name: str) -> str:
    """按文件名读取 System Prompt（如 router.md / market.md）。"""
    path = PROMPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt 文件不存在: {path}")
    return path.read_text(encoding="utf-8")

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def render_prompt(name: str, **variables: str) -> str:
    """加载 Prompt 并替换 {variable_name} 占位符。

    与 str.format 不同：只替换 {变量名} 形式的占位符，prompt 中 JSON 示例的花括号
    （如 { "directions": [...] }）不会被误解析（变量注入契约）。
    """
    prompt = load_prompt(name)

    def _sub(match: re.Match) -> str:
        key = match.group(1)
        if key not in variables:
            raise KeyError(f"Prompt 变量未提供: {key}")
        return variables[key]

    return _PLACEHOLDER_RE.sub(_sub, prompt)
