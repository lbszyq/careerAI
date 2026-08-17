"""AI 业务落库（architecture.md / 决策③：报告/方向/差距/计划仅在任务成功时创建）。

- 执行器在保存步骤前必须复核任务未被取消（cancelled → 不落库）。
- 表结构引用 已落地模型；norm_benchmarks 由 提供（本模块不涉及）。
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.fallback.resume_parser import normalize_internships, normalize_projects
from app.ai.guard.guards import sanitize_structured_output
from app.models.plan import GrowthPlan, PlanTask
from app.models.profile import UserProfile
from app.models.report import CareerDirection, CareerReport, GapAnalysis

logger = logging.getLogger("careerai.ai.persistence")


async def upsert_resume_profile(
    session: AsyncSession, user_id: uuid.UUID, profile: dict
) -> UserProfile:
    """resume_parse：解析结果写入 user_profiles（upsert 活跃档案，C-001 单活跃）。"""
    profile = sanitize_structured_output(profile, context="resume_parse_profile")
    # QA-BUG-005 结构防御：internships/projects 归一为 list[dict]，避免与 ProfileOut 契约冲突
    profile["internships"] = normalize_internships(profile.get("internships"))
    profile["projects"] = normalize_projects(profile.get("projects"))
    from sqlalchemy import select

    stmt = select(UserProfile).where(
        UserProfile.user_id == user_id, UserProfile.is_active.is_(True)
    )
    existing = (await session.execute(stmt)).scalars().first()
    data = {
        "name": profile.get("name"),
        "school": profile.get("school"),
        "major": profile.get("major"),
        "education": profile.get("education"),
        "gpa": profile.get("gpa"),
        "graduation_year": _to_int(profile.get("graduation_year")),
        "skills": profile.get("skills") or [],
        "skills_sources": profile.get("skills_sources") or [], # provenance 随画像落库
        "internships": profile.get("internships") or [],
        "projects": profile.get("projects") or [],
        "certificates": profile.get("certificates") or [],
        "is_active": True,
    }
    # 用户偏好字段：简历解析通常无来源，仅当解析输出显式包含时写入，
    # 避免覆盖用户通过表单（PUT /profile）已填写的偏好。
    if "preferred_cities" in profile:
        data["preferred_cities"] = profile["preferred_cities"] or []
    if "preferred_industries" in profile:
        data["preferred_industries"] = profile["preferred_industries"] or []
    if "expected_salary" in profile:
        data["expected_salary"] = _to_float(profile["expected_salary"])
    if existing is not None:
        for key, value in data.items():
            setattr(existing, key, value)
        await session.flush()
        return existing
    row = UserProfile(user_id=user_id, **data)
    session.add(row)
    await session.flush()
    return row


async def save_stage1_result(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    profile_id: uuid.UUID | None,
    report: dict,
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Stage 1 成功：career_reports(status=completed) + career_directions。"""
    report = sanitize_structured_output(report, context="report_stage1")
    report_row = CareerReport(
        user_id=user_id,
        profile_id=profile_id,
        status="completed",
        stage="stage1",
        result=report,
        finished_at=datetime.now(timezone.utc),
    )
    session.add(report_row)
    await session.flush()

    direction_ids: list[uuid.UUID] = []
    for idx, d in enumerate(report.get("directions") or []):
        direction_row = CareerDirection(
            report_id=report_row.id,
            job_title=d.get("job_title") or "未知岗位",
            match_score=int(d.get("match_score") or 0),
            salary_p25=_to_float(_nested_salary(d, "p25")),
            salary_p50=_to_float(_nested_salary(d, "p50")),
            salary_p75=_to_float(_nested_salary(d, "p75")),
            trend=d.get("trend"),
            heat=d.get("heat"),
        )
        session.add(direction_row)
        await session.flush()
        direction_ids.append(direction_row.id)
    return report_row.id, direction_ids


async def save_stage2_result(
    session: AsyncSession,
    *,
    report_id: uuid.UUID,
    direction_id: uuid.UUID | None,
    target_job: str,
    report: dict,
    confidence: dict | None = None,
) -> uuid.UUID:
    """Stage 2 成功：gap_analyses + growth_plans + plan_tasks；报告 stage 置 stage2。

    confidence：GraphState.confidence 透传（QA-BUG-017 契约根治）——gap_analysis
    落库补 confidence（来源=executor 输出，禁止编造；无来源时不写）。
    """
    report = sanitize_structured_output(report, context="report_stage2")
    # QA-BUG-017：gap_analysis 补 confidence（reports-contract 定义但此前未落库）。
    # 来源=GraphState.confidence.executor（高/中/低），确定性注入；无来源时不编造。
    gap_analysis = report.get("gap_analysis")
    if isinstance(gap_analysis, dict):
        executor_confidence = (confidence or {}).get("executor")
        if executor_confidence is not None:
            gap_analysis["confidence"] = executor_confidence
    gap_items = (report.get("gap_analysis") or {}).get("items") or report.get("gap_items") or []
    gap_row = GapAnalysis(
        report_id=report_id,
        direction_id=direction_id,
        target_job=target_job,
        items=gap_items,
    )
    session.add(gap_row)
    await session.flush()

    plan_payload = report.get("plan") or {}
    plan_row = GrowthPlan(
        report_id=report_id,
        gap_analysis_id=gap_row.id,
        stages=plan_payload.get("stages"),
        progress=0,
    )
    session.add(plan_row)
    await session.flush()

    for idx, task in enumerate(plan_payload.get("tasks") or []):
        session.add(
            PlanTask(
                plan_id=plan_row.id,
                name=task.get("name") or "未命名任务",
                resource=task.get("resource"),
                duration=task.get("duration"),
                stage=task.get("stage"),
                status="todo",
                sort_order=int(task.get("sort_order") or (idx + 1)),
            )
        )

    report_row = await session.get(CareerReport, report_id)
    if report_row is not None:
        report_row.stage = "stage2"
        # QA-BUG-013：Stage2 是增量叠加（reports-contract 报告详情），整体覆盖会丢失
        # Stage1 的 portrait/directions（Stage2 图无 career_analysis 节点，report 不含画像）。
        # 合并：Stage2 字段叠加到 Stage1，portrait/directions 以 Stage1 为准。
        stage1_result = report_row.result or {}
        merged = {**stage1_result, **report}
        merged["portrait"] = stage1_result.get("portrait") or report.get("portrait")
        merged["directions"] = stage1_result.get("directions") or report.get("directions")
        # /（单一事实源）：gap_analysis.target_job 确定性注入 JSONB——
        # 以调用方传入的 target_job（= 用户 Stage2 实际所选 direction.job_title）
        # 为准，LLM/规则双路径均覆盖，保证 list_reports 的 target_job 可全量从 JSONB 读取，
        # 不再跨 store 查 gap_analyses 表。
        merged_gap = merged.get("gap_analysis")
        if isinstance(merged_gap, dict):
            merged_gap["target_job"] = target_job
        report_row.result = merged # 报告详情 gap/plan 可查（reports-contract）
    await session.flush()
    return plan_row.id


async def update_plan(
    session: AsyncSession,
    *,
    plan_id: uuid.UUID,
    report: dict,
) -> None:
    """plan_regenerate：更新 growth_plans.stages + 替换 plan_tasks（保留计划行）。"""
    report = sanitize_structured_output(report, context="plan_regenerate")
    plan_row = await session.get(GrowthPlan, plan_id)
    if plan_row is None:
        raise ValueError(f"growth_plan 不存在: {plan_id}")
    plan_payload = report.get("plan") or {}
    tasks = plan_payload.get("tasks") or []
    if not tasks:
        # 空 plan 防御：plan 无 tasks 时保留旧任务/旧 stages/旧报告 plan，
        # 不删不插（幂等），杜绝「重新生成」用空 plan 清空计划（用户走查缺陷）。
        logger.warning("update_plan: plan 无 tasks，跳过更新（保留旧任务，plan_id=%s）", plan_id)
        return
    plan_row.stages = plan_payload.get("stages")
    # 替换任务为最新
    from sqlalchemy import delete

    await session.execute(delete(PlanTask).where(PlanTask.plan_id == plan_id))
    for idx, task in enumerate(plan_payload.get("tasks") or []):
        session.add(
            PlanTask(
                plan_id=plan_id,
                name=task.get("name") or "未命名任务",
                resource=task.get("resource"),
                duration=task.get("duration"),
                stage=task.get("stage"),
                status="todo",
                sort_order=int(task.get("sort_order") or (idx + 1)),
            )
        )
    # v1.1：plan_regenerate 后同步报告 result.plan/suggestion，
    # 保证报告详情与计划详情一致（任务级 acceptance_criteria 从 result.plan.tasks 透传）。
    report_row = await session.get(CareerReport, plan_row.report_id)
    if report_row is not None:
        merged = dict(report_row.result or {})
        merged["plan"] = plan_payload
        if report.get("suggestion") is not None:
            merged["suggestion"] = report.get("suggestion")
        report_row.result = merged
    await session.flush()


def _nested_salary(direction: dict, key: str) -> float | None:
    salary = direction.get("salary")
    if isinstance(salary, dict):
        return _to_float(salary.get(key))
    return None


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value) -> int | None:
    """毕业年份容错：LLM 偶发输出数字字符串（如 "2026"）时也能正确落库。"""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
