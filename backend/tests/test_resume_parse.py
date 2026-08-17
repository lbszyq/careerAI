"""/ 技能画像提取增强：规则兜底路径（parse_resume_text）测试。

覆盖（验证标准 1/2/3）：
- 词表补 AI/工程化方向词（langgraph/rag/llm api/pgvector/celery 等）命中
- tech 蕴含反推（最小集合 + 扩展：LangGraph→LLM API/LangChain、
  Vue/React→JavaScript/TypeScript、RAG→向量数据库、框架/工具→语言 9 组全清单）
- 别名归一（js→javascript、ts→typescript）
- grounding 过滤（skills 元素找不到原文/蕴含依据则剔除，防 LLM 幻觉；否定断言：
  幻觉 tech / 原文未出现的蕴含键均不得传递）
- 反幻觉准入（：数据分析/tensorflow/pytorch 不在映射键）
- 边界：空简历 / 仅姓名简历 / 空 skills / 空 projects 不报错
- 结构防御：skills/tech 含 None/非字符串不抛异常
"""
import os
from pathlib import Path

import pytest

from app.ai.agents.router import (
    _tech_to_list,
    normalize_vision_output,
    normalize_vision_projects,
    parse_vision_response,
    profile_from_vision,
)
from app.ai.fallback.resume_parser import (
    _KNOWN_SKILL_KEYWORDS,
    IMPLICATION_MAP,
    SKILL_ALIASES,
    parse_resume_text,
    postprocess_skills,
    postprocess_skills_with_sources,
)
from app.ai.llm.client import _parse_json
from app.ai.llm.exceptions import LLMFormatError
from app.tasks.executors.ai_base import classify_resume_file

# 视觉夹具目录（脱敏合成简历图片，Round 1 生成并入库）
VISION_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "resume_vision"

# 测试夹具：真实简历文本（含 LangGraph/RAG/Vue/React/TypeScript/Docker/Celery/pgvector 等项目技术栈）。
# 取自 2026-08-14 端到端实测用户简历形态，随代码入库。
REAL_RESUME_TEXT = """姓名：张三
学校：清华大学
专业：计算机科学与技术
学历：本科
毕业年份：2025
GPA：3.8

技能：Python、Java、SQL、Git

项目经历
1. RAG 智能问答系统（LangGraph、pgvector、Docker、Celery）
   基于 LangGraph 构建 RAG 问答链路，pgvector 向量检索，Celery 异步任务。
2. 全栈 Web 应用（Vue、React、TypeScript）
   前端 Vue/React 组件化开发，TypeScript 类型约束。

证书：CET-6
"""


# ---------- 标准 1：IMPLICATION_MAP 最小集合 + fallback 蕴含反推 ----------

def test_implication_map_minimal_set():
    """蕴含映射确定性最小集合（结构=带等级二元组）：LangGraph→LLM API/LangChain、
    Vue/React→JavaScript/TypeScript、RAG→向量数据库。"""
    assert IMPLICATION_MAP["langgraph"] == (("llm api", "部分具备"), ("langchain", "部分具备"))
    assert "javascript" in {s for s, _ in IMPLICATION_MAP["vue"]}
    assert "typescript" in {s for s, _ in IMPLICATION_MAP["vue"]}
    assert "javascript" in {s for s, _ in IMPLICATION_MAP["react"]}
    assert IMPLICATION_MAP["rag"] == (("向量数据库", "部分具备"),)


def test_skill_aliases_mapping():
    """别名归一到标准名（与 _KNOWN_SKILL_KEYWORDS 命名一致）。"""
    assert SKILL_ALIASES["js"] == "javascript"
    assert SKILL_ALIASES["ts"] == "typescript"
    assert "javascript" in _KNOWN_SKILL_KEYWORDS
    assert "typescript" in _KNOWN_SKILL_KEYWORDS


def test_known_skills_extended_ai_keywords():
    """词表补 AI/工程化方向词：真实简历命中 langgraph/rag/pgvector/celery/llm api。"""
    for kw in ("langgraph", "rag", "llm api", "pgvector", "celery", "openai api"):
        assert kw in _KNOWN_SKILL_KEYWORDS, f"词表应包含 {kw}"


def test_parse_resume_text_extracts_ai_stack_skills():
    """fallback 路径：真实简历（LangGraph/RAG/pgvector/Celery/Vue/React/TypeScript）技能提取完整。"""
    profile = parse_resume_text(REAL_RESUME_TEXT)
    skills = [s.lower() for s in profile["skills"]]
    # 显式技能词
    assert "python" in skills
    assert "sql" in skills
    # AI/工程化词表命中
    assert "langgraph" in skills
    assert "rag" in skills
    assert "pgvector" in skills
    assert "celery" in skills
    # tech 蕴含反推
    assert "llm api" in skills
    assert "javascript" in skills
    assert "typescript" in skills


def test_parse_resume_text_vue_implies_javascript():
    """标准 1：fallback 路径 tech 蕴含反推——项目 tech 含 vue 时 skills 补入 javascript。"""
    text = """姓名：李四
专业：软件工程
学历：本科
毕业年份：2024
技能：Git
项目经历
1. 商城前端（Vue）
   使用 Vue 开发前端页面。
"""
    profile = parse_resume_text(text)
    skills = [s.lower() for s in profile["skills"]]
    assert "javascript" in skills
    assert "typescript" in skills


# ---------- 标准 1a：框架/工具→语言 蕴含扩展（全清单，去「等」） ----------

def test_implication_map_framework_to_language_full_level():
    """标准 1a：IMPLICATION_MAP 含全部 9 组高频框架/工具→语言键，且蕴含等级=已具备（硬前置依赖）。"""
    required = {
        "fastapi": "python",
        "django": "python",
        "flask": "python",
        "pytest": "python",
        "spring": "java",
        "springboot": "java",
        "express": "javascript",
        "numpy": "python",
        "pandas": "python",
    }
    for key, lang in required.items():
        assert key in IMPLICATION_MAP, f"映射应包含 {key}"
        levels = {s: lv for s, lv in IMPLICATION_MAP[key]}
        assert lang in levels, f"{key} 应蕴含 {lang}"
        assert levels[lang] == "已具备", f"{key}→{lang} 为框架/语言硬依赖，蕴含等级应为已具备"


def test_postprocess_skills_fastapi_implies_python():
    """标准 1a：postprocess_skills 输入 projects.tech 含 FastAPI 且原文含 FastAPI → skills 补入 Python。"""
    raw = "使用 FastAPI 开发后端服务"
    projects = [{"name": "后端服务", "description": None, "tech": ["FastAPI"]}]
    out = [s.lower() for s in postprocess_skills([], raw, projects)]
    assert "python" in out, f"会 FastAPI 应补入 Python，实际 {out}"


def test_postprocess_skills_pytest_implies_python():
    """标准 1a 扩展：projects.tech 含 pytest 且原文含 pytest → skills 补入 Python。"""
    raw = "使用 pytest 编写单元测试"
    projects = [{"name": "测试", "description": None, "tech": ["pytest"]}]
    out = [s.lower() for s in postprocess_skills([], raw, projects)]
    assert "python" in out


def test_postprocess_skills_spring_implies_java():
    """标准 1a 扩展：projects.tech 含 Spring 且原文含 Spring → skills 补入 Java。"""
    raw = "基于 Spring 构建微服务"
    projects = [{"name": "微服务", "description": None, "tech": ["Spring"]}]
    out = [s.lower() for s in postprocess_skills([], raw, projects)]
    assert "java" in out


def test_postprocess_skills_langgraph_implies_langchain():
    """标准 1：框架→框架蕴含——原文含 LangGraph 时 skills 补入 langchain。"""
    raw = "基于 LangGraph 构建 RAG 问答链路"
    projects = [{"name": "问答系统", "description": None, "tech": ["LangGraph"]}]
    out = [s.lower() for s in postprocess_skills([], raw, projects)]
    assert "langchain" in out, f"会 LangGraph 应补入 langchain，实际 {out}"


# ---------- 标准 3：别名归一（fallback 路径） ----------

def test_parse_resume_text_alias_normalization_fallback():
    """标准 3：fallback 路径简历含 JS/TS 归一到 javascript/typescript。"""
    text = """姓名：王五
专业：计算机
学历：本科
毕业年份：2025
技能：JS、TS、Python
"""
    profile = parse_resume_text(text)
    skills = [s.lower() for s in profile["skills"]]
    assert "javascript" in skills
    assert "typescript" in skills
    # 别名 js/ts 不应以原样出现
    assert "js" not in skills
    assert "ts" not in skills


def test_postprocess_skills_alias_normalization():
    """标准 3：postprocess_skills 直接调用时 JS/TS 归一。"""
    out = postprocess_skills(["JS", "TS"], "简历含 JS 与 TS", [])
    assert out == ["javascript", "typescript"]


# ---------- 标准 2：grounding 过滤（防 LLM 幻觉） ----------

def test_postprocess_skills_grounding_filters_hallucination():
    """标准 2：grounding 过滤——skills 找不到原文/蕴含依据则剔除。"""
    raw = "熟悉 Python 与 SQL，使用 LangGraph 做项目"
    out = postprocess_skills(["Python", "SQL", "Cobol", "LLM API"], raw, [])
    # Python/SQL 原文依据；LLM API 由原文 LangGraph 蕴含；Cobol 原文无 → 剔除
    assert "Cobol" not in out
    assert "Python" in out
    assert "SQL" in out
    assert "LLM API" in out


def test_parse_resume_text_grounding_filters_hallucination():
    """标准 2：fallback 路径 grounding——原文无的技能不会被词表误加（子串误匹配防护）。"""
    # "storage" 含 "rag" 子串，但 rag 不是独立词 → 不应命中
    text = """姓名：赵六
专业：计算机
学历：本科
毕业年份：2025
项目经历
1. 存储系统（C++）
   基于 C++ 的 storage 系统设计。
"""
    profile = parse_resume_text(text)
    skills = [s.lower() for s in profile["skills"]]
    assert "rag" not in skills


# ---------- 标准 2b：grounding 否定（防幻觉 tech 传递） ----------

def test_postprocess_skills_grounding_negation_tech_hallucination():
    """标准 2b：tech 数组含 FastAPI 但原文不含（LLM 幻觉 tech）→ Python 不得被补入（防幻觉传递）。"""
    raw = "熟悉 Git 与 Docker" # 原文无 FastAPI
    projects = [{"name": "后端", "description": None, "tech": ["FastAPI"]}]
    out = [s.lower() for s in postprocess_skills([], raw, projects)]
    assert "python" not in out, f"幻觉 tech 不得传递蕴含，实际 {out}"
    assert "fastapi" not in out


def test_postprocess_skills_implied_skill_grounding_negative():
    """标准 2b：新增蕴含键原文未出现 → 蕴含技能不得保留（LangGraph 未出现时 langchain 不得补入）。"""
    raw = "熟悉 Python 与 Docker" # 原文无 LangGraph
    projects = [{"name": "系统", "description": None, "tech": ["LangGraph"]}]
    out = [s.lower() for s in postprocess_skills([], raw, projects)]
    assert "langchain" not in out


# ---------- 标准 2c：反幻觉准入准则 ----------

def test_implication_map_no_probabilistic_keys():
    """标准 2c：反幻觉准入——「数据分析」「tensorflow」不得入映射键（概率性/多语言前端）。"""
    assert "数据分析" not in IMPLICATION_MAP, "数据分析可能用 R/Excel，禁止概率性蕴含"
    assert "tensorflow" not in IMPLICATION_MAP, "tensorflow 有 TF.js/Kotlin/C++ 官方前端，禁止加入"
    assert "pytorch" not in IMPLICATION_MAP, "PyTorch 有多语言官方前端（libtorch 等），保持最保守不加入"


# ---------- 标准 2a/：结构防御 + 边界 ----------

def test_postprocess_skills_malformed_inputs_no_crash():
    """标准 2a：skills 含 None/非字符串、projects.tech 含 None/非字符串时不抛异常。"""
    raw = "熟悉 Python 与 SQL"
    projects = [
        {"name": "后端", "description": None, "tech": ["FastAPI", None, 123, "", " "]},
    ]
    out = [s.lower() for s in postprocess_skills(["Python", None, 123, "SQL"], raw, projects)]
    assert "python" in out
    assert "sql" in out
    assert "fastapi" not in out # 原文无 FastAPI → grounding 剔除


def test_postprocess_skills_empty_inputs_no_crash():
    """标准 2c/：空 skills/空 projects 不崩溃。"""
    assert postprocess_skills([], "", []) == []
    assert postprocess_skills(None, None, None) == []


# ---------- 标准 3：边界 ----------

def test_empty_resume_returns_empty_skills():
    """：空简历输出空 skills，不报错。"""
    profile = parse_resume_text("")
    assert profile["skills"] == []
    assert profile["name"] is None


def test_name_only_resume_returns_empty_skills():
    """：仅姓名简历输出空 skills，不报错。"""
    profile = parse_resume_text("姓名：张三")
    assert profile["skills"] == []
    assert profile["name"] == "张三"


# ---------- 标准 1：provenance 标记（literal / inferred，索引对齐） ----------

def test_postprocess_skills_with_sources_literal_vs_inferred():
    """标准 1：原文显式技能=literal，蕴含反推技能=inferred，索引对齐。"""
    raw = "熟悉 Python，基于 LangGraph 构建 RAG 问答链路"
    projects = [{"name": "问答系统", "description": None, "tech": ["LangGraph"]}]
    skills, sources = postprocess_skills_with_sources(["Python", "LangGraph"], raw, projects)
    by_skill = {s.lower(): src for s, src in zip(skills, sources, strict=True)}
    assert len(skills) == len(sources), "skills 与 sources 必须索引对齐"
    assert by_skill["python"] == "literal"
    assert by_skill["langgraph"] == "literal"
    assert by_skill["llm api"] == "inferred", "LLM API 由 LangGraph 蕴含（不在原文）应为 inferred"
    assert by_skill["langchain"] == "inferred"
    # rag 不在输入 skills/tech 数组（postprocess 不扫描原文关键词，那是 parse_resume_text 的职责）
    assert "rag" not in by_skill
    assert set(sources) <= {"literal", "inferred"}, "provenance 枚举仅 literal/inferred"


def test_postprocess_skills_with_sources_dual_source_literal_priority():
    """标准 1：双重来源时 literal 优先——原文同含 fastapi+python → python 标 literal。"""
    raw = "使用 FastAPI 与 Python 开发后端服务"
    projects = [{"name": "后端服务", "description": None, "tech": ["FastAPI"]}]
    skills, sources = postprocess_skills_with_sources([], raw, projects)
    by_skill = {s.lower(): src for s, src in zip(skills, sources, strict=True)}
    assert by_skill["python"] == "literal", "原文显式出现 python（双重来源）→ literal 优先"
    assert by_skill["fastapi"] == "literal"


def test_postprocess_skills_with_sources_inferred_only_when_not_in_text():
    """标准 1：仅蕴含依据（原文无该技能）→ inferred。"""
    raw = "基于 Vue 开发前端" # 原文无 javascript/typescript
    projects = [{"name": "前端", "description": None, "tech": ["Vue"]}]
    skills, sources = postprocess_skills_with_sources([], raw, projects)
    by_skill = {s.lower(): src for s, src in zip(skills, sources, strict=True)}
    assert by_skill["javascript"] == "inferred", "Vue→JavaScript 蕴含，原文未出现 → inferred"
    assert by_skill["typescript"] == "inferred"


def test_postprocess_skills_with_sources_grounding_still_filters():
    """标准 1：grounding 过滤仍只对 literal 依据生效——无依据技能剔除且不输出 source。"""
    raw = "熟悉 Python 与 SQL"
    skills, sources = postprocess_skills_with_sources(["Python", "Cobol"], raw, [])
    assert skills == ["Python"]
    assert sources == ["literal"]


def test_postprocess_skills_with_sources_empty_inputs():
    """标准 1/：空输入返回空并行数组，不崩溃。"""
    assert postprocess_skills_with_sources([], "", []) == ([], [])
    assert postprocess_skills_with_sources(None, None, None) == ([], [])


def test_parse_resume_text_outputs_skills_sources():
    """标准 1：parse_resume_text（规则兜底路径）输出 skills_sources 且与 skills 索引对齐。"""
    profile = parse_resume_text(REAL_RESUME_TEXT)
    skills = profile["skills"]
    sources = profile["skills_sources"]
    assert len(sources) == len(skills)
    by_skill = {s.lower(): src for s, src in zip(skills, sources, strict=True)}
    # 原文显式技能词（技能行/正文）→ literal
    assert by_skill["python"] == "literal"
    assert by_skill["langgraph"] == "literal"
    assert by_skill["vue"] == "literal"
    # 原文显式出现 TypeScript（项目 tech 括号 + 描述行）→ literal（双重来源 literal 优先）
    assert by_skill["typescript"] == "literal"
    # 蕴含反推（原文未出现）→ inferred
    assert by_skill["llm api"] == "inferred"
    assert by_skill["javascript"] == "inferred"
    # 兼容：postprocess_skills 仍返回纯 skills 列表（既有用例不迁移）
    assert postprocess_skills(profile["skills"], REAL_RESUME_TEXT, profile["projects"]) == skills


# ============ ：简历解析多模态分流（图片/扫描件 → GLM-4.6V 视觉） ============


def test_classify_resume_file_image_suffixes():
    """标准 2：图片后缀（png/jpg/jpeg，含大写）→ vision。"""
    for suffix in (".png", ".jpg", ".jpeg", ".PNG", ".Jpg"):
        assert classify_resume_file(suffix, "") == "vision"


def test_classify_resume_file_scan_pdf_short_text():
    """标准 2：.pdf 且 get_text() 字符数 < 50（扫描件无文本层）→ vision。"""
    assert classify_resume_file(".pdf", "") == "vision"
    assert classify_resume_file(".pdf", " ") == "vision"
    assert classify_resume_file(".pdf", "张三") == "vision"
    assert classify_resume_file(".pdf", "a" * 49) == "vision"


def test_classify_resume_file_text_pdf_long_text():
    """标准 2：.pdf 且文本 ≥ 50 字符（文本型）→ text（行为零改动）。"""
    assert classify_resume_file(".pdf", "a" * 50) == "text"
    assert classify_resume_file(".pdf", "姓名：张三\n学校：某大学\n" + "x" * 100) == "text"


def test_classify_resume_file_unknown_or_empty_suffix():
    """标准 2/：未知后缀/空后缀 → text（原链路兜底，不误判视觉）。"""
    assert classify_resume_file(".docx", "") == "text"
    assert classify_resume_file(".txt", "简历文本") == "text"
    assert classify_resume_file("", "简历文本") == "text"
    assert classify_resume_file(None, "简历文本") == "text"


def test_tech_to_list_normalization():
    """标准 3：tech 字符串（带括号/分隔符）→ 数组；数组保序去噪；非法 → []。"""
    assert _tech_to_list("(LangGraph、pgvector、Celery)") == ["LangGraph", "pgvector", "Celery"]
    assert _tech_to_list("Vue、ECharts") == ["Vue", "ECharts"]
    assert _tech_to_list("React") == ["React"]
    assert _tech_to_list(["Vue", "React"]) == ["Vue", "React"]
    assert _tech_to_list(["Vue", None, 123, ""]) == ["Vue"]
    assert _tech_to_list(None) == []
    assert _tech_to_list("") == []


def test_normalize_vision_projects_field_drift():
    """标准 3/归一化：字段名漂移 title/tools → name/tech；tech 字符串 → 数组（确定性）。"""
    items = [
        {"title": "用户画像分析", "tools": "(pandas、NumPy)"},
        {"name": "电商全栈", "tech": ["Vue", "TypeScript"]},
        "数据可视化平台",
        {"name": "无效项", "tech": None},
    ]
    out = normalize_vision_projects(items)
    assert out[0] == {"name": "用户画像分析", "description": None, "tech": ["pandas", "NumPy"]}
    assert out[1]["tech"] == ["Vue", "TypeScript"]
    assert out[2] == {"name": "数据可视化平台", "description": None, "tech": []}
    assert out[3] == {"name": "无效项", "description": None, "tech": []}


def test_normalize_vision_output_types():
    """标准 3/归一化：gpa 字符串→float、graduation_year 字符串→int、缺失→None/[]（不编造）。"""
    raw = {
        "name": "张三", "school": "某大学", "major": "计算机", "education": "本科",
        "gpa": "3.7", "graduation_year": "2025",
        "skills": ["Python", None, 123, ""],
        "internships": [{"company": "某公司", "role": "实习生"}],
        "projects": [{"name": "项目", "tech": "Vue"}],
        "certificates": "CET-6",
    }
    out = normalize_vision_output(raw)
    assert out["gpa"] == 3.7
    assert out["graduation_year"] == 2025
    assert out["skills"] == ["Python"]
    assert out["certificates"] == ["CET-6"]
    assert out["projects"] == [{"name": "项目", "description": None, "tech": ["Vue"]}]
    out2 = normalize_vision_output({})
    assert out2["name"] is None and out2["skills"] == [] and out2["projects"] == []


# 视觉结构化样例（对齐 Round 1 MCP 实测 resume1 输出；ocr_text 是 grounding 依据）
_VISION_RESUME1 = {
    "ocr_text": """姓名：张明远
求职意向：后端开发工程师
学校：华岚理工大学
专业：计算机科学与技术
学历：本科
毕业年份：2025
GPA：3.7
技能
Python、Java、SQL、Git、Docker
实习经历
1. 星辰科技有限公司 后端开发实习生 2024.06-2024.09
参与订单系统开发，使用 FastAPI 编写 REST 接口。
项目经历
1. RAG 智能问答系统（LangGraph、pgvector、Celery）
基于 LangGraph 构建 RAG 问答链路。
2. 电商全栈应用（Vue、TypeScript）""",
    "name": "张明远", "school": "华岚理工大学", "major": "计算机科学与技术",
    "education": "本科", "graduation_year": "2025", "gpa": "3.7",
    "skills": ["Python", "Java", "SQL", "Git", "Docker"],
    "internships": [{"company": "星辰科技有限公司", "role": "后端开发实习生"}],
    "projects": [
        {"name": "RAG 智能问答系统", "tech": "(LangGraph、pgvector、Celery)"},
        {"name": "电商全栈应用", "tech": "(Vue、TypeScript)"},
    ],
    "certificates": ["CET-6", "软考中级"],
}


def test_profile_from_vision_skill_recall_and_grounding():
    """标准 3/5：视觉技能召回——显式技能 + 项目 tech + 蕴含反推 + 关键词扫描，全部 grounded。"""
    profile = profile_from_vision(_VISION_RESUME1, _VISION_RESUME1["ocr_text"])
    skills = [s.lower() for s in profile["skills"]]
    for s in ("python", "java", "sql", "git", "docker"):
        assert s in skills, f"显式技能 {s} 应在"
    for s in ("langgraph", "pgvector", "celery", "vue", "typescript"):
        assert s in skills, f"项目 tech {s} 应在"
    assert "rag" in skills, "关键词扫描应补入 rag（项目名出现但不在技能行/tech 数组）"
    assert "llm api" in skills and "langchain" in skills, "langgraph 蕴含应反推"
    assert "javascript" in skills, "vue 蕴含应反推 javascript"
    assert len(profile["skills_sources"]) == len(profile["skills"])
    assert profile["generated_by"] == "glm_vision"
    assert profile["name"] == "张明远"
    assert profile["projects"][0]["tech"] == ["LangGraph", "pgvector", "Celery"]


def test_profile_from_vision_grounding_removes_hallucinated_skill():
    """标准 5：视觉结果中技能不在 OCR 原文且无蕴含依据 → 剔除（反幻觉不因多模态放宽）。"""
    raw = {
        "ocr_text": """姓名：张三
技能
Python、SQL""",
        "name": "张三", "skills": ["Python", "SQL", "Cobol"], "projects": [],
    }
    profile = profile_from_vision(raw, raw["ocr_text"])
    skills = [s.lower() for s in profile["skills"]]
    assert "python" in skills and "sql" in skills
    assert "cobol" not in skills, "Cobol 不在 OCR 原文 → 应被 grounding 剔除"


def test_profile_from_vision_empty_ocr_text_kills_skills():
    """标准 5：OCR 原文空 → 技能全被 grounding 剔除（证明 raw_text 是依据；executor 已拦空 ocr_text）。"""
    raw = {"ocr_text": "", "name": "张三", "skills": ["Python", "SQL"], "projects": []}
    profile = profile_from_vision(raw, "")
    assert profile["skills"] == []


def test_parse_vision_response_valid():
    """标准 4：合法 JSON 含 ocr_text → (ocr_text, data)。"""
    import json

    data = {"ocr_text": """姓名：张三
技能
Python""", "name": "张三", "skills": ["Python"]}
    ocr, parsed = parse_vision_response(json.dumps(data, ensure_ascii=False))
    assert ocr == "姓名：张三\n技能\nPython"
    assert parsed["name"] == "张三"


def test_parse_vision_response_invalid_structure_raises():
    """标准 4：非 JSON / 无 ocr_text / ocr_text 空 → LLMFormatError（executor mark_failed）。"""
    import json

    import pytest

    with pytest.raises(LLMFormatError):
        parse_vision_response("这不是 JSON")
    with pytest.raises(LLMFormatError):
        parse_vision_response(json.dumps({"name": "张三"})) # 无 ocr_text
    with pytest.raises(LLMFormatError):
        parse_vision_response(json.dumps({"ocr_text": "", "name": "张三"}))


async def test_extract_vision_returns_ocr_and_structured():
    """标准 6 视觉接入：_extract_vision（mock 视觉 client）→ OCR 原文 + 结构化 dict。"""
    import json

    from app.tasks.executors.resume_parse_executor import _extract_vision

    class _FakeVision:
        is_available = True

        def __init__(self, text):
            self._text = text

        async def complete_vision(self, system_prompt, user_prompt, images, *, node_name="vision"):
            assert images, "应传入图片 data URI"
            assert images[0].startswith("data:image/"), "应为 base64 data URI"
            return self._text

    payload = {"ocr_text": "姓名：张三\n技能\nPython", "name": "张三", "skills": ["Python"]}
    fixture = VISION_FIXTURE_DIR / "resume1_backend_clean.png"
    ocr, data = await _extract_vision(
        str(fixture), ".png", vision=_FakeVision(json.dumps(payload, ensure_ascii=False))
    )
    assert ocr == "姓名：张三\n技能\nPython"
    assert data["name"] == "张三"


async def test_extract_vision_unavailable_raises():
    """标准 4：GLM 未配置（is_available=False）→ 抛异常 → executor mark_failed。"""
    import pytest

    from app.ai.llm.exceptions import LLMUnavailableError
    from app.tasks.executors.resume_parse_executor import _extract_vision

    class _NoKeyVision:
        is_available = False

    with pytest.raises(LLMUnavailableError):
        await _extract_vision("x.png", ".png", vision=_NoKeyVision())


@pytest.mark.skipif(
    not os.environ.get("GLM_API_KEY"),
    reason="GLM_API_KEY 未配置，跳过真实 HTTP API 复测（标准 1 最终证据需 Key）",
)
async def test_vision_http_api_real_alignment():
    """标准 1/3 最终证据：真实 HTTP API（complete_vision）对 3 份脱敏简历复测，技能召回 ≥ 90%。

    运行：cd backend && $env:GLM_API_KEY="<智谱Key>" && python -m pytest tests/test_resume_parse.py -k real_alignment
    """
    import json

    from app.tasks.executors.resume_parse_executor import _extract_vision

    gt = json.loads((VISION_FIXTURE_DIR / "ground_truth.json").read_text(encoding="utf-8"))
    for key in ("resume1_backend_clean", "resume2_data_scan", "resume3_frontend_complex"):
        fixture = VISION_FIXTURE_DIR / f"{key}.png"
        ocr_text, structured = await _extract_vision(str(fixture), ".png")
        profile = profile_from_vision(structured, ocr_text)
        got = {s.lower() for s in profile["skills"]}
        want = {s.lower() for s in gt[key]["skills"]}
        hit = len(want & got)
        recall = hit / len(want) if want else 1.0
        print(f"[real_alignment] {key}: 技能召回 {recall:.0%}（命中 {hit}/{len(want)}）")
        assert recall >= 0.9, f"{key} 技能召回 {recall:.0%} < 90%（命中 {hit}/{len(want)}）"
        assert profile["name"] == gt[key]["name"]
        # 标准 2：补字段断言——school/major/education 与 ground_truth 对齐
        assert profile["school"] == gt[key]["school"], f"{key} school 对齐失败"
        assert profile["major"] == gt[key]["major"], f"{key} major 对齐失败"
        assert profile["education"] == gt[key]["education"], f"{key} education 对齐失败"


# ============ ：视觉链路 JSON 解析对裸换行 ocr_text 的容错 ============


def test_parse_vision_response_fence_bare_newline_fixture():
    """标准 1：仓库化真实形态 fixture（markdown 围栏 + ocr_text 字符串值内裸换行，
    JSON 标准禁止）→ 解析成功、结构化字段完整；ocr_text 换行保留为 \\n（不替换/删除/拼接）。"""
    raw = (VISION_FIXTURE_DIR / "raw_fence_newline.json").read_text(encoding="utf-8")
    ocr, data = parse_vision_response(raw)

    # 结构化字段完整（对齐 ground_truth resume1_backend_clean）
    assert data["name"] == "张明远"
    assert data["school"] == "华岚理工大学"
    assert data["major"] == "计算机科学与技术"
    assert data["education"] == "本科"
    assert data["graduation_year"] == 2025
    assert data["skills"] == ["Python", "Java", "SQL", "Git", "Docker"]
    assert data["projects"][0]["name"] == "RAG 智能问答系统"
    assert data["projects"][0]["tech"] == ["LangGraph", "pgvector", "Celery"]

    # 换行保留为 \n（语义行分隔，不得替换为空格/删除/拼接）
    assert "\n" in ocr
    assert ocr.startswith("简历")
    assert "简历\n姓名：张明远" in ocr
    assert "姓名：张明远\n求职意向：后端开发工程师" in ocr
    assert "Python、Java、SQL、Git、Docker" in ocr
    assert "（合成简历样本，人物与机构均为虚构）" in ocr
    # 换行未被拼接/替换为空格：技能行与实习行之间必须是换行而非空格
    assert "Docker\n实习经历" in ocr


def test_parse_json_normal_input_zero_diff():
    """标准 4：_parse_json 正常 JSON 输入路径零改动——干净/围栏/已转义换行/前后噪声
    均按原语义解析，已合法转义的 \\n 不被二次破坏。"""
    import json

    assert _parse_json('{"a": 1, "b": "x"}') == {"a": 1, "b": "x"}
    assert _parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    # 已转义换行（合法 JSON）：json.loads 应得到真实换行符，而非字面反斜杠
    valid_escaped = json.dumps({"ocr_text": "a\nb"}, ensure_ascii=False)
    assert _parse_json(valid_escaped) == {"ocr_text": "a\nb"}
    # 前后噪声 + 平衡块提取（原兜底路径）
    assert _parse_json('前缀噪声 {"a": 1} 后缀噪声') == {"a": 1}


def test_parse_json_bare_newline_crlf_tolerance():
    """标准 6 扩展：CRLF 裸换行同样转义为 \\n（不产生双换行），Windows 序列化不破坏语义。"""
    raw = '```json\n{"ocr_text":"a\r\nb"}\n```'
    assert _parse_json(raw) == {"ocr_text": "a\nb"}


def test_parse_json_malformed_returns_none():
    """标准 7：纯噪声 / 无围栏非 JSON / 截断 JSON → _parse_json 返回 None（不误解析、不抛异常）。"""
    assert _parse_json("") is None
    assert _parse_json("这不是 JSON 纯噪声文本") is None
    assert _parse_json('{"ocr_text": "截断') is None
    assert _parse_json('{"a": ') is None
    assert _parse_json("```json\n{broken nonsense}\n```") is None


def test_parse_vision_response_malformed_raises():
    """标准 7：畸形输入仍抛 LLMFormatError（容错不放大为静默成功）。"""
    for bad in ("纯噪声无 JSON", '{"name": "张三"}', '{"ocr_text": "截断'):
        with pytest.raises(LLMFormatError):
            parse_vision_response(bad)


async def test_extract_vision_malformed_output_raises():
    """标准 3：_extract_vision 收到畸形视觉输出 → LLMFormatError（executor execute 捕获后 mark_failed）。"""
    import json

    from app.tasks.executors.resume_parse_executor import _extract_vision

    class _FakeVision:
        is_available = True

        def __init__(self, text):
            self._text = text

        async def complete_vision(self, system_prompt, user_prompt, images, *, node_name="vision"):
            return self._text

    fixture = VISION_FIXTURE_DIR / "resume1_backend_clean.png"
    # 围栏内非 JSON 结构（无 ocr_text）
    with pytest.raises(LLMFormatError):
        await _extract_vision(str(fixture), ".png", vision=_FakeVision("```json\n{broken}\n```"))
    # 截断 JSON
    with pytest.raises(LLMFormatError):
        await _extract_vision(str(fixture), ".png", vision=_FakeVision('{"ocr_text": "截断'))
    # 合法 JSON 但无 ocr_text
    with pytest.raises(LLMFormatError):
        await _extract_vision(str(fixture), ".png", vision=_FakeVision(json.dumps({"name": "张三"})))


async def test_resume_parse_vision_malformed_output_marks_failed(monkeypatch, tmp_path):
    """标准 3：executor 层——图片简历视觉输出畸形 → mark_failed（job.status=failed），
    前端引导手动补填，不静默空画像。"""
    import shutil
    import uuid
    from types import SimpleNamespace

    from app.tasks.executors import resume_parse_executor as rpe

    job = SimpleNamespace(
        id=uuid.uuid4(), user_id=uuid.uuid4(), task_type="resume_parse",
        status="running", progress=0, stage=None, result=None, result_ref=None,
        error_message=None, celery_task_id=None, trace_id=None, finished_at=None,
    )

    class _FakeSession:
        def __init__(self, job):
            self.job = job

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, model, pk):
            return self.job

        async def flush(self):
            return None

        async def commit(self):
            return None

    class _FakeVision:
        is_available = True

        async def complete_vision(self, system_prompt, user_prompt, images, *, node_name="vision"):
            return "```json\n{broken nonsense}\n```"

    png = tmp_path / "resume.png"
    shutil.copyfile(VISION_FIXTURE_DIR / "resume1_backend_clean.png", png)
    monkeypatch.setattr(rpe, "AsyncSessionLocal", lambda: _FakeSession(job))
    monkeypatch.setattr(rpe, "get_vision_client", lambda: _FakeVision())

    await rpe.ResumeParseExecutor().execute(
        str(job.id), {"user_id": str(job.user_id), "file_path": str(png)}
    )

    assert job.status == "failed"
    assert "视觉识别未成功" in job.error_message


def test_profile_from_vision_fence_newline_fixture_grounding():
    """标准 6：裸换行保留为 \\n 后，postprocess_skills_with_sources 词边界（\\b）
    grounding 不劣化——fixture 端到端（裸换行 JSON → ocr_text → 画像）技能召回完整。"""
    raw = (VISION_FIXTURE_DIR / "raw_fence_newline.json").read_text(encoding="utf-8")
    ocr, data = parse_vision_response(raw)
    profile = profile_from_vision(data, ocr)
    skills = [s.lower() for s in profile["skills"]]
    # 显式技能 + 项目 tech + 关键词扫描 + 蕴含反推，全部 grounded（换行边界未破坏词边界匹配）
    for s in ("python", "java", "sql", "git", "docker", "fastapi",
              "langgraph", "pgvector", "celery", "vue", "typescript"):
        assert s in skills, f"换行保留后 {s} 应仍被 grounding 召回"
    assert "rag" in skills, "关键词扫描应在换行文本中召回 rag"
    assert "llm api" in skills and "javascript" in skills, "蕴含反推应保留"
    assert len(profile["skills_sources"]) == len(profile["skills"])
    assert profile["generated_by"] == "glm_vision"
