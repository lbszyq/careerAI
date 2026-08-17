"""router_node（Career Router，）：简历解析/表单 → 结构化画像 + 完整性检查（C-002）。

- 输入已有结构化画像（DB 载入，stage1 报告场景）→ 直接做完整性检查。
- 输入简历原文（resume_parse 场景）→ LLM 解析优先，规则正则兜底。
- Guard：输入先过 Input Guard（Prompt Injection / 恶意指令 / 超长）。
"""
import logging
import re

from app.ai.fallback.resume_parser import (
    _KNOWN_SKILL_KEYWORDS,
    check_profile_complete,
    normalize_internships,
    normalize_projects,
    parse_resume_text,
    postprocess_skills_with_sources,
)
from app.ai.guard.guards import get_guard
from app.ai.llm.client import LLMClient, _parse_json
from app.ai.llm.exceptions import LLMError, LLMFormatError
from app.ai.prompts import render_prompt
from app.ai.schemas import GraphState
from app.ai.agents.deps import AgentDeps

logger = logging.getLogger("careerai.ai.agents.router")

_COMPLETE_REQUIRED = ("name", "education", "major", "graduation_year")


async def router_node(state: GraphState, deps: AgentDeps) -> dict:
    profile: dict | None = state.get("profile")
    raw_text: str | None = state.get("profile_raw")

    if raw_text:
        guard = get_guard()
        verdict = guard.check_input(raw_text, context="resume_parse")
        if verdict.blocked:
            logger.warning("router: 输入被 Guard 拦截: %s", verdict.reason)
            return {
                "profile": {},
                "profile_complete": False,
                "stage_errors": ["简历输入包含不安全内容，已拒绝解析"],
            }
        raw_text = verdict.sanitized_text

    if profile is None:
        profile = await _parse_resume(raw_text, deps.llm)

    complete = check_profile_complete(profile)
    return {
        "profile": profile,
        "profile_complete": complete,
        "stage_errors": state.get("stage_errors") or [],
    }


async def _parse_resume(raw_text: str | None, llm: LLMClient | None) -> dict:
    if not raw_text or not raw_text.strip():
        return _empty_profile("无简历文本输入")

    if llm is not None and llm.is_available:
        try:
            data = await llm.complete_json(
                system_prompt=render_prompt("router.md", profile_raw=raw_text[:6000]),
                user_prompt=f"简历/表单原文：\n{raw_text[:6000]}",
                node_name="router_node",
            )
            profile = {
                "name": data.get("name"),
                "school": data.get("school"),
                "major": data.get("major"),
                "education": data.get("education"),
                "gpa": data.get("gpa"),
                "graduation_year": data.get("graduation_year"),
                "skills": list(data.get("skills") or []),
                "internships": normalize_internships(data.get("internships")),
                "projects": normalize_projects(data.get("projects")),
                "certificates": list(data.get("certificates") or []),
                "completeness": data.get("completeness") or {},
            }
            if profile.get("name") or profile.get("major"):
                # /：LLM 路径入口统一后处理（tech 蕴含反推 + 别名归一 + grounding 过滤
                # + provenance 标记）；skills_sources 与 skills 索引对齐（literal/inferred）。
                profile["skills"], profile["skills_sources"] = postprocess_skills_with_sources(
                    profile["skills"], raw_text, profile["projects"]
                )
                return profile
            logger.warning("router: LLM 输出空画像，转规则兜底")
        except LLMError as exc:
            logger.warning("router: LLM 解析失败转规则兜底: %s", exc)

    profile = parse_resume_text(raw_text)
    # /：规则兜底路径入口统一后处理（parse_resume_text 内部已处理，此处幂等兜底，
    # 保证 LLM 与规则两条路径都经 _parse_resume 统一后处理出口）；skills_sources 同步幂等覆盖。
    profile["skills"], profile["skills_sources"] = postprocess_skills_with_sources(
        profile["skills"], raw_text, profile["projects"]
    )
    profile["generated_by"] = "rule_template"
    return profile


def _empty_profile(reason: str) -> dict:
    return {
        "name": None, "school": None, "major": None, "education": None,
        "gpa": None, "graduation_year": None, "skills": [], "internships": [],
        "projects": [], "certificates": [],
        "completeness": {
            "has_name": False, "has_education": False, "has_major": False,
            "has_graduation_year": False, "has_experience": False,
            "missing_fields": list(_COMPLETE_REQUIRED) + ["experience"],
        },
        "generated_by": "empty",
        "parse_note": reason,
    }


# ---------------------------------------------------------------------------
# 视觉结构化输出归一化 + 画像构建（grounding 依据接线：OCR 原文作为 raw_text）
# ---------------------------------------------------------------------------

_VISION_TECH_SPLIT_RE = re.compile(r"[、,，;；/+|]+")


def _to_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_str_list(raw) -> list[str]:
    """视觉 skills/certificates 归一：list[str] 保序去噪；单字符串 → 单元素；非法 → []。"""
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if isinstance(x, str) and str(x).strip()]
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    return []


def _tech_to_list(raw) -> list[str]:
    """视觉 projects.tech 归一：字符串（带括号/分隔符）→ 数组；数组 → 保序去噪；非法 → []。"""
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if isinstance(t, str) and str(t).strip()]
    if isinstance(raw, str):
        s = raw.strip().strip("()[]【】《》")
        return [t for t in _VISION_TECH_SPLIT_RE.split(s) if t.strip()][:5]
    return []


def normalize_vision_projects(items) -> list[dict]:
    """视觉 projects 归一（确定性）：字段名 title/tools→name/tech，tech 字符串→数组。

    字段漂移是视觉模型的常态（实测 title/tools 与 name/tech 均出现），归一为契约字段，
    归一失败置 None/[]，不编造。
    """
    out: list[dict] = []
    for item in items or []:
        if isinstance(item, str):
            out.append({"name": item, "description": None, "tech": []})
            continue
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("title") or item.get("project")
        desc = item.get("description") or item.get("desc")
        tech = _tech_to_list(item.get("tech") or item.get("tools"))
        out.append({
            "name": str(name).strip() if name else None,
            "description": str(desc).strip() if desc else None,
            "tech": tech,
        })
    return out


def normalize_vision_output(raw: dict) -> dict:
    """视觉结构化输出归一化（确定性，不编造）：字段名映射 + 类型归一。"""
    raw = raw or {}
    return {
        "name": str(raw.get("name") or "").strip() or None,
        "school": str(raw.get("school") or "").strip() or None,
        "major": str(raw.get("major") or "").strip() or None,
        "education": str(raw.get("education") or "").strip() or None,
        "gpa": _to_float(raw.get("gpa")),
        "graduation_year": _to_int(raw.get("graduation_year")),
        "skills": _to_str_list(raw.get("skills")),
        "internships": normalize_internships(raw.get("internships")),
        "projects": normalize_vision_projects(raw.get("projects")),
        "certificates": _to_str_list(raw.get("certificates")),
    }


def parse_vision_response(text: str) -> tuple[str, dict]:
    """视觉响应解析：模型文本 → (OCR 原文, 结构化 dict)。

    非法结构（非 JSON / 无 ocr_text / ocr_text 空）→ LLMFormatError（executor → mark_failed，
    前端引导手动补填，优于静默空画像）。ocr_text 是技能 grounding 的依据，缺失即视为失败。
    """
    data = _parse_json(text)
    if not isinstance(data, dict):
        raise LLMFormatError("视觉模型输出无法解析为 JSON")
    ocr_text = str(data.get("ocr_text") or "").strip()
    if not ocr_text:
        raise LLMFormatError("视觉模型未返回 OCR 原文（grounding 依据缺失）")
    return ocr_text, data


def _scan_known_skills(skills: list[str], text: str) -> list[str]:
    """OCR 原文已知技能词扫描（对齐规则兜底路径）：补入技能行/tech 数组遗漏的关键词。

    视觉模型可能只提取显式技能行 + 项目 tech，而漏掉出现在项目名/描述里的技能词（如
    「RAG 智能问答系统」的 rag、「使用 Docker 部署」的 docker）。按 _KNOWN_SKILL_KEYWORDS
    对 OCR 原文做词边界扫描补入，提升与文本链路（DeepSeek）的技能召回对齐；补入的技能仍须
    经 postprocess_skills_with_sources grounding（词边界匹配原文依据），不引入幻觉。
    """
    out = [s for s in (skills or []) if isinstance(s, str) and s.strip()]
    existing = {s.lower() for s in out}
    lowered = (text or "").lower()
    for kw in _KNOWN_SKILL_KEYWORDS:
        if kw.isascii() and "+" not in kw and "#" not in kw:
            hit = bool(re.search(rf"\b{re.escape(kw)}\b", text, re.IGNORECASE))
        else:
            hit = kw in lowered
        if hit and kw not in existing:
            out.append(kw)
            existing.add(kw)
    return out


def profile_from_vision(raw: dict, ocr_text: str) -> dict:
    """视觉结构化结果 → 画像：确定性归一化 + grounding 依据接线（OCR 原文作为 raw_text）。

    - 复用 postprocess_skills_with_sources（别名归一 + tech 蕴含反推 + grounding 过滤 + provenance）；
    - OCR 原文（raw_text）是技能 grounding 的唯一依据（词边界匹配），视觉路径不得绕过；
    - 与文本路径同源：技能须在 OCR 原文出现或由原文蕴含键反推，否则剔除（反幻觉不因多模态放宽）；
    - _scan_known_skills 补入 OCR 原文出现的已知技能词（对齐规则兜底路径），提升召回对齐。
    """
    structured = normalize_vision_output(raw)
    skills = _scan_known_skills(structured["skills"], ocr_text)
    skills, skills_sources = postprocess_skills_with_sources(
        skills, ocr_text, structured["projects"]
    )
    return {
        "name": structured["name"],
        "school": structured["school"],
        "major": structured["major"],
        "education": structured["education"],
        "gpa": structured["gpa"],
        "graduation_year": structured["graduation_year"],
        "skills": skills,
        "skills_sources": skills_sources,
        "internships": structured["internships"],
        "projects": structured["projects"],
        "certificates": structured["certificates"],
        "generated_by": "glm_vision",
    }
