"""AI 评估数据集加载与访问入口。"""
from app.ai.evaluation.loader import (
    EVALUATION_DATA_DIR,
    load_market_corpus,
    load_portrait_cases,
    load_rag_cases,
    load_report_cases,
    load_resume_cases,
    market_record_to_text,
    schema_description,
)

__all__ = [
    "EVALUATION_DATA_DIR",
    "load_resume_cases",
    "load_portrait_cases",
    "load_report_cases",
    "load_rag_cases",
    "load_market_corpus",
    "market_record_to_text",
    "schema_description",
]
