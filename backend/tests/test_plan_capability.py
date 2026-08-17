"""报告生成质量优化测试：why 去重/阶段差异化 + executor prompt 技术栈时效与长期求职任务。"""
from pathlib import Path

from app.ai.agents.deps import AgentDeps
from app.ai.agents.executor_agent import _normalize_plan_tasks, executor_node
from app.ai.fallback.plan_capability import stage_capability_fields
from app.ai.schemas import initial_state

BACKEND_DIR = Path(__file__).resolve().parents[1]
EXECUTOR_MD = BACKEND_DIR / "app" / "ai" / "prompts" / "executor.md"

_GAP_ITEMS = [
    {"skill": "Redis", "jd_source": "JD 要求：熟练使用 Redis 缓存", "level": "不具备"},
    {"skill": "微服务", "jd_source": "JD 要求：掌握微服务架构", "level": "不具备"},
    {"skill": "Copilot", "jd_source": "JD 要求：使用 AI 编程助手", "level": "不具备"},
]
_TASKS = [
    {"name": "系统学习 Redis 缓存基础", "stage": "short"},
    {"name": "用 Spring Cloud Alibaba 搭建微服务项目", "stage": "mid"},
    {"name": "用 Copilot 提升开发效率", "stage": "long"},
]
_TARGET_JOB = "后端开发工程师"


def _why(stage: str) -> str:
    return stage_capability_fields(stage, _TASKS, _TARGET_JOB, _GAP_ITEMS)["why"]


def test_why_no_jd_prefix_duplication():
    for stage in ("short", "mid", "long"):
        why = _why(stage)
        assert "JD 要求：JD 要求：" not in why, f"{stage} why 出现「JD 要求：JD 要求：」重复：{why}"
        assert "目标岗位 JD 要求：JD 要求：" not in why


def test_why_differentiated_across_stages():
    whys = {stage: _why(stage) for stage in ("short", "mid", "long")}
    assert len(set(whys.values())) == 3, f"三阶段 why 未差异化：{whys}"


def test_short_why_points_to_stage_skill():
    why = _why("short")
    assert "Redis" in why, f"short why 未指向该阶段技能缺口：{why}"


def test_mid_why_points_to_deepening():
    why = _why("mid")
    assert "微服务" in why and "工程化" in why, f"mid why 未指向深化方向：{why}"


def test_long_why_points_to_delivery_standard():
    why = _why("long")
    assert "投递标准" in why and "求职准备" in why, f"long why 未指向投递标准：{why}"


def test_executor_prompt_forbids_deprecated_stack():
    prompt = EXECUTOR_MD.read_text(encoding="utf-8")
    assert "Eureka" in prompt and "Zuul" in prompt, "executor.md 未提及 Eureka/Zuul 禁令"
    assert "禁止" in prompt and "过时" in prompt, "executor.md 缺少禁止过时技术栈约束"
    assert "Nacos" in prompt and "Gateway" in prompt, "executor.md 缺少主流替代（Nacos/Gateway）"


def test_executor_prompt_requires_long_job_prep():
    prompt = EXECUTOR_MD.read_text(encoding="utf-8")
    assert "简历优化" in prompt, "executor.md 缺少长期简历优化任务约束"
    assert "模拟面试" in prompt, "executor.md 缺少长期模拟面试任务约束"
    assert "岗位投递" in prompt, "executor.md 缺少长期岗位投递任务约束"


# ---------- 复验补修：long 阶段求职准备任务确定性补齐 ----------


def _llm_plan_without_long_job_prep() -> dict:
    """模拟真实 LLM 输出：long 阶段只有纯技术任务，缺求职准备。"""
    return {
        "tasks": [
            {
                "name": "完成 AI 工具集成项目（使用 OpenAI API 实现智能商品推荐）",
                "resource": "OpenAI API 文档 + 示例项目",
                "duration": "1 个月",
                "stage": "long",
                "acceptance_criteria": "项目可运行并演示",
            }
        ]
    }


_GAP_AI = [{"skill": "AI 工具集成", "jd_source": "JD 要求：使用 AI 编程助手", "level": "不具备"}]


def test_normalize_plan_tasks_appends_long_job_prep_when_missing():
    """LLM 生成的 long 任务缺求职准备时，_normalize_plan_tasks 确定性补齐。"""
    result = _normalize_plan_tasks(_llm_plan_without_long_job_prep(), _GAP_AI, "后端开发工程师", None)
    long_tasks = [t for t in result["tasks"] if t.get("stage") == "long"]
    names = " ".join(t["name"] for t in long_tasks)
    assert "简历" in names, f"long 任务未补齐简历优化：{names}"
    assert "面试" in names, f"long 任务未补齐模拟面试：{names}"
    assert "投递" in names, f"long 任务未补齐岗位投递：{names}"
    assert len(long_tasks) == 2


def test_normalize_plan_tasks_does_not_duplicate_long_job_prep():
    """long 任务已含求职准备时，不重复追加。"""
    plan = {
        "tasks": [
            {
                "name": "模拟面试 + 岗位投递准备",
                "resource": "牛客网面经",
                "duration": "1 个月",
                "stage": "long",
                "acceptance_criteria": "完成 3 场模拟面试并复盘",
            }
        ]
    }
    result = _normalize_plan_tasks(plan, _GAP_AI, "后端开发工程师", None)
    assert len(result["tasks"]) == 1


class _FakeLLM:
    """is_available=True 且返回「long 缺求职准备」计划的 mock（模拟真实 LLM 路径）。"""

    is_available = True

    async def complete_json(self, **kwargs):
        return {"gap_items": _GAP_AI, "plan": _llm_plan_without_long_job_prep()}


async def test_executor_node_appends_long_job_prep_when_llm_omits():
    """端到端：LLM 路径生成的 long 任务缺求职准备 → executor_node 确定性补齐。"""
    state = initial_state(
        profile={"name": "张三", "skills": ["Python"]},
        target_job="后端开发工程师",
        target_job_requirements=["AI 工具集成"],
        stage="stage2",
    )
    deps = AgentDeps(llm=_FakeLLM())
    result = await executor_node(state, deps)
    long_tasks = [t for t in result["plan"]["tasks"] if t.get("stage") == "long"]
    names = " ".join(t["name"] for t in long_tasks)
    assert "简历" in names and "面试" in names and "投递" in names
