"""reports 业务编排：Stage1 提交/列表/详情 + Stage2（gap）/计划重生成（异步任务触发）。"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ApiError, ErrorCode
from app.models import User
from app.repositories.profile_repository import ProfileRepository
from app.repositories.report_repository import ReportRepository
from app.repositories.task_job_repository import TaskJobRepository
from app.schemas.reports import (
    GapRequest,
    ReportCreateRequest,
    ReportDetailOut,
    ReportDirectionOut,
    ReportListItemOut,
)
from app.schemas.task import TaskTriggerResult
from app.services.audit_service import AuditService
from app.services.error_codes import ReportErrorCode
from app.services.task_service import TaskService


class ReportService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.report_repo = ReportRepository(session)
        self.profile_repo = ProfileRepository(session)
        self.job_repo = TaskJobRepository(session)

    async def create_report(self, user: User, req: ReportCreateRequest) -> TaskTriggerResult:
        """POST /reports：C-002 门槛 + 日配额 + Stage1 串行 → report_stage1 任务。"""
        cities = req.preferred_cities or []
        industries = req.preferred_industries or []
        if len(cities) > 5:
            raise ApiError(ErrorCode.INVALID_PARAM, "意向城市最多 5 个", 400)
        if len(industries) > 5:
            raise ApiError(ErrorCode.INVALID_PARAM, "意向行业最多 5 个", 400)

        profile = await self.profile_repo.get_by_id_and_user(req.profile_id, user.id)
        if profile is None:
            raise ApiError(ReportErrorCode.PROFILE_NOT_FOUND, "用户画像不存在", 404)

        missing = self._check_c002_minimum(profile)
        if missing:
            raise ApiError(
                ReportErrorCode.REPORT_PROFILE_INCOMPLETE,
                f"用户画像信息不完整，缺少{'、'.join(missing)}",
                400,
            )

        limit = get_settings().AI_DAILY_REPORT_LIMIT
        if await self.report_repo.count_completed_today(user.id) >= limit:
            raise ApiError(
                ReportErrorCode.REPORT_QUOTA_EXCEEDED,
                f"当日报告生成次数已超限（{limit} 次/天）",
                429,
            )

        if await self.job_repo.has_processing(user.id, "report_stage1"):
            raise ApiError(ReportErrorCode.REPORT_STAGE_CONFLICT, "已有进行中的报告生成任务", 409)

        task_service = TaskService(self.session)
        job = await task_service.create_and_dispatch(
            user,
            "report_stage1",
            {
                "user_id": str(user.id),
                "profile_id": str(req.profile_id),
                "preferred_cities": cities,
                "preferred_industries": industries,
            },
        )
        return TaskTriggerResult(task_id=job.id, status=job.status)

    async def list_reports(self, user: User, page: int, page_size: int) -> dict:
        """我的报告列表：已完成报告 + 生成中任务（task_jobs pending/running）。

        / 单一事实源：score/job_titles/target_job 主读 result JSONB
        （写路径同一 dict 落库，读取不再跨 store 调停——删除 career_directions 表读取与
        job_title 去重/择优/grade 比较）；target_job 仅对存量缺口回退 gap_analyses 表
        （null 填充，权威值，非调停，见实现注释）。

        - 生成中条目排前（通常 0-1 条：C-004 同一用户仅一个 processing Stage1；
          Stage2/plan 仅对已完成报告触发，与 Stage1 互斥）。
        - 进行中条目 id 为 task_id（报告行尚未落库），前端可经 GET /tasks/{id} 轮询续接（Q5）。
        - 分页：total 含进行中任务；进行中条目恒在第一页顶部，后续页仅含已完成报告。
        """
        total, rows = await self.report_repo.list_by_user(user.id, page, page_size)
        jobs = await self.report_repo.list_processing_report_jobs(user.id)
        processing_items = [
            ReportListItemOut(
                id=job.id,
                stage=_stage_of(job.task_type),
                status=job.status,
                score=None,
                summary={"job_titles": [], "target_job": None},
                created_at=job.created_at,
            )
            for job in jobs
        ]
        report_items = [
            ReportListItemOut(
                id=row.id,
                stage=row.stage,
                status=row.status,
                score=((row.result or {}).get("portrait") or {}).get("overall_score"),
                summary={
                    "job_titles": _jsonb_job_titles(row.result),
                    "target_job": _jsonb_target_job(row.result),
                },
                created_at=row.created_at,
            )
            for row in rows
        ]
        # 存量兜底（非调停）：target_job 主读 JSONB（新报告写路径已确定性注入）；
        # 仅当存量报告 JSONB gap_analysis 缺 target_job（LLM 路径历史报告）时，回退
        # gap_analyses 表权威值（用户 Stage2 实际所选）——null 填充，不做去重/择优/grade 比较。
        if any(item.summary["target_job"] is None for item in report_items):
            fallback_map = await self.report_repo.get_target_jobs_by_report_ids([r.id for r in rows])
            for item in report_items:
                if item.summary["target_job"] is None:
                    item.summary["target_job"] = fallback_map.get(item.id)
        return {
            "total": total + len(jobs),
            "page": page,
            "page_size": page_size,
            "items": processing_items + report_items,
        }

    async def get_report(self, user: User, report_id: uuid.UUID) -> ReportDetailOut:
        """报告详情（/ 单一事实源：读取只消费 result JSONB，不再跨存储调停）。

        - directions 内容（job_title/match_score/salary/trend/heat/data_source/education_*/
          competition_note/certificates_bonus/recommend_reason/data_grade/confidence_reasons）
          全部来自 result JSONB（写路径同一 dict 落库 JSONB + career_directions 表）；
          career_directions 表仅承担方向 id 身份锚点（读时合成，与 plan.id 注入 QA-BUG-018 同类，
          标准 1c 排除在读往返断言外）。
        - 删除 QA-BUG-004 旧跨存储调停：_best_directions_by_title/_direction_better/_grade_rank
          （job_title 去重/match_score 择优/data_grade 优先级比较）——写路径已去重，读取不再调停。
        - plan.id 注入保留（QA-BUG-018/，读时合成身份字段）。
        """
        report = await self.report_repo.get_owned(report_id, user.id)
        if report is None:
            raise ApiError(ReportErrorCode.REPORT_NOT_FOUND, "报告不存在", 404)
        result = report.result or {}

        # 方向 id 身份锚点（career_directions 表按 job_title 映射，读时合成）
        directions = await self.report_repo.get_directions(report_id)
        id_by_title: dict[str, uuid.UUID] = {}
        for row in directions:
            title = str(row.job_title or "").strip()
            if title and title not in id_by_title:
                id_by_title[title] = row.id

        # JSONB 为方向内容单一事实源（写路径已按 job_title 去重，读取直通）
        merged: list[ReportDirectionOut] = []
        for d in result.get("directions") or []:
            if not isinstance(d, dict):
                continue
            title = str(d.get("job_title") or "").strip()
            if not title:
                continue
            salary = d.get("salary") if isinstance(d.get("salary"), dict) else None
            salary_comparison = (
                d.get("salary_comparison") if isinstance(d.get("salary_comparison"), dict) else None
            )
            merged.append(
                ReportDirectionOut(
                    id=id_by_title.get(title),
                    job_title=title,
                    match_score=int(d.get("match_score") or 0),
                    salary=salary,
                    salary_note=d.get("salary_note"),
                    trend=d.get("trend"),
                    heat=d.get("heat"),
                    data_source=d.get("data_source"),
                    education_requirement=d.get("education_requirement"),
                    education_match=d.get("education_match"),
                    competition_note=d.get("competition_note"),
                    certificates_bonus=d.get("certificates_bonus"),
                    recommend_reason=d.get("recommend_reason"),
                    data_grade=d.get("data_grade"),
                    confidence_reasons=d.get("confidence_reasons"),
                    salary_comparison=salary_comparison,
                )
            )
        # QA-BUG-018：plan 注入计划记录 id（查 growth_plans 按 report_id），
        # 前端 detail.plan?.id 可定位计划明细；无计划记录时保持现状（plan 为 AI 摘要 dict）。
        plan = result.get("plan")
        plan_row = await self.report_repo.get_plan_by_report_id(report_id)
        if plan_row is not None:
            plan = {**(plan or {}), "id": plan_row.id}
        return ReportDetailOut(
            id=report.id,
            stage=report.stage,
            status=report.status,
            portrait=result.get("portrait"),
            directions=merged,
            gap_analysis=result.get("gap_analysis"),
            plan=plan,
            suggestion=result.get("suggestion"), # v1.1：AI 策略建议（仅 Stage 2 完整报告，否则 null）
            created_at=report.created_at,
            finished_at=report.finished_at,
        )

    async def create_gap_analysis(
        self, user: User, report_id: uuid.UUID, req: GapRequest
    ) -> TaskTriggerResult:
        """POST /reports/{id}/gap：direction 校验 + Stage2 串行 → report_stage2 任务。"""
        if req.direction_id is None:
            raise ApiError(ReportErrorCode.DIRECTION_REQUIRED, "缺少 direction_id", 400)
        report = await self.report_repo.get_owned(report_id, user.id)
        if report is None:
            raise ApiError(ReportErrorCode.REPORT_NOT_FOUND, "报告不存在", 404)
        direction = await self.report_repo.get_direction(report_id, req.direction_id)
        if direction is None:
            raise ApiError(ReportErrorCode.DIRECTION_NOT_FOUND, "目标方向不存在", 404)
        if await self.job_repo.has_processing(user.id, "report_stage2"):
            raise ApiError(ReportErrorCode.REPORT_STAGE_CONFLICT, "该报告已有进行中的 Stage 2 任务", 409)

        task_service = TaskService(self.session)
        job = await task_service.create_and_dispatch(
            user,
            "report_stage2",
            {
                "user_id": str(user.id),
                "report_id": str(report_id),
                "direction_id": str(req.direction_id),
            },
        )
        return TaskTriggerResult(task_id=job.id, status=job.status)

    async def regenerate_plan(self, user: User, report_id: uuid.UUID):
        """POST /reports/{id}/plan（关键操作）：REQUIRE_CONFIRMATION=true 时延迟确认。"""
        payload = {"report_id": str(report_id)}
        if get_settings().REQUIRE_CONFIRMATION:
            return await AuditService(self.session).defer(
                user, "regenerate_plan", "report", str(report_id), payload
            )
        result = await self._regenerate_plan(user, report_id)
        await AuditService(self.session).record_auto_approved(
            user, "regenerate_plan", "report", str(report_id), payload
        )
        return result

    async def _regenerate_plan(self, user: User, report_id: uuid.UUID) -> TaskTriggerResult:
        """计划重生成内部实现（不含审计包装，供批准重放）。"""
        report = await self.report_repo.get_owned(report_id, user.id)
        if report is None:
            raise ApiError(ReportErrorCode.REPORT_NOT_FOUND, "报告不存在", 404)
        if not await self.report_repo.has_gap_analysis(report_id):
            raise ApiError(
                ReportErrorCode.PLAN_REGEN_NOT_ALLOWED,
                "该报告尚未完成差距分析，无法重新生成计划",
                400,
            )
        if await self.job_repo.has_processing(user.id, "plan_regenerate"):
            raise ApiError(ReportErrorCode.REPORT_STAGE_CONFLICT, "已有进行中的计划重生成任务", 409)

        task_service = TaskService(self.session)
        job = await task_service.create_and_dispatch(
            user,
            "plan_regenerate",
            {"user_id": str(user.id), "report_id": str(report_id)},
        )
        return TaskTriggerResult(task_id=job.id, status=job.status)

    @staticmethod
    def _check_c002_minimum(profile) -> list[str]:
        """C-002 最低信息门槛：姓名、学历、专业、毕业年份 + ≥1 段实习/项目。"""
        missing: list[str] = []
        if not profile.name:
            missing.append("姓名")
        if not profile.education:
            missing.append("学历")
        if not profile.major:
            missing.append("专业")
        if not profile.graduation_year:
            missing.append("毕业年份")
        if not (profile.internships or profile.projects):
            missing.append("至少一段实习/项目经历")
        return missing



def _jsonb_job_titles(result: dict | None) -> list[str]:
    """列表摘要 job_titles：result JSONB directions 的 job_title（单一事实源）。"""
    out: list[str] = []
    for d in (result or {}).get("directions") or []:
        if isinstance(d, dict) and str(d.get("job_title") or "").strip():
            out.append(str(d["job_title"]))
    return out


def _jsonb_target_job(result: dict | None) -> str | None:
    """列表摘要 target_job：result JSONB gap_analysis.target_job（单一事实源）。

     语义保留：target_job 为用户 Stage2 实际所选（direction.job_title），
    save_stage2_result 写路径已将该值注入 JSONB gap_analysis（LLM/规则双路径均覆盖）。
    """
    gap = (result or {}).get("gap_analysis")
    if isinstance(gap, dict):
        value = str(gap.get("target_job") or "").strip()
        return value or None
    return None

def _stage_of(task_type: str) -> str:
    """报告类任务 → 列表 stage 语义（stage1 生成 / stage2 差距+计划一体）。"""
    if task_type == "report_stage1":
        return "stage1"
    return "stage2" # report_stage2 / plan_regenerate


