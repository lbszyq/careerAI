"""AI fallback 测试：mock LLM 抛错/不可用时走规则模板，返回成功结构而非崩溃。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from test_resume_parse import REAL_RESUME_TEXT

from app.ai.agents.deps import AgentDeps
from app.ai.agents.executor_agent import executor_node
from app.ai.agents.planner import planner_node
from app.ai.agents.router import _parse_resume
from app.ai.fallback.report_assembler import assemble_stage1_report
from app.ai.llm.client import LLMClient
from app.ai.llm.exceptions import LLMTimeoutError, LLMUnavailableError
from app.ai.schemas import initial_state


class _BrokenLLM:
    """is_available=True 但每次调用都抛 LLM 异常（模拟服务故障）。"""

    is_available = True

    def __init__(self, exc: Exception):
        self._exc = exc

    async def complete_json(self, **kwargs):
        raise self._exc


class _FakeLLM:
    """is_available=True 且 complete_json 返回预设 JSON（模拟 LLM 正常/幻觉输出）。"""

    is_available = True

    def __init__(self, data: dict):
        self._data = data

    async def complete_json(self, **kwargs):
        return self._data


def _executor_state(**overrides) -> dict:
    """Stage2 最小输入：画像 + 目标岗位 + JD 要求。"""
    state = {
        "profile": {"name": "张三", "education": "本科", "major": "计算机", "skills": ["Python", "Git"]},
        "target_job": "后端工程师",
        "target_job_requirements": ["Python", "FastAPI", "PostgreSQL"],
        "target_job_jd_summary": {"data_grade": "B", "job_title": "后端工程师"},
        "stage": "stage2",
    }
    state.update(overrides)
    return initial_state(**state)


def test_assemble_stage1_report_returns_success_structure():
    state = {
        "stage": "stage1",
        "scores": {
            "overall_score": 72,
            "dimensions": {"专业能力": 72, "项目经验": 65},
            "strengths": ["Python"],
            "weaknesses": ["SQL"],
        },
        "market_results": [
            {"job_title": "后端工程师", "match_score": 0.85, "salary": "20-35K", "data_source": "招聘平台"}
        ],
        "stage_errors": ["planner_node: mock 故障"],
    }
    report = assemble_stage1_report(state)
    assert report["stage"] == "stage1"
    assert report["portrait"]["overall_score"] == 72
    assert report["directions"][0]["job_title"] == "后端工程师"
    assert any("不完整" in note for note in report["notes"])


def test_assemble_stage1_report_empty_state_still_succeeds():
    report = assemble_stage1_report({"stage": "stage1", "stage_errors": ["x: mock"]})
    assert report["stage"] == "stage1"
    assert report["portrait"]["overall_score"] is None
    assert report["directions"] == []
    assert any("无评分数据" in note for note in report["notes"])


async def test_executor_node_llm_error_fails_with_plan_none():
    """：LLM 调用失败 → executor 节点失败（plan=None + stage_errors），不降级死模板。"""
    deps = AgentDeps(llm=_BrokenLLM(LLMUnavailableError("mock: LLM 服务不可用")))
    result = await executor_node(_executor_state(), deps)
    assert result["plan"] is None
    assert result["gap_items"] == []
    assert result["confidence"]["executor"] == "低"
    assert "LLM 生成成长计划失败" in " ".join(result["stage_errors"])


async def test_executor_node_llm_none_fails_with_plan_none():
    """：LLM 不可用 → executor 节点失败（plan=None + stage_errors），确保用户走 LLM 路径。"""
    deps = AgentDeps(llm=None)
    result = await executor_node(_executor_state(), deps)
    assert result["plan"] is None
    assert result["gap_items"] == []
    assert "LLM 生成成长计划失败" in " ".join(result["stage_errors"])


async def test_planner_node_llm_none_returns_fallback_report():
    state = initial_state(
        stage="stage1",
        scores={
            "overall_score": 68,
            "dimensions": {"专业能力": 70, "项目经验": 65},
            "strengths": ["Python"],
            "weaknesses": ["SQL"],
        },
        stage_errors=["career_analysis_node: LLMUnavailableError"],
    )
    deps = AgentDeps(llm=None)
    result = await planner_node(state, deps)
    assert result["stage"] == "stage1"
    report = result["report"]
    assert report["stage"] == "stage1"
    assert report["portrait"]["overall_score"] == 68
    assert any("不完整" in note for note in report["notes"])


def _llm_settings(**overrides) -> SimpleNamespace:
    """构造 LLMClient 所需的 settings 对象（避免读取 .env/真实配置）。"""
    base = {
        "DEEPSEEK_API_KEY": "sk-test-only",
        "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
        "DEEPSEEK_MODEL": "deepseek-v4-flash",
        "DEEPSEEK_FALLBACK_MODEL": "",
        "DEEPSEEK_TIMEOUT_SECONDS": 30.0,
        "DEEPSEEK_MAX_RETRIES": 3,
        "DEEPSEEK_TEMPERATURE": 0.3,
        "DEEPSEEK_MAX_OUTPUT_TOKENS": 4096,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_llm_client_unavailable_without_api_key():
    client = LLMClient(settings=_llm_settings(DEEPSEEK_API_KEY=""))
    assert client.is_available is False
    with pytest.raises(LLMUnavailableError):
        client._get_client()


async def test_llm_client_complete_maps_timeout_to_llm_error(monkeypatch):
    client = LLMClient(settings=_llm_settings(DEEPSEEK_MAX_RETRIES=0))
    fake_openai = AsyncMock()
    fake_openai.chat.completions.create = AsyncMock(side_effect=httpx.TimeoutException("mock timeout"))
    client._client = fake_openai
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    with pytest.raises(LLMTimeoutError):
        await client.complete("system", "user", node_name="test_node")


async def test_llm_client_complete_reraises_unavailable():
    client = LLMClient(settings=_llm_settings(DEEPSEEK_MAX_RETRIES=0))
    fake_openai = AsyncMock()
    fake_openai.chat.completions.create = AsyncMock(side_effect=LLMUnavailableError("mock 不可用"))
    client._client = fake_openai
    with pytest.raises(LLMUnavailableError):
        await client.complete("system", "user", node_name="test_node")


# ---------- ：技能画像提取增强（标准 1/2/3/4） ----------


def _llm_profile(**skills_and_projects) -> dict:
    """构造 router_node 最小 LLM 输出（姓名+专业齐全走 LLM 分支）。"""
    return {
        "name": "张三",
        "school": "清华大学",
        "major": "计算机科学与技术",
        "education": "本科",
        "graduation_year": 2025,
        "skills": list(skills_and_projects.get("skills") or []),
        "projects": skills_and_projects.get("projects") or [],
        "internships": [],
        "certificates": [],
        "completeness": {},
    }


async def test_parse_resume_llm_error_falls_back_to_rules_skills_nonempty():
    """标准 4：mock LLM 抛 LLMUnavailableError → _parse_resume 转规则兜底，skills 非空且不抛异常。"""
    llm = _BrokenLLM(LLMUnavailableError("mock: LLM 服务不可用"))
    profile = await _parse_resume(REAL_RESUME_TEXT, llm)
    assert profile["skills"], "规则兜底路径应按词表命中技能"
    assert profile["generated_by"] == "rule_template"
    # 规则兜底路径同样做蕴含/别名后处理（标准 1 覆盖两路径）
    assert "javascript" in [s.lower() for s in profile["skills"]]
    assert "llm api" in [s.lower() for s in profile["skills"]]


async def test_parse_resume_llm_timeout_falls_back_to_rules():
    """标准 4：mock LLM 抛 LLMTimeoutError → 转规则兜底，skills 非空且不抛异常。"""
    llm = _BrokenLLM(LLMTimeoutError("mock: 超时"))
    profile = await _parse_resume(REAL_RESUME_TEXT, llm)
    assert profile["skills"]
    assert profile["generated_by"] == "rule_template"


async def test_parse_resume_llm_missing_javascript_implied_from_vue():
    """标准 1：mock LLM 注入 skills 缺 javascript、projects.tech 含 vue → 后处理补入 javascript。"""
    llm = _FakeLLM(_llm_profile(skills=["Python", "Git"], projects=[{"name": "前端", "tech": ["Vue"]}]))
    profile = await _parse_resume(REAL_RESUME_TEXT, llm)
    skills = [s.lower() for s in profile["skills"]]
    assert "javascript" in skills
    assert "typescript" in skills


async def test_parse_resume_llm_hallucinated_skill_grounding_filtered():
    """标准 2（grounding 过滤）：mock LLM 注入幻觉技能（简历无 Cobol）→ 被过滤剔除。"""
    llm = _FakeLLM(_llm_profile(skills=["Python", "Cobol", "Fortran"], projects=[]))
    profile = await _parse_resume(REAL_RESUME_TEXT, llm)
    skills = [s.lower() for s in profile["skills"]]
    assert "python" in skills # 原文依据
    assert "cobol" not in skills
    assert "fortran" not in skills


async def test_parse_resume_llm_alias_normalization():
    """标准 3（别名归一）：mock LLM 返回 skills=['JS','TS'] → 归一为 javascript/typescript。"""
    llm = _FakeLLM(_llm_profile(skills=["JS", "TS"], projects=[]))
    profile = await _parse_resume(REAL_RESUME_TEXT, llm)
    skills = [s.lower() for s in profile["skills"]]
    assert "javascript" in skills
    assert "typescript" in skills
    assert "js" not in skills
    assert "ts" not in skills
