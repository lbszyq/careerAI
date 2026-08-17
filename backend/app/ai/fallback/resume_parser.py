"""简历解析规则兜底：LLM 不可用时用正则提取常见简历字段。

诚实定位：启发式提取，仅覆盖常见排版；无法提取的字段置 null 并计入 missing_fields，
引导用户手动补填（兜底）。禁止猜测补全。

输出结构与 profile-contract 对齐（QA-BUG-005 修复）：
- internships: [{"company", "role", "duration"}]（对齐前端 ApiInternship）
- projects: [{"name", "description", "tech"}]（对齐前端 ApiProject）
- certificates: list[str]
- 项目支持多行描述块（name/description/tech），证书条目自动去项目符号
"""
import re

_KNOWN_SKILL_KEYWORDS = [
    "python", "java", "c++", "c#", "go", "rust", "sql", "mysql", "postgresql",
    "redis", "mongodb", "excel", "tableau", "power bi", "spark", "hadoop",
    "hive", "linux", "docker", "k8s", "kubernetes", "git", "tensorflow",
    "pytorch", "sklearn", "机器学习", "深度学习", "数据分析", "数据挖掘",
    "langgraph", "rag", "llm api", "pgvector", "celery", "openai api", "向量数据库",
    "react", "vue", "typescript", "javascript", "html", "css", "node.js",
    "fastapi", "django", "flask", "spring", "springboot", "kafka", "flink",
    "产品设计", "axure", "figma", "项目管理", "用户研究", "市场调研",
    "新媒体运营", "内容运营", "用户运营", "活动策划", "商务谈判", "英语",
]

# /：技能蕴含映射（确定性数据结构，反幻觉底线）。
# 键=项目 tech 数组中明确出现的技术栈（小写）；值=该技术栈蕴含的 (具体技能名, 蕴含等级) 二元组序列。
# 蕴含等级（语义分级，确定性准入准则）：
# - 已具备（IMPLICATION_LEVEL_FULL）：框架/工具→语言，语言是框架/工具的前置**硬依赖**（确定性成立）。
# 准入：无同义其他语言官方前端/主实现——FastAPI/Django/Flask/pytest/NumPy/pandas 为纯 Python
# 生态，Spring/SpringBoot 主语言唯一（Java）、Express 主语言唯一（JavaScript）；
# - 部分具备（IMPLICATION_LEVEL_PARTIAL）：框架→框架/相关技术，可快速上手但非必然掌握
# （LangGraph→LangChain；Vue/React→TypeScript 为可选写法；RAG→向量数据库 非硬依赖）。
# 反幻觉底线：禁止概率性蕴含——「数据分析→Python」不成立（可能用 R/Excel）；tensorflow 有
# TF.js/Kotlin/C++ 官方前端、PyTorch 有 libtorch 等多语言前端，均不加入，保持最保守。
IMPLICATION_LEVEL_FULL = "已具备"
IMPLICATION_LEVEL_PARTIAL = "部分具备"

IMPLICATION_MAP: dict[str, tuple[tuple[str, str], ...]] = {
    # 框架/工具→语言（已具备：语言是硬前置依赖）
    "fastapi": (("python", IMPLICATION_LEVEL_FULL),),
    "django": (("python", IMPLICATION_LEVEL_FULL),),
    "flask": (("python", IMPLICATION_LEVEL_FULL),),
    "pytest": (("python", IMPLICATION_LEVEL_FULL),),
    "spring": (("java", IMPLICATION_LEVEL_FULL),),
    "springboot": (("java", IMPLICATION_LEVEL_FULL),),
    "express": (("javascript", IMPLICATION_LEVEL_FULL),),
    "numpy": (("python", IMPLICATION_LEVEL_FULL),),
    "pandas": (("python", IMPLICATION_LEVEL_FULL),),
    # 框架→框架/相关技术（部分具备：可快速上手，非必然掌握；「会 LangGraph 判 LLM API 部分具备」）
    "langgraph": (
        ("llm api", IMPLICATION_LEVEL_PARTIAL),
        ("langchain", IMPLICATION_LEVEL_PARTIAL),
    ),
    # 保留：Vue/React 主实现语言=JavaScript（已具备），TypeScript 为可选写法（部分具备）；
    # RAG 可用关键词检索实现，向量数据库非硬依赖（部分具备）
    "vue": (("javascript", IMPLICATION_LEVEL_FULL), ("typescript", IMPLICATION_LEVEL_PARTIAL)),
    "react": (("javascript", IMPLICATION_LEVEL_FULL), ("typescript", IMPLICATION_LEVEL_PARTIAL)),
    "rag": (("向量数据库", IMPLICATION_LEVEL_PARTIAL),),
}

# ── 蕴含规则审计（增量补足 注释，不重建映射）────────────────────────────────
# 每条蕴含附【依据】与【不确定性】；不确定性边界情形供下游对 inferred 技能降权/标注
# （executor 侧消费 provenance + inferred_kind；PARTIAL inferred 在差距分析中权重打折）。
# fastapi/django/flask/pytest/numpy/pandas → python（已具备）
# 依据：纯 Python 生态——框架由 Python 编写、API 即 Python，使用必然涉及 Python（硬前置）。
# 不确定性：无（确定性成立）。
# spring/springboot → java（已具备）
# 依据：Spring 生态主语言唯一为 Java（官方文档/API 均为 Java）。
# 不确定性：无（Kotlin/Scala 为衍生使用，主实现语言仍 Java）。
# express → javascript（已具备）
# 依据：Express 是 Node.js 框架，主语言唯一为 JavaScript。
# 不确定性：无。
# langgraph → llm api（部分具备）
# 依据：LangGraph 是 LLM 应用编排框架，构建应用必然接触 LLM 调用。
# 不确定性：用户可能仅用 LangGraph 封装层/可视化编排而未直接调 LLM API（用户审计
# 明确指出「用 LangGraph 的人可能不会直接调 LLM API」）——故判部分具备 + inferred 降权。
# langgraph → langchain（部分具备）
# 依据：LangGraph 与 LangChain 同生态、API 风格相近，可快速上手。
# 不确定性：可快速上手 ≠ 已掌握；LangChain 组件体系庞大，用户可能仅使用 LangGraph 独立能力。
# vue/react → javascript（已具备）
# 依据：Vue/React 主实现语言=JavaScript，组件开发必然使用 JS（模板/JSX 均为 JS 语法）。
# 不确定性：无。
# vue/react → typescript（部分具备）
# 依据：TS 为可选写法，Vue3/React 官方支持 TS 但非强制。
# 不确定性：用户可能纯 JS 开发、未使用 TS。
# rag → 向量数据库（部分具备）
# 依据：RAG 常用向量检索实现（pgvector 等）。
# 不确定性：向量数据库非 RAG 硬依赖——可用关键词检索/BM25/倒排索引实现，故部分具备。

# 技能别名归一（别名→标准名，标准名与 _KNOWN_SKILL_KEYWORDS 命名一致）。
SKILL_ALIASES: dict[str, str] = {
    "js": "javascript",
    "ts": "typescript",
}

# 其他节头（用于结束当前节）：内容行含关键词不再误判为节头（QA-BUG-004）
_SECTION_NAMES = ("教育", "自我评价", "荣誉", "获奖", "联系", "技能", "实习", "项目", "证书")
_DURATION_RE = re.compile(
    r"(?:20\d{2}|19\d{2})(?:[.\-/年]\d{1,2})?\s*[-~—至到]\s*"
    r"(?:(?:20\d{2}|19\d{2})(?:[.\-/年]\d{1,2})?|至今|现在)"
)
_PAREN_RE = re.compile(r"[（(][^()]*[）)]")
_TECH_PAREN_RE = re.compile(r"[（(]([^()]+)[）)]")


def parse_resume_text(text: str) -> dict:
    """正则启发式提取画像字段（无 LLM 兜底路径）。"""
    raw_lines = [ln for ln in text.splitlines() if ln.strip()]
    lines = [ln.strip() for ln in raw_lines]

    def find(pattern: str, flags: int = re.IGNORECASE) -> str | None:
        for ln in lines:
            m = re.search(pattern, ln, flags=flags)
            if m:
                return m.group(1).strip().rstrip("，,；;。")
        return None

    name = find(r"(?:姓名|名字)\s*[：:]\s*(\S+)")
    school = find(r"(?:学校|院校|毕业院校|就读院校)\s*[：:]\s*(\S+)")
    major = find(r"(?:专业|主修|所学专业)\s*[：:]\s*(\S+)")
    education = find(r"(本科|硕士|博士|大专|专科)")
    graduation_year = find(r"(?:毕业\s*(?:年份|时间|年度)?\s*[：:]\s*)(20\d{2})")
    if graduation_year is None:
        graduation_year = find(r"(20\d{2})\s*[年届]")
    gpa = find(r"(?:GPA|绩点)\s*[：:]\s*([0-9]+(?:\.[0-9]+)?)")

    # 技能：显式技能行 + 已知关键词扫描
    skills: list[str] = []
    skill_line = find(r"(?:技能|掌握|熟悉|熟练使用)\s*[：:]\s*(.+)")
    if skill_line:
        skills = [s.strip() for s in re.split(r"[、,，;；/]", skill_line) if s.strip()]
    lowered = text.lower()
    for kw in _KNOWN_SKILL_KEYWORDS:
        # ASCII 单词按词边界匹配（防 rag 误命中 storage/average、java 误命中 javascript）；
        # 中文词 / 含特殊字符词（c++、c#）保持子串匹配（词边界会破坏其匹配）。
        if kw.isascii() and "+" not in kw and "#" not in kw:
            hit = bool(re.search(rf"\b{re.escape(kw)}\b", text, re.IGNORECASE))
        else:
            hit = kw in lowered
        if hit and kw not in skills:
            skills.append(kw)

    # 实习/项目/证书：段落式 + 单行式提取（QA-BUG-004），多行描述并入同一条目（完整性）
    internship_groups = _extract_section(raw_lines, ("实习", "intern"))
    project_groups = _extract_section(raw_lines, ("项目", "project"))
    certificate_groups = _extract_section(raw_lines, ("证书", "证书/资质", "certificate"))
    internships = [_internship_entry(lns) for lns in internship_groups]
    projects = [_project_entry(lns) for lns in project_groups]
    certificates = [_certificate_entry(lns) for lns in certificate_groups]

    # /：技能后处理（别名归一 + tech 蕴含反推 + grounding 过滤 + provenance 标记），
    # 规则兜底路径同样覆盖；skills_sources 与 skills 索引对齐（literal/inferred）。
    skills, skills_sources = postprocess_skills_with_sources(skills, text, projects)

    completeness = {
        "has_name": bool(name),
        "has_education": bool(education),
        "has_major": bool(major),
        "has_graduation_year": bool(graduation_year),
        "has_experience": bool(internships or projects),
    }
    missing = [k.replace("has_", "") for k, v in completeness.items() if not v]
    completeness["missing_fields"] = missing

    return {
        "name": name,
        "school": school,
        "major": major,
        "education": education,
        "gpa": float(gpa) if gpa else None,
        "graduation_year": int(graduation_year) if graduation_year else None,
        "skills": skills,
        "skills_sources": skills_sources,
        "internships": internships,
        "projects": projects,
        "certificates": certificates,
        "completeness": completeness,
    }


def _is_section_header(line: str, keywords: tuple[str, ...]) -> bool:
    """节头判定（QA-BUG-004 b）：仅独立短行（如「实习经历」「项目经历」「证书」）视为节头。"""
    for kw in keywords:
        base = kw.split("/")[0]
        if re.match(rf"^{re.escape(base)}(?:经历|经验|资质|ship)?\s*[:：]?\s*$", line, re.IGNORECASE):
            return True
    return False


def _single_line_entry(line: str, keywords: tuple[str, ...]) -> str | None:
    """单行格式（QA-BUG-004 a）：`实习：xxx` / `项目：xxx` / `证书：xxx` 直接成条目。"""
    for kw in keywords:
        m = re.match(
            rf"^{re.escape(kw)}(?:经历|经验|资质|ship)?\s*[:：]\s*(.+)$",
            line,
            re.IGNORECASE,
        )
        if m:
            return m.group(1).strip().rstrip("，,；;。")
    return None


def _build_stop_regex(keywords: tuple[str, ...]) -> re.Pattern:
    """当前节内的结束判定：其余节头（排除当前关键词，避免内容行含自身关键词误终止）。"""
    excluded = {kw.split("/")[0] for kw in keywords}
    others = [name for name in _SECTION_NAMES if name not in excluded]
    return re.compile(rf"^(?:{'|'.join(others)})(?:经历|经验|资质|ship)?\s*[:：]?", re.IGNORECASE)


def _extract_section(raw_lines: list[str], keywords: tuple[str, ...]) -> list[list[str]]:
    """从简历中提取节条目（每组=一条经历的原始行列表，支持多行描述块）。

    - 节头：独立短行（如「实习经历」），含关键词的内容行不再被误判为节头跳过（QA-BUG-004）
    - 单行格式：`实习：xxx` 直接成条目
    - 条目切分：序号/项目符号行开启新条目；缩进续行与长描述行并入上一条目（完整性）；
      无标记的短行视为新条目名
    - 遇下一节头结束
    """
    stop_re = _build_stop_regex(keywords)
    entries: list[list[str]] = []
    in_section = False
    for ln in raw_lines:
        s = ln.strip()
        single = _single_line_entry(s, keywords)
        if single is not None:
            entries.append([single])
            continue
        if _is_section_header(s, keywords):
            in_section = True
            continue
        if in_section:
            if stop_re.match(s):
                in_section = False
                continue
            if _is_entry_start(s):
                entries.append([s])
            elif entries and (ln[:1].isspace() or _is_continuation(entries[-1][-1], s)):
                entries[-1].append(s)
            else:
                entries.append([s])
            if len(entries) >= 8:
                break
    return entries[:5]


_ENTRY_MARKER_RE = re.compile(r"^\s*(?:[0-9]{1,2}[.、)]|[-·•*])\s*")
_END_PUNCT_RE = re.compile(r"[。.!?！？;；]$")


def _is_entry_start(line: str) -> bool:
    """序号/项目符号行开启新条目。"""
    return bool(_ENTRY_MARKER_RE.match(line))


def _is_continuation(prev_line: str, line: str) -> bool:
    """判断无标记行是否属于上一条目：长描述行并入；短行视为新条目名（缩进判定在调用处）。"""
    if _END_PUNCT_RE.search(prev_line):
        return False
    if len(line) > 30:
        return True
    return False


def _strip_bullet(line: str) -> str:
    return re.sub(r"^\s*(?:[0-9]+[.、)]|[-·•*])\s*", "", line).strip()


def _internship_entry(lines: list[str]) -> dict:
    """单条实习（可含多行）→ {company, role, duration}（对齐 ApiInternship；启发式拆分，不可拆则 company 保留原文）。"""
    text = _strip_bullet(lines[0]) if lines else ""
    for raw in lines[1:]:
        text += " " + _strip_bullet(raw)
    duration = None
    m = _DURATION_RE.search(text)
    if m:
        duration = m.group(0)
        text = text.replace(m.group(0), "")
    text = _PAREN_RE.sub("", text).strip(" -·•*，,；;。")
    parts = [p for p in re.split(r"[\s·、/]+", text) if p]
    company = parts[0] if parts else None
    role = " ".join(parts[1:]) if len(parts) > 1 else None
    return {"company": company, "role": role, "duration": duration}


def _project_entry(lines: list[str]) -> dict:
    """单条项目（可含多行）→ {name, description, tech}（对齐 ApiProject；无描述置 None，禁止编造）。

     完整性：续行描述并入 description，不再仅取首行，避免多行项目内容丢失。
    """
    first = _strip_bullet(lines[0]) if lines else ""
    tech: list[str] = []
    m = _TECH_PAREN_RE.search(first)
    if m:
        tech = [t.strip() for t in re.split(r"[、,，;；/+]+", m.group(1)) if t.strip()][:5]
        first = first.replace(m.group(0), "")
    name = first.strip(" -·•*，,；;。") or None
    desc = " ".join(_strip_bullet(raw) for raw in lines[1:]).strip(" -·•*，,；;。") or None
    return {"name": name, "description": desc, "tech": tech}


def _certificate_entry(lines: list[str]) -> str:
    """单条证书行 → 去项目符号后的纯文本（：证书条目不再带「-」等符号）。"""
    return " ".join(_strip_bullet(ln) for ln in lines).strip(" -·•*，,；;。")


def normalize_internships(items) -> list[dict]:
    """结构防御：任意来源的 internships 归一为 list[dict]（对齐 ApiInternship）。"""
    out: list[dict] = []
    for item in items or []:
        if isinstance(item, dict):
            out.append(item)
        elif isinstance(item, str):
            out.append({"company": item, "role": None, "duration": None})
    return out


def normalize_projects(items) -> list[dict]:
    """结构防御：任意来源的 projects 归一为 list[dict]（对齐 ApiProject）。"""
    out: list[dict] = []
    for item in items or []:
        if isinstance(item, dict):
            out.append(item)
        elif isinstance(item, str):
            out.append({"name": item, "description": None, "tech": []})
    return out


_IMPLICATION_KEY_RES = {
    key: re.compile(rf"\b{re.escape(key)}\b", re.IGNORECASE) for key in IMPLICATION_MAP
}
_ALIAS_RES = {
    alias: re.compile(rf"\b{re.escape(alias)}\b", re.IGNORECASE) for alias in SKILL_ALIASES
}


def _collect_project_techs(projects) -> list[str]:
    """收集所有项目的 tech 技术栈（小写去重保序，供蕴含反推与 grounding 依据）。"""
    techs: list[str] = []
    for proj in projects or []:
        if not isinstance(proj, dict):
            continue
        for t in proj.get("tech") or []:
            if isinstance(t, str) and t.strip():
                techs.append(t.strip().lower())
    return list(dict.fromkeys(techs))


def postprocess_skills_with_sources(
    skills, raw_text, projects
) -> tuple[list[str], list[str]]:
    """技能后处理 + provenance 标记：在 _parse_resume 入口统一执行，覆盖 LLM 与规则兜底两路径。

    流程：
    1. 别名归一（js→javascript、ts→typescript，标准名与 _KNOWN_SKILL_KEYWORDS 一致）
    2. 项目 tech 蕴含反推补技能（扩展：框架/工具→语言 fastapi→python、spring→java 等
       9 组 + 框架→框架 langgraph→langchain；蕴含等级由 executor 侧消费，parser 侧统一补入）
    3. grounding 过滤：每个技能须能在原文文本或 tech 蕴含映射中找到依据，找不到剔除（防 LLM 幻觉）
    4. 去重保序（标准名大小写不敏感去重）

    返回 (skills, sources) 并行数组，索引对齐。provenance 语义：
    - literal：技能在原文显式出现（_in_text 原文依据）；
    - inferred：技能不在原文，由 IMPLICATION_MAP 蕴含反推（_implied_by_tech 蕴含依据）；
    - 双重来源时 literal 优先（原文同含 fastapi+python → python 标 literal）；
    - grounding 过滤仍只对 literal 依据生效：无原文依据且无蕴含依据 → 剔除（不输出）。

    反幻觉底线：只做「tech 数组明确出现的技术栈」的蕴含，不凭空推断；grounding 找不到依据即剔除。
    """
    text_low = (raw_text or "").lower()

    def _in_text(skill_low: str) -> bool:
        """技能（或其别名形式）是否在原文中出现。

        ASCII 单词按词边界匹配（防子串误命中幻觉：如原文只有 javascript 时，LLM 输出 java
        不应通过原文依据）；中文 / 含特殊字符词（c++、c#）保持子串匹配（词边界会破坏匹配）。
        """
        for alias, std in SKILL_ALIASES.items():
            if std == skill_low and _ALIAS_RES[alias].search(text_low):
                return True
        if skill_low.isascii() and "+" not in skill_low and "#" not in skill_low:
            return bool(re.search(rf"\b{re.escape(skill_low)}\b", text_low))
        return skill_low in text_low

    def _implied_by_tech(skill_low: str) -> bool:
        """技能是否由**原文中明确出现**的技术栈蕴含（grounding 依据 2）。

        ⚠️ 触发源只取原文词边界出现的蕴含键：projects.tech 数组是 LLM 输出，可能被幻觉
        （原文无 Vue 却编造 tech=["Vue"]），不作为蕴含触发源；tech 本身须走 _in_text 原文依据。
        蕴含键在原文出现（如原文写了 LangGraph），其蕴含技能（llm api）才有依据。
        """
        # 原文文本中出现的蕴含键（词边界，避免 rag 误匹配 storage 等）
        triggered = [k for k in IMPLICATION_MAP if _IMPLICATION_KEY_RES[k].search(text_low)]
        implied = {s for key in triggered for s, _ in IMPLICATION_MAP[key]}
        return skill_low in implied

    normalized: list[str] = []
    seen: set[str] = set()

    def _add(skill: str) -> None:
        s = skill.strip()
        key = s.lower()
        if key and key not in seen:
            seen.add(key)
            normalized.append(s)

    # 1) 别名归一（原技能）
    for s in skills or []:
        if not isinstance(s, str):
            continue
        std = SKILL_ALIASES.get(s.strip().lower(), s.strip())
        _add(std)

    # 2) 项目 tech 数组技术栈（②）补入 + 蕴含反推（③）
    # tech 本身（如 langgraph/vue/react）作为技能补入；grounding 时须在原文出现（防 tech 幻觉），
    # 蕴含技能（如 llm api/javascript）由 IMPLICATION_MAP 依据保留。
    # 单字符 tech 跳过（_project_entry 拆分 "C++" 会产生 "C" 噪音，防御）。
    for tech in _collect_project_techs(projects):
        if len(tech) >= 2:
            _add(tech)
        for implied, _level in IMPLICATION_MAP.get(tech, ()):
            _add(implied)

    # 3) grounding 过滤（原文依据 或 蕴含依据），去重保序，并标记 provenance
    out_skills: list[str] = []
    out_sources: list[str] = []
    for s in normalized:
        low = s.lower()
        if _in_text(low):
            out_skills.append(s)
            out_sources.append("literal") # 双重来源时 literal 优先
        elif _implied_by_tech(low):
            out_skills.append(s)
            out_sources.append("inferred")
    return out_skills, out_sources


def postprocess_skills(skills, raw_text, projects) -> list[str]:
    """兼容包装：返回 skills 列表，既有调用点/测试签名不变。

    provenance 由 postprocess_skills_with_sources 输出；需要 sources 的调用点（router 两路径）
    改用 with_sources 版本。
    """
    skills_out, _ = postprocess_skills_with_sources(skills, raw_text, projects)
    return skills_out


def check_profile_complete(profile: dict) -> bool:
    """C-002 最低信息门槛：姓名、学历、专业、毕业年份 + 至少 1 段实习/项目经历。"""
    return bool(
        profile.get("name")
        and profile.get("education")
        and profile.get("major")
        and profile.get("graduation_year")
        and (profile.get("internships") or profile.get("projects"))
    )
