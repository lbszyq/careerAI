"""评估数据集加载器。

- 默认数据目录：``<backend>/evaluation_data``（按本文件所在位置向上定位，禁止依赖 cwd）。
- 所有加载函数返回已通过 Pydantic 校验的对象列表；文件缺失/损坏时抛出带路径的异常，
  由调用脚本转为明确错误信息（不崩溃）。
- 加载器仅依赖 pydantic，不 import 任何 LLM / 向量库 / 数据库代码。
"""
import json
from pathlib import Path

from app.ai.evaluation.schemas import (
    MarketCorpusRecord,
    PortraitEvalCase,
    RagEvalCase,
    ReportEvalCase,
    ResumeEvalCase,
)

EVALUATION_DATA_DIR = Path(__file__).resolve().parents[3] / "evaluation_data"

_SCHEMA_VERSION = "1.0"


def _load_cases(path: Path, model: type) -> list:
    """读取 ``{"_meta": ..., "cases": [...]}`` 并校验 cases。"""
    if not path.is_file():
        raise FileNotFoundError(f"评测集文件不存在：{path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"评测集文件 JSON 解析失败：{path}（{exc}）") from exc
    if not isinstance(raw, dict) or "cases" not in raw:
        raise ValueError(f"评测集文件缺少 cases 数组：{path}")
    cases = raw["cases"]
    if not isinstance(cases, list):
        raise ValueError(f"评测集文件 cases 必须为数组：{path}")
    try:
        return [model.model_validate(item) for item in cases]
    except Exception as exc: # noqa: BLE001 转成带文件路径的错误
        raise ValueError(f"评测集文件 schema 校验失败：{path}（{exc}）") from exc


def load_resume_cases(data_dir: Path | str | None = None) -> list[ResumeEvalCase]:
    return _load_cases(_data_path(data_dir, "resume_cases.json"), ResumeEvalCase)


def load_portrait_cases(data_dir: Path | str | None = None) -> list[PortraitEvalCase]:
    return _load_cases(_data_path(data_dir, "portrait_cases.json"), PortraitEvalCase)


def load_report_cases(data_dir: Path | str | None = None) -> list[ReportEvalCase]:
    return _load_cases(_data_path(data_dir, "report_cases.json"), ReportEvalCase)


def load_rag_cases(data_dir: Path | str | None = None) -> list[RagEvalCase]:
    return _load_cases(_data_path(data_dir, "rag_cases.json"), RagEvalCase)


def load_market_corpus(data_dir: Path | str | None = None) -> list[MarketCorpusRecord]:
    return _load_cases(_data_path(data_dir, "market_corpus.json"), MarketCorpusRecord)


def _data_path(data_dir: Path | str | None, filename: str) -> Path:
    base = Path(data_dir) if data_dir else EVALUATION_DATA_DIR
    return base / filename


def market_record_to_text(record: MarketCorpusRecord) -> str:
    """语料记录 → 检索文本（对齐 app/ai/rag/vectorize.build_record_text 的拼装口径）。

    mock 模式用它构造内存语料，保证与真实向量化入库文本格式一致。
    """
    skills = "、".join(record.required_skills or []) or "暂无"
    parts = [
        f"岗位：{record.job_title}",
        f"城市：{record.city}",
        f"行业：{record.industry}",
        f"薪资P25/P50/P75：{record.salary_p25}/{record.salary_p50}/{record.salary_p75}",
        f"趋势：{record.trend or '未知'}",
        f"热度：{record.heat or '未知'}",
        f"技能要求：{skills}",
        f"来源：{record.data_source or '未知'}",
    ]
    if record.data_quarter:
        parts.append(f"数据季度：{record.data_quarter}")
    return "；".join(parts)


def schema_description() -> str:
    """评测集 schema 说明（供脚本 --schema 输出 / README 引用）。"""
    return (
        f"评测集 schema v{_SCHEMA_VERSION}\n"
        "统一结构：{\"_meta\": {schema_version, category, description, structure}, \"cases\": [...]}\n"
        "- resume_cases.json: cases[] = {case_id, category:\"resume\", description, input:{resume_text}, expected:{must_have_fields, expected_name, expected_education, expected_skills, must_contain_text, must_not_contain_text}}\n"
        "- portrait_cases.json: cases[] = {case_id, category:\"portrait\", description, input:{portrait 对象}, expected:{must_have_fields, overall_score_min, overall_score_max, dimensions_required, confidence_allowed}}\n"
        "- report_cases.json: cases[] = {case_id, category:\"report\", description, report:{报告对象}, expected:{must_have_fields, must_not_contain, directions_min/max, gap_items_min, plan_tasks_min, suggestion}}\n"
        "- rag_cases.json: cases[] = {case_id, category:\"rag\", description, query, expected_job_titles, expected_skills, expected_city, must_not_hit?(Top-10 不得命中), is_negative?(无命中反例，不计入 recall 聚合)}\n"
        "- market_corpus.json: cases[] = {id, city, industry, job_title, salary_p25/p50/p75, trend, heat, required_skills, data_source, confidence, data_quarter, city_tier, source_type}\n"
        "权威 schema 定义：backend/app/ai/evaluation/schemas.py"
    )
