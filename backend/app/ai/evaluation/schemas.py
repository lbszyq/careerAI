"""AI 评估数据集 Schema。

统一文件结构（每个 JSON 评测集文件）：
    {
      "_meta": { "schema_version": "...", "category": "...", "description": "...", "structure": "..." },
      "cases": [ ... ]
    }
    - ``_meta`` 仅作人类可读说明，加载器不校验其内容；
    - ``cases`` 由本模块对应 Pydantic 模型严格校验（extra="forbid"，未知字段即报错）。

评测输入覆盖三类（验证标准 3）：
- ``resume_cases.json`` —— 简历原文输入（真实风格、纯合成、无隐私），预留简历解析评估；
- ``portrait_cases.json`` —— 职业画像对象（report.portrait 同构），供画像结构/评分区间校验；
- ``report_cases.json`` —— 最终报告对象（stage1/stage2，reports-contract 结构），供报告质量校验。

RAG 检索评估（eval_rag.py）另有两份文件：
- ``rag_cases.json`` —— 检索查询 + 期望命中岗位（ground truth）；
- ``market_corpus.json``—— 合成市场语料（模拟 market_data 记录，mock 模式的确定性检索底座）。
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# 简历输入
# ---------------------------------------------------------------------------
class ResumeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resume_text: str = Field(min_length=1, description="简历原文（合成样例）")


class ResumeExpected(BaseModel):
    model_config = ConfigDict(extra="forbid")

    must_have_fields: list[str] = Field(
        default_factory=list,
        description="解析结果顶层必须存在的字段（如 name/education/major/skills）",
    )
    expected_name: str | None = Field(default=None, description="期望姓名（可空）")
    expected_education: str | None = Field(default=None, description="期望学历（可空）")
    expected_skills: list[str] = Field(default_factory=list, description="期望技能清单")
    must_contain_text: list[str] = Field(default_factory=list, description="简历原文必须包含的片段")
    must_not_contain_text: list[str] = Field(default_factory=list, description="简历原文禁止包含的片段")


class ResumeEvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    category: Literal["resume"]
    description: str = ""
    input: ResumeInput
    expected: ResumeExpected


# ---------------------------------------------------------------------------
# 职业画像（与 report.portrait 同构）
# ---------------------------------------------------------------------------
class PortraitExpected(BaseModel):
    model_config = ConfigDict(extra="forbid")

    must_have_fields: list[str] = Field(
        default_factory=list,
        description="画像顶层必须存在的键（如 overall_score/dimensions/strengths/weaknesses/confidence）",
    )
    overall_score_min: int = 0
    overall_score_max: int = 100
    dimensions_required: list[str] = Field(
        default_factory=lambda: ["technical", "project", "academic", "soft_skill", "industry_knowledge"],
        description="五维评分必须包含的维度键",
    )
    confidence_allowed: list[str] = Field(default_factory=lambda: ["高", "中", "低"])


class PortraitEvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    category: Literal["portrait"]
    description: str = ""
    input: dict = Field(description="画像对象（含 overall_score/dimensions 等）")
    expected: PortraitExpected = Field(default_factory=PortraitExpected)


# ---------------------------------------------------------------------------
# 最终报告（stage1/stage2，reports-contract）
# ---------------------------------------------------------------------------
class ReportExpected(BaseModel):
    model_config = ConfigDict(extra="forbid")

    must_have_fields: list[str] = Field(
        default_factory=list,
        description="报告必须存在的点分路径字段（如 portrait.overall_score / plan.tasks）",
    )
    must_not_contain: list[str] = Field(
        default_factory=list,
        description="额外占位文案黑名单（大小写不敏感，追加到全局规则）",
    )
    directions_min: int | None = Field(default=None, description="directions 数量下限（None=不校验）")
    directions_max: int | None = Field(default=None, description="directions 数量上限（None=不校验）")
    gap_items_min: int | None = Field(default=None, description="gap_analysis.items 数量下限")
    plan_tasks_min: int | None = Field(default=None, description="plan.tasks 数量下限")
    suggestion: Literal["null", "dict", "any"] = Field(
        default="any",
        description="suggestion 期望形态：null=必须为 None；dict=必须为对象；any=不校验",
    )


class ReportEvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    category: Literal["report"]
    description: str = ""
    report: dict = Field(description="待校验报告对象")
    expected: ReportExpected = Field(default_factory=ReportExpected)


# ---------------------------------------------------------------------------
# RAG 检索评测（eval_rag.py）
# ---------------------------------------------------------------------------
class RagEvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    category: Literal["rag"]
    description: str = ""
    query: str = Field(min_length=1, description="检索查询（模拟面试/产品提问）")
    expected_job_titles: list[str] = Field(
        min_length=1, description="期望命中的岗位（ground truth，至少 1 个）"
    )
    expected_skills: list[str] = Field(default_factory=list, description="期望命中的技能要求")
    expected_city: str | None = Field(default=None, description="期望命中的城市（可空）")
    must_not_hit: list[str] = Field(
        default_factory=list,
        description="负向断言（2b 方案①）：Top-10 不得命中的岗位（precision 断言）",
    )
    is_negative: bool = Field(
        default=False,
        description="反例标记（2d）：无命中查询用例，单列断言不计入 recall@10 聚合",
    )


class MarketCorpusRecord(BaseModel):
    """合成市场语料记录（字段对齐 market_data / MarketHit）。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    city: str
    industry: str
    job_title: str
    salary_p25: float | None = None
    salary_p50: float | None = None
    salary_p75: float | None = None
    trend: str | None = None
    heat: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    data_source: str | None = None
    confidence: float | None = None
    data_quarter: str | None = None
    city_tier: str | None = None
    source_type: Literal["official_stat", "job_post", "ai_infer"] | None = None
