"""差距分析与成长计划 LLM 化测试。

覆盖（验证标准 1/2 + 边界）：
- executor 失败语义：LLM 不可用 / 调用失败 / plan.tasks 空重试仍空 → plan=None +
  stage_errors「LLM 生成成长计划失败」，不产出「系统学习并掌握 {skill} 基础」死模板；
- 重试语义：第 1 次 plan.tasks 空、第 2 次完整 → 成功且 LLM 恰好调用 2 次；
- 技能蕴含推理：LangGraph→LLM API、Vue→TypeScript 判「部分具备」而非「不具备」；
- 蕴含等级：FastAPI→Python 判「已具备」（框架→语言硬依赖，不具备/部分具备均升级）；
  LangGraph→LangChain 判「部分具备」而非「已具备」（框架→框架上限），LLM 幻觉已具备 → 压回部分具备；
- 反幻觉：用户 skills 无 LangGraph 时 LLM API 不得判「已具备」；gap_items 含非 dict/缺 level/
  level 非法值时不崩溃、不误升级；
- 分级权重：core 项权重 > nice-to-have 项权重（不再平均）；
- required_level 权威注入（来源=市场 Agent requirements，禁止 LLM 自判）；
- market：required_skills 分级归一（dict/字符串兼容、非法等级→core、去重）。
"""
from app.ai.agents.deps import AgentDeps
from app.ai.agents.executor_agent import (
    _apply_required_level_weights,
    _apply_skill_implications,
    _inject_gap_required_level,
    executor_node,
)
from app.ai.agents.market import _normalize_required_skills, market_research_node
from app.ai.llm.exceptions import LLMUnavailableError
from app.ai.schemas import initial_state


class _FakeLLM:
    """可配置输出序列的 mock（is_available=True）；超出预期调用次数时抛 AssertionError。"""

    is_available = True

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    async def complete_json(self, **kwargs):
        self.calls += 1
        if self._responses:
            return self._responses.pop(0)
        raise AssertionError("LLM 调用超出预期次数")


def _gap(skill, level="不具备", required_level=None):
    item = {
        "skill": skill,
        "level": level,
        "jd_source": f"JD 要求：{skill}",
        "evidence": f"用户技能列表无 {skill}",
    }
    if required_level is not None:
        item["required_level"] = required_level
    return item


def _valid_plan():
    return {
        "tasks": [
            {
                "name": "完成 SQL 窗口函数专项练习",
                "resource": "LeetCode SQL 题库（178/185/601）",
                "duration": "2 周",
                "stage": "short",
                "acceptance_criteria": "独立 AC 窗口函数 10 题并写出题解笔记",
            }
        ]
    }


def _executor_state(**overrides):
    state = {
        "profile": {"name": "张三", "education": "本科", "major": "计算机", "skills": ["Python"]},
        "target_job": "后端开发工程师",
        "target_job_requirements": ["LLM API"],
        "target_job_jd_summary": {"data_grade": "B", "job_title": "后端开发工程师"},
        "stage": "stage2",
    }
    state.update(overrides)
    return initial_state(**state)


# ---------- 标准 1：executor 失败语义（LLM 仅路径，去掉规则兜底） ----------


async def test_executor_llm_unavailable_fails_with_plan_none():
    deps = AgentDeps(llm=None)
    result = await executor_node(_executor_state(), deps)
    assert result["plan"] is None
    assert result["gap_items"] == []
    assert result["confidence"]["executor"] == "低"
    assert "LLM 生成成长计划失败" in " ".join(result["stage_errors"])


async def test_executor_llm_error_fails_with_plan_none():
    class _Broken:
        is_available = True

        async def complete_json(self, **kwargs):
            raise LLMUnavailableError("mock: LLM 服务不可用")

    result = await executor_node(_executor_state(), deps=AgentDeps(llm=_Broken()))
    assert result["plan"] is None
    assert "LLM 生成成长计划失败" in " ".join(result["stage_errors"])


async def test_executor_retries_once_then_succeeds():
    """LLM 第 1 次 plan.tasks 空 → 重试 1 次（共 2 次调用），第 2 次完整 → 成功。"""
    fake = _FakeLLM([
        {"gap_items": [_gap("LLM API")], "plan": {"tasks": []}},
        {"gap_items": [_gap("LLM API")], "plan": _valid_plan()},
    ])
    result = await executor_node(_executor_state(), deps=AgentDeps(llm=fake))
    assert fake.calls == 2
    assert result["plan"] is not None
    assert result["plan"]["tasks"]
    assert result["stage_errors"] == []


async def test_executor_empty_plan_tasks_after_retry_fails_with_plan_none():
    """重试仍空 → executor 失败：plan=None + stage_errors；gap_items 保留（报告成功但计划缺失）。"""
    fake = _FakeLLM([
        {"gap_items": [_gap("LLM API")], "plan": {"tasks": []}},
        {"gap_items": [_gap("LLM API")], "plan": {}},
    ])
    result = await executor_node(_executor_state(), deps=AgentDeps(llm=fake))
    assert fake.calls == 2
    assert result["plan"] is None
    assert result["gap_items"], "gap_items 应保留（失败语义：报告成功但计划缺失）"
    assert "LLM 生成成长计划失败" in " ".join(result["stage_errors"])
    # 死模板不得产出
    assert not any("系统学习并掌握" in str(t) for t in (result["plan"] or {}).get("tasks", []))


async def test_executor_happy_path_returns_normalized_plan():
    fake = _FakeLLM([{"gap_items": [_gap("LLM API")], "plan": _valid_plan()}])
    result = await executor_node(_executor_state(), deps=AgentDeps(llm=fake))
    assert fake.calls == 1
    assert result["plan"]["tasks"]
    assert result["stage_errors"] == []
    assert result["confidence"]["executor"] == "中"
    assert result["gap_items"][0]["required_level"] == "core"


# ---------- 标准 2：技能蕴含推理（复用 IMPLICATION_MAP） ----------


def test_apply_skill_implications_langgraph_implies_llm_api():
    gap_items = [_gap("LLM API", level="不具备")]
    out = _apply_skill_implications(gap_items, ["LangGraph"])
    assert out[0]["level"] == "部分具备", "会 LangGraph 时 LLM API 不得判不具备"
    assert "蕴含" in out[0]["evidence"]


def test_apply_skill_implications_vue_implies_typescript():
    gap_items = [_gap("TypeScript", level="不具备")]
    out = _apply_skill_implications(gap_items, ["Vue"])
    assert out[0]["level"] == "部分具备", "会 Vue 时 TypeScript 不得判不具备"


def test_apply_skill_implications_no_false_positive_without_trigger():
    """边界：用户无 LangGraph 时，LLM API 不得因蕴含被判已具备。"""
    gap_items = [_gap("LLM API", level="已具备")]
    out = _apply_skill_implications(gap_items, ["Python"])
    assert out[0]["level"] != "已具备", "无蕴含依据时不得判已具备（反幻觉）"
    assert out[0]["level"] == "不具备"


def test_apply_skill_implications_keep_literal_have():
    """用户字面具备该技能时保持已具备（非幻觉）。"""
    gap_items = [_gap("LLM API", level="已具备")]
    out = _apply_skill_implications(gap_items, ["LLM API"])
    assert out[0]["level"] == "已具备"


def test_apply_skill_implications_keep_have_when_not_gap():
    """非差距技能（已具备项）不受蕴含逻辑影响。"""
    gap_items = [_gap("Python", level="已具备")]
    out = _apply_skill_implications(gap_items, ["Python"])
    assert out[0]["level"] == "已具备"


# ---------- 标准 1c：蕴含等级语义（框架→语言=已具备 / 框架→框架=部分具备） ----------

def test_apply_skill_implications_fastapi_implies_python_full():
    """：框架→语言蕴含=已具备——会 FastAPI 时 Python 判「已具备」（不具备→已具备）。"""
    gap_items = [_gap("Python", level="不具备")]
    out = _apply_skill_implications(gap_items, ["FastAPI"])
    assert out[0]["level"] == "已具备", "会 FastAPI 时 Python 不得判不具备/部分具备"


def test_apply_skill_implications_fastapi_python_partial_upgrade():
    """：报告实测缺陷——LLM 判 Python「部分具备」时升级为「已具备」（硬前置依赖）。"""
    gap_items = [_gap("Python", level="部分具备")]
    out = _apply_skill_implications(gap_items, ["FastAPI"])
    assert out[0]["level"] == "已具备", "框架/语言硬依赖下部分具备应升级为已具备"


def test_apply_skill_implications_langgraph_implies_langchain_partial():
    """：框架→框架蕴含=部分具备——会 LangGraph 时 LangChain 判「部分具备」而非「已具备」。"""
    gap_items = [_gap("LangChain", level="不具备")]
    out = _apply_skill_implications(gap_items, ["LangGraph"])
    assert out[0]["level"] == "部分具备", "会 LangGraph 时 LangChain 不得判不具备"
    assert out[0]["level"] != "已具备", "框架→框架上限为部分具备，禁止判已具备"
    assert "部分具备" in out[0]["evidence"]


def test_apply_skill_implications_langgraph_langchain_mirror_cap():
    """：反幻觉镜像——LLM 幻觉判 LangChain「已具备」→ 压回「部分具备」（可快速上手≠已掌握）。"""
    gap_items = [_gap("LangChain", level="已具备")]
    out = _apply_skill_implications(gap_items, ["LangGraph"])
    assert out[0]["level"] == "部分具备", "部分具备蕴含下 LLM 判已具备必须压回部分具备"


def test_apply_skill_implications_fastapi_python_keep_have():
    """：状态转换矩阵——框架→语言依据下已具备保持已具备（防被降级分支误伤）。"""
    gap_items = [_gap("Python", level="已具备")]
    out = _apply_skill_implications(gap_items, ["FastAPI"])
    assert out[0]["level"] == "已具备"


def test_apply_skill_implications_pandas_implies_python_full():
    """扩展：pandas→Python 同为框架/工具→语言硬依赖——会 pandas 判 Python 已具备。"""
    gap_items = [_gap("Python", level="部分具备")]
    out = _apply_skill_implications(gap_items, ["pandas"])
    assert out[0]["level"] == "已具备"


# ---------- 标准 2a：结构防御（不崩溃、不误升级） ----------

def test_apply_skill_implications_malformed_gap_items_safe():
    """/：gap_items 含非 dict/缺 level/level 非法值——不崩溃、不误升级。"""
    gap_items = [
        "not-a-dict",
        None,
        {"skill": "Python", "level": "高级"}, # level 非法值（非三级枚举）
        {"skill": "Python"}, # 缺 level
    ]
    out = _apply_skill_implications(gap_items, ["FastAPI"])
    assert len(out) == len(gap_items), "非 dict 项应安全透传，数量不变"
    assert out[0] == "not-a-dict"
    assert out[1] is None
    assert out[2]["level"] == "高级", "非法 level 不误升级"
    assert "level" not in out[3], "缺 level 保持原样不误升级"


# ---------- 标准 2：分级权重（core > nice-to-have，不再平均） ----------


def test_apply_required_level_weights_core_gt_nice_to_have():
    gap_items = [
        _gap("SQL", required_level="core"),
        _gap("Redis", required_level="core"),
        _gap("Docker", required_level="nice-to-have"),
    ]
    out = _apply_required_level_weights(gap_items)
    core_weights = [g["weight"] for g in out if g["required_level"] == "core"]
    nice_weights = [g["weight"] for g in out if g["required_level"] == "nice-to-have"]
    assert core_weights and nice_weights
    for c in core_weights:
        for n in nice_weights:
            assert c > n, f"core 权重 {c} 必须 > nice-to-have 权重 {n}（分级权重硬约束）"
    total = sum(g["weight"] for g in out)
    assert 0.99 < total < 1.01


def test_apply_required_level_weights_equal_within_tier():
    """同档项均分（无分级差异时保持稳定，等价原平均）。"""
    gap_items = [_gap("SQL"), _gap("Redis")]
    out = _apply_required_level_weights(gap_items)
    assert out[0]["weight"] == out[1]["weight"] == 0.5


# ---------- 标准 2：required_level 权威注入（禁止 LLM 自判） ----------


def test_inject_gap_required_level_authoritative_from_requirements():
    requirements = [
        {"name": "SQL", "required_level": "core"},
        {"name": "Docker", "required_level": "nice-to-have"},
    ]
    gap_items = [_gap("SQL"), _gap("Docker")]
    out = _inject_gap_required_level(gap_items, requirements)
    by_skill = {g["skill"]: g["required_level"] for g in out}
    assert by_skill == {"SQL": "core", "Docker": "nice-to-have"}


def test_inject_gap_required_level_overrides_llm_value():
    """权威值覆盖 LLM 残留（禁止 LLM 自判，同 data_grade 模式）。"""
    requirements = [{"name": "SQL", "required_level": "nice-to-have"}]
    gap_items = [_gap("SQL", required_level="core")]
    out = _inject_gap_required_level(gap_items, requirements)
    assert out[0]["required_level"] == "nice-to-have"


def test_inject_gap_required_level_str_requirements_default_core():
    requirements = ["SQL"]
    gap_items = [_gap("SQL")]
    out = _inject_gap_required_level(gap_items, requirements)
    assert out[0]["required_level"] == "core"


# ---------- 标准 2：market required_skills 分级输出 ----------


def test_normalize_required_skills_mixed_shapes():
    raw = [
        {"name": "SQL", "required_level": "core"},
        {"skill": "Python", "required_level": "NICE-TO-HAVE"},
        "Docker",
        {"name": "SQL", "required_level": "nice-to-have"}, # 按 name 去重
        {"name": "Java", "required_level": "must"}, # 非法等级 → core
    ]
    out = _normalize_required_skills(raw)
    assert out == [
        {"name": "SQL", "required_level": "core"},
        {"name": "Python", "required_level": "nice-to-have"},
        {"name": "Docker", "required_level": "core"},
        {"name": "Java", "required_level": "core"},
    ]


async def test_market_stage2_required_skills_graded():
    """LLM 路径：required_skills 带 required_level → target_job_requirements 分级 dict。"""

    class _MarketLLM:
        is_available = True

        async def complete_json(self, **kwargs):
            return {
                "directions": [{
                    "job_title": "后端开发工程师",
                    "match_score": 85,
                    "salary": {"p25": 20, "p50": 28, "p75": 40},
                    "salary_note": "招聘平台样本",
                    "trend": "增长",
                    "heat": "高",
                    "data_source": "公开招聘",
                    "education_requirement": "本科",
                    "education_match": "匹配",
                    "competition_note": "竞争中等",
                    "certificates_bonus": None,
                    "recommend_reason": "技能匹配度高",
                }],
                "required_skills": [
                    {"name": "Python", "required_level": "core"},
                    {"name": "Docker", "required_level": "nice-to-have"},
                ],
            }

    state = initial_state(
        profile={"name": "张三", "major": "计算机", "education": "本科", "skills": ["Python"]},
        target_job="后端开发工程师",
        stage="stage2",
    )
    result = await market_research_node(state, deps=AgentDeps(llm=_MarketLLM(), embedding=None))
    assert result["target_job_requirements"] == [
        {"name": "Python", "required_level": "core"},
        {"name": "Docker", "required_level": "nice-to-have"},
    ]
    assert result["target_job_jd_summary"]["required_skills"][0] == {
        "name": "Python", "required_level": "core",
    }


async def test_market_stage2_required_skills_fallback_all_core():
    """LLM 失败路径：RAG 无数据 → 通用要求兜底，分级统一 core（不臆造加分项）。"""

    class _BrokenMarketLLM:
        is_available = True

        async def complete_json(self, **kwargs):
            raise LLMUnavailableError("mock: 市场 LLM 不可用")

    state = initial_state(
        profile={"name": "张三", "major": "计算机", "education": "本科", "skills": ["Python"]},
        target_job="后端开发工程师",
        stage="stage2",
    )
    result = await market_research_node(state, deps=AgentDeps(llm=_BrokenMarketLLM(), embedding=None))
    assert result["target_job_requirements"]
    assert all(item["required_level"] == "core" for item in result["target_job_requirements"])
    assert any("兜底" in e for e in result["stage_errors"])


# ---------- 标准 2：provenance 标记（gap 侧）+ PARTIAL inferred 权重打折 ----------

def test_apply_skill_implications_partial_inferred_marks_provenance():
    """：PARTIAL 蕴含（LangGraph→LLM API）→ provenance=inferred + inferred_kind=部分具备。"""
    gap_items = [_gap("LLM API", level="不具备")]
    out = _apply_skill_implications(gap_items, ["LangGraph"])
    assert out[0]["provenance"] == "inferred"
    assert out[0]["inferred_kind"] == "部分具备"
    assert out[0]["level"] == "部分具备"


def test_apply_skill_implications_full_inferred_marks_provenance():
    """：FULL 蕴含（FastAPI→Python）→ provenance=inferred + inferred_kind=已具备（不降权）。"""
    gap_items = [_gap("Python", level="不具备")]
    out = _apply_skill_implications(gap_items, ["FastAPI"])
    assert out[0]["provenance"] == "inferred"
    assert out[0]["inferred_kind"] == "已具备"
    assert out[0]["level"] == "已具备"


def test_apply_skill_implications_literal_provenance():
    """：用户字面具备 → provenance=literal（不降权，无 inferred_kind）。"""
    gap_items = [_gap("Python", level="已具备")]
    out = _apply_skill_implications(gap_items, ["Python"])
    assert out[0]["provenance"] == "literal"
    assert out[0]["level"] == "已具备"
    assert "inferred_kind" not in out[0]


def test_apply_skill_implications_no_evidence_provenance_none():
    """：无依据反幻觉降级 → provenance=none（既非字面也非蕴含）。"""
    gap_items = [_gap("LLM API", level="已具备")]
    out = _apply_skill_implications(gap_items, ["Python"])
    assert out[0]["provenance"] == "none"
    assert out[0]["level"] == "不具备"


def test_apply_skill_implications_inferred_user_skill_uses_implication():
    """：用户技能本身 inferred（python 由 fastapi 蕴含，原文未写 python）→ gap Python 走蕴含而非字面。"""
    # skills_sources=["inferred","literal"]：python 不在 literal_skills → 由 fastapi FULL 蕴含触发
    gap_items = [_gap("Python", level="已具备")]
    out = _apply_skill_implications(gap_items, ["python", "fastapi"], ["inferred", "literal"])
    assert out[0]["provenance"] == "inferred"
    assert out[0]["inferred_kind"] == "已具备"
    assert out[0]["level"] == "已具备" # FULL 蕴含维持已具备，不降权


def test_apply_skill_implications_sources_f4_defensive():
    """/：skills_sources 缺失/非法枚举/长度不匹配 → 默认 literal，不崩溃。"""
    gap_items = [_gap("Python", level="已具备"), _gap("LLM API", level="已具备")]
    # 长度不匹配（sources 为空）：Python 默认 literal，LLM API 无蕴含依据 → 反幻觉降级
    out = _apply_skill_implications(gap_items, ["Python", "LangGraph"], [])
    assert out[0]["provenance"] == "literal"
    # 非法枚举 → 默认 literal
    out2 = _apply_skill_implications(gap_items, ["Python", "LangGraph"], ["bogus", "bogus"])
    assert out2[0]["provenance"] == "literal"
    assert out2[0]["level"] == "已具备", "Python 按 literal 处理，LLM 判已具备保持"
    # 缺失（None）→ 全 literal
    out3 = _apply_skill_implications(gap_items, ["Python", "LangGraph"], None)
    assert out3[0]["provenance"] == "literal"
    # sources 含 None 元素（长度匹配但元素非法）→ 默认 literal
    out4 = _apply_skill_implications(gap_items, ["Python"], [None])
    assert out4[0]["provenance"] == "literal"


def test_apply_required_level_weights_partial_inferred_discount_within_core():
    """：同 core 档内 PARTIAL inferred 权重 < literal（推断技能打折）。"""
    gap_items = [
        _gap("SQL", level="已具备", required_level="core"),
        _gap("LLM API", level="部分具备", required_level="core"),
    ]
    gap_items[1]["provenance"] = "inferred"
    gap_items[1]["inferred_kind"] = "部分具备"
    out = _apply_required_level_weights(gap_items)
    assert out[1]["weight"] < out[0]["weight"], (
        f"同 core 档内 inferred {out[1]['weight']} 应 < literal {out[0]['weight']}"
    )
    total = sum(g["weight"] for g in out)
    assert 0.99 < total < 1.01


def test_apply_required_level_weights_partial_inferred_discount_within_nice():
    """：同 nice-to-have 档内 PARTIAL inferred 权重 < literal。"""
    gap_items = [
        _gap("Docker", level="已具备", required_level="nice-to-have"),
        _gap("Kafka", level="部分具备", required_level="nice-to-have"),
    ]
    gap_items[1]["provenance"] = "inferred"
    gap_items[1]["inferred_kind"] = "部分具备"
    out = _apply_required_level_weights(gap_items)
    assert out[1]["weight"] < out[0]["weight"]


def test_apply_required_level_weights_full_inferred_no_discount():
    """：FULL 蕴含 inferred（inferred_kind=已具备）与 literal 同权重，不降权。"""
    gap_items = [
        _gap("Python", level="已具备", required_level="core"),
        _gap("Java", level="已具备", required_level="core"),
    ]
    gap_items[1]["provenance"] = "inferred"
    gap_items[1]["inferred_kind"] = "已具备" # FULL 蕴含（如 spring→java）
    out = _apply_required_level_weights(gap_items)
    assert out[0]["weight"] == out[1]["weight"] == 0.5, "FULL inferred 不降权（与 literal 均分）"


def test_apply_required_level_weights_cross_tier_no_inversion_with_discount():
    """：跨档不反转——打折后任何 core 权重仍 > 任何 nice-to-have 权重（硬约束）。"""
    gap_items = [
        _gap("SQL", level="已具备", required_level="core"),
        _gap("LLM API", level="部分具备", required_level="core"),
        _gap("Docker", level="已具备", required_level="nice-to-have"),
        _gap("Kafka", level="部分具备", required_level="nice-to-have"),
    ]
    gap_items[1]["provenance"] = "inferred"
    gap_items[1]["inferred_kind"] = "部分具备"
    gap_items[3]["provenance"] = "inferred"
    gap_items[3]["inferred_kind"] = "部分具备"
    out = _apply_required_level_weights(gap_items)
    core_w = [g["weight"] for g in out if g["required_level"] == "core"]
    nice_w = [g["weight"] for g in out if g["required_level"] == "nice-to-have"]
    for c in core_w:
        for n in nice_w:
            assert c > n, f"core {c} 必须 > nice {n}（跨档不反转，打折仅同档内生效）"
    # 碰撞防御（round 后 core/nice 边界相等时强制降 nice）是 既有取舍，
    # 允许合计略偏离 1；跨档不反转才是本测试断言重点
    total = sum(g["weight"] for g in out)
    assert 0.9 < total < 1.1


async def test_executor_gap_items_carry_provenance_through_pipeline():
    """：executor_node 全链路——PARTIAL inferred 项带 provenance 且权重 < 同档 literal。"""
    fake = _FakeLLM([{
        "gap_items": [
            _gap("LLM API", level="不具备", required_level="core"),
            _gap("SQL", level="已具备", required_level="core"),
        ],
        "plan": _valid_plan(),
    }])
    state = _executor_state(profile={
        "name": "张三", "education": "本科", "major": "计算机",
        "skills": ["LangGraph", "SQL"],
        "skills_sources": ["literal", "literal"],
    })
    result = await executor_node(state, deps=AgentDeps(llm=fake))
    by_skill = {g["skill"]: g for g in result["gap_items"]}
    llm_api = by_skill["LLM API"]
    sql = by_skill["SQL"]
    assert llm_api["provenance"] == "inferred"
    assert llm_api["inferred_kind"] == "部分具备"
    assert sql["provenance"] == "literal"

    assert llm_api["weight"] < sql["weight"], "同 core 档内 PARTIAL inferred 权重应 < literal"


# ---------- ：多套 JD 聚合统计（job_post 薪资/技能/学历/职责综合） ----------


def _mk_market_hit(**overrides):
    """：构造 MarketHit（聚合单测用；source_type/薪资/学历/职责可用 override 覆盖）。"""
    from app.ai.rag.retriever import MarketHit

    base = dict(
        id="h1", city="北京", industry="互联网", job_title="后端开发工程师",
        salary_p25=15000, salary_p50=20000, salary_p75=25000, trend="稳定", heat="高",
        required_skills=["Java", "MySQL"], data_source="招聘平台JD", confidence=0.7,
        data_quarter="2026Q2", city_tier="一线", similarity=0.85, source_type="job_post",
        education_requirement="本科及以上", responsibilities=["负责后端服务开发"],
    )
    base.update(overrides)
    return MarketHit(**base)


def test_aggregate_multiple_job_post():
    """标准 2：多套 job_post 聚合——薪资 min/median/max、技能频次、学历众数、职责并集。"""
    from app.ai.agents.market import _jd_summary_from_hits

    hits = [
        _mk_market_hit(id="a", similarity=0.9, salary_p25=10000, salary_p50=18000, salary_p75=22000,
                       required_skills=["Java", "SQL"],
                       responsibilities=["负责后端服务开发", "参与架构设计"]),
        _mk_market_hit(id="b", similarity=0.8, salary_p25=12000, salary_p50=20000, salary_p75=28000,
                       required_skills=["Java", "Docker"],
                       responsibilities=["负责后端服务开发", "维护线上服务"]),
        _mk_market_hit(id="c", similarity=0.7, salary_p25=14000, salary_p50=22000, salary_p75=26000,
                       required_skills=["Python", "SQL"], education_requirement="硕士",
                       responsibilities=["负责后端服务开发"]),
    ]
    summary = _jd_summary_from_hits(hits, "后端开发工程师")
    assert summary["salary"] == {"p25": 10000.0, "p50": 20000.0, "p75": 28000.0}
    # 频次：Java=2/SQL=2/Docker=1/Python=1 → 同频次字典序 Java<SQL、Docker<Python
    assert [s["name"] for s in summary["required_skills"]] == ["Java", "SQL", "Docker", "Python"]
    assert [s["count"] for s in summary["required_skills"]] == [2, 2, 1, 1]
    assert all(s["required_level"] == "core" for s in summary["required_skills"])
    assert summary["education_requirement"] == "本科及以上" # 众数（本科x2 > 硕士x1）
    assert summary["responsibilities"] == ["负责后端服务开发", "参与架构设计", "维护线上服务"]
    assert summary["data_grade"] == "B"
    assert summary["skills_data_grade"] == "B"


def test_aggregate_single_hit_degrades_to_single():
    """标准 3：仅 1 条命中 → 退化为取单条（count=1、薪资=自身），不聚合不报错。"""
    from app.ai.agents.market import _jd_summary_from_hits

    hits = [_mk_market_hit(salary_p25=15000, salary_p50=20000, salary_p75=25000,
                           required_skills=["Java", "MySQL"])]
    summary = _jd_summary_from_hits(hits, "后端开发工程师")
    assert summary["salary"] == {"p25": 15000.0, "p50": 20000.0, "p75": 25000.0}
    assert [s["name"] for s in summary["required_skills"]] == ["Java", "MySQL"]
    assert all(s["count"] == 1 for s in summary["required_skills"])
    assert summary["education_requirement"] == "本科及以上"


def test_aggregate_mixed_source_type_salary_official_authoritative():
    """标准 1：混合 source_type——薪资取 official 分位为权威，技能/学历/职责取 job_post 聚合。"""
    from app.ai.agents.market import _jd_summary_from_hits

    hits = [
        _mk_market_hit(id="official", source_type="official_stat", similarity=0.88,
                       salary_p25=18000, salary_p50=24000, salary_p75=30000,
                       required_skills=[], education_requirement=None, responsibilities=[]),
        _mk_market_hit(id="p1", similarity=0.9, salary_p25=10000, salary_p50=15000, salary_p75=20000,
                       required_skills=["Java"]),
        _mk_market_hit(id="p2", similarity=0.8, salary_p25=12000, salary_p50=16000, salary_p75=22000,
                       required_skills=["Java", "SQL"]),
    ]
    summary = _jd_summary_from_hits(hits, "后端开发工程师")
    assert summary["salary"] == {"p25": 18000.0, "p50": 24000.0, "p75": 30000.0} # official 权威
    assert [s["name"] for s in summary["required_skills"]] == ["Java", "SQL"] # job_post 聚合（Java=2）
    assert summary["education_requirement"] == "本科及以上"
    assert summary["data_grade"] == "A" # 薪资权威=official_stat
    assert summary["skills_data_grade"] == "B" # 技能溯源=job_post


def test_aggregate_all_official_stat_keeps_skills_empty():
    """标准 4：全 official_stat（无技能/学历/职责）——薪资取分位、技能/学历/职责空，不编造。"""
    from app.ai.agents.market import _jd_summary_from_hits

    hits = [
        _mk_market_hit(id="o1", source_type="official_stat", similarity=0.9,
                       salary_p25=20000, salary_p50=26000, salary_p75=32000,
                       required_skills=[], education_requirement=None, responsibilities=[]),
        _mk_market_hit(id="o2", source_type="official_stat", similarity=0.7,
                       salary_p25=19000, salary_p50=25000, salary_p75=31000,
                       required_skills=[], education_requirement=None, responsibilities=[]),
    ]
    summary = _jd_summary_from_hits(hits, "后端开发工程师")
    assert summary["salary"] == {"p25": 20000.0, "p50": 26000.0, "p75": 32000.0} # 相似度最高 official
    assert summary["required_skills"] == []
    assert summary["education_requirement"] is None
    assert summary["responsibilities"] == []
    assert summary["skills_data_grade"] is None
    assert summary["data_grade"] == "A"


def test_aggregate_zero_hits_placeholder():
    """标准 4：0 命中 → 全 None/[] + summary_note 缺失提示（行为与现状一致）。"""
    from app.ai.agents.market import _jd_summary_from_hits

    summary = _jd_summary_from_hits([], "后端开发工程师")
    assert summary["salary"] is None
    assert summary["required_skills"] == []
    assert summary["education_requirement"] is None
    assert summary["responsibilities"] == []
    assert summary["summary_note"] == "未检索到该岗位市场数据，JD 要求摘要缺失"


def test_aggregate_multiple_official_exact_match_preferred():
    """标准 1：多条 official_stat——job_title 精确匹配 target_job 优先（相似度其次）。"""
    from app.ai.agents.market import _jd_summary_from_hits

    hits = [
        _mk_market_hit(id="o1", source_type="official_stat", job_title="高级后端开发工程师",
                       similarity=0.95, salary_p25=25000, salary_p50=30000, salary_p75=40000,
                       required_skills=[], education_requirement=None, responsibilities=[]),
        _mk_market_hit(id="o2", source_type="official_stat", job_title="后端开发工程师",
                       similarity=0.6, salary_p25=18000, salary_p50=24000, salary_p75=30000,
                       required_skills=[], education_requirement=None, responsibilities=[]),
    ]
    summary = _jd_summary_from_hits(hits, "后端开发工程师")
    # o2 精确匹配 target_job，即使相似度更低也优先
    assert summary["job_title"] == "后端开发工程师"
    assert summary["salary"] == {"p25": 18000.0, "p50": 24000.0, "p75": 30000.0}


def test_aggregate_education_mode_tie_prefers_highest_similarity():
    """标准 2：学历众数平局 → 取相似度最高命中。"""
    from app.ai.agents.market import _jd_summary_from_hits

    hits = [
        _mk_market_hit(id="a", similarity=0.9, education_requirement="本科"),
        _mk_market_hit(id="b", similarity=0.7, education_requirement="硕士"),
    ]
    summary = _jd_summary_from_hits(hits, "后端开发工程师")
    assert summary["education_requirement"] == "本科" # 平局 → 相似度最高（a）


def test_aggregate_skills_frequency_desc_then_lexicographic():
    """标准 2：required_skills 频次降序 + 同频次字典序稳定排序（固定输出可断言）。"""
    from app.ai.agents.market import _aggregate_skills

    hits = [
        _mk_market_hit(id="a", required_skills=["Redis", "Java"]),
        _mk_market_hit(id="b", required_skills=["Java", "Docker"]),
        _mk_market_hit(id="c", required_skills=["Redis"]),
    ]
    out = _aggregate_skills(hits)
    # Redis=2/Java=2/Docker=1 → 同频次字典序 Java<Redis；Docker 频次最低最后
    assert [s["name"] for s in out] == ["Java", "Redis", "Docker"]
    assert [s["count"] for s in out] == [2, 2, 1]


def test_direction_aggregates_education_responsibilities():
    """_jd_summary_from_direction：学历/职责以 job_post 聚合补充（多套合并），薪资/技能保持 LLM 输出。"""
    from app.ai.agents.market import _jd_summary_from_direction

    direction = {
        "job_title": "后端开发工程师",
        "salary": {"p25": 20000, "p50": 26000, "p75": 32000},
        "trend": "稳定", "heat": "高", "data_source": "公开招聘", "data_grade": "B",
        "education_requirement": None, # LLM 未给学历 → 回落聚合众数
    }
    hits = [
        _mk_market_hit(id="a", similarity=0.9, education_requirement="本科及以上",
                       responsibilities=["负责后端服务开发"]),
        _mk_market_hit(id="b", similarity=0.8, education_requirement="本科及以上",
                       responsibilities=["负责后端服务开发", "维护线上服务"]),
    ]
    summary = _jd_summary_from_direction(
        direction, "后端开发工程师", [{"name": "Java", "required_level": "core"}], hits=hits
    )
    assert summary["education_requirement"] == "本科及以上" # 聚合众数
    assert summary["responsibilities"] == ["负责后端服务开发", "维护线上服务"] # 并集去重
    assert summary["salary"] == {"p25": 20000, "p50": 26000, "p75": 32000} # LLM 薪资保持


def test_inject_gap_data_grade_prefers_skills_data_grade():
    """gap 项 data_grade 优先取 skills_data_grade（技能溯源=B），缺失回落 data_grade。"""
    from app.ai.agents.executor_agent import _inject_gap_data_grade

    gap_items = [_gap("Java")]
    out = _inject_gap_data_grade(gap_items, {"skills_data_grade": "B", "data_grade": "A"})
    assert out[0]["data_grade"] == "B"
    out2 = _inject_gap_data_grade(gap_items, {"data_grade": "A"})
    assert out2[0]["data_grade"] == "A"
    out3 = _inject_gap_data_grade(gap_items, {})
    assert "data_grade" not in out3[0]


async def test_aggregated_jd_summary_flows_through_executor_and_grounding():
    """聚合后 jd_summary 跑通 executor + grounding：LLM 消费 count 字段、jd_source 引用聚合技能原文，无幻觉/格式异常。"""
    from app.ai.grounding import audit_report_grounding

    jd_summary = {
        "job_title": "后端开发工程师", "city": "北京", "industry": "互联网",
        "education_requirement": "本科及以上", "responsibilities": ["负责后端服务开发"],
        "salary": {"p25": 10000.0, "p50": 20000.0, "p75": 28000.0},
        "trend": "稳定", "heat": "高",
        "required_skills": [
            {"name": "Java", "required_level": "core", "count": 3},
            {"name": "SQL", "required_level": "core", "count": 2},
        ],
        "data_source": "招聘平台JD", "data_grade": "B", "skills_data_grade": "B",
        "summary_note": "聚合 3 套公开招聘 JD（薪资区间合并、技能按频次、学历取众数、职责并集），来源可溯源",
    }
    fake = _FakeLLM([{"gap_items": [_gap("Java")], "plan": _valid_plan()}])
    state = _executor_state(
        target_job_requirements=[{"name": "Java", "required_level": "core"}],
        target_job_jd_summary=jd_summary,
    )
    result = await executor_node(state, deps=AgentDeps(llm=fake))
    assert result["plan"] is not None
    gap = result["gap_items"][0]
    assert gap["data_grade"] == "B" # skills_data_grade 优先
    assert gap["required_level"] == "core" # 权威分级注入
    # 走 grounding：聚合技能原文在依据池 → jd_source 映射通过，不误删
    report = {
        "gap_analysis": {"target_job": "后端开发工程师", "items": [gap]},
        "directions": [], "suggestion": None,
    }
    audited = audit_report_grounding(report, {
        "target_job_requirements": [{"name": "Java", "required_level": "core"}],
        "target_job_jd_summary": jd_summary,
    })
    kept = (audited.get("gap_analysis") or {}).get("items") or []
    assert len(kept) == 1
    assert kept[0]["jd_source_kind"] == "jd"
