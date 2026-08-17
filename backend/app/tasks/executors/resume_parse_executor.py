"""resume_parse 执行器（）：简历解析（Career Router 单节点）→ user_profiles；临时文件解析后即删（C-008）。"""
import logging
import os
import uuid

from app.ai.agents.deps import AgentDeps
from app.ai.agents.router import parse_vision_response, profile_from_vision, router_node
from app.ai.llm.client import get_llm_client, get_vision_client
from app.ai.llm.exceptions import LLMUnavailableError
from app.ai.persistence import upsert_resume_profile
from app.ai.schemas import initial_state
from app.db.base import AsyncSessionLocal
from app.tasks.executors.ai_base import (
    AIExecutor,
    classify_resume_file,
    extract_pdf_text,
    image_to_data_uri,
    pdf_to_data_uris,
)
from app.tasks.executors.registry import ExecutorRegistry

logger = logging.getLogger("careerai.ai.executors.resume_parse")

# 视觉结构化提取 Prompt（OCR 原文 + 结构化字段；ocr_text 是技能 grounding 的依据）
_VISION_SYSTEM_PROMPT = (
    "你是简历 OCR 与结构化提取引擎。对给定简历图片（可能为扫描件或复杂排版），"
    "输出一个纯 JSON 对象，不要输出任何其他文字、不要 markdown 围栏。"
)
_VISION_USER_PROMPT = (
    "请提取简历图片内容，输出如下 JSON（字段缺失填 null 或 []，禁止编造）：\n"
    '{"ocr_text":"按原文排版逐行转录的图片全部文字（不要遗漏、不要改写）",'
    '"name":"姓名或 null","school":"学校或 null","major":"专业或 null",'
    '"education":"学历（本科/硕士/博士/大专）或 null","graduation_year":"毕业年份或 null",'
    '"gpa":"GPA 或 null","skills":["技能1","技能2"],'
    '"internships":[{"company":"公司","role":"岗位","duration":"时间段"}],'
    '"projects":[{"name":"项目名","description":"描述","tech":["技术1","技术2"]}],'
    '"certificates":["证书"]}\n'
    "规则：ocr_text 必须逐行完整转录图片全部文字（作为技能溯源依据）；"
    "projects[].tech 必须是字符串数组；skills/internships/certificates 必须是数组；"
    "只提取图片中明确存在的信息，缺失填 null 或 []。"
)


async def _extract_vision(file_path: str, suffix: str, vision=None) -> tuple[str, dict]:
    """图片/扫描 PDF → GLM-4.6V-Flash → (OCR 原文, 结构化 dict)。异常由调用方统一 mark_failed。

    - vision 可注入（单测 mock）；默认 get_vision_client()；
    - GLM 未配置 → LLMUnavailableError；视觉返回非法结构 → LLMFormatError（parse_vision_response 抛）。
    """
    vision = vision or get_vision_client()
    if not vision.is_available:
        raise LLMUnavailableError("GLM_API_KEY 未配置，无法解析图片/扫描件简历")
    images = pdf_to_data_uris(file_path) if suffix == ".pdf" else [image_to_data_uri(file_path)]
    text = await vision.complete_vision(
        _VISION_SYSTEM_PROMPT, _VISION_USER_PROMPT, images, node_name="resume_vision"
    )
    return parse_vision_response(text)


class ResumeParseExecutor(AIExecutor):
    task_type = "resume_parse"

    async def execute(self, job_id: str, params: dict) -> None:
        # 参数解析补 try/except——uuid.UUID("") 抛 ValueError，安全失败不崩溃
        # （不再依赖 worker 层兜底，错误信息明确落到 error_message）。
        try:
            user_id = uuid.UUID(params.get("user_id") or "")
        except (TypeError, ValueError):
            async with AsyncSessionLocal() as session:
                await self._mark_failed(session, job_id, "参数缺失或非法（user_id）")
            return
        file_path = params.get("file_path")
        raw_text = params.get("raw_text") or ""
        temp_path = None

        # 越权锚点（唯一可信 = job.user_id）：params.user_id 必须等于任务归属用户，
        # 防经 trigger 端点传他人 user_id 覆写受害者画像（IDOR）；不符 → mark_failed，
        # 不执行、不落库；传入的临时文件一并清理（C-008 防御）。
        async with AsyncSessionLocal() as session:
            job = await self._get_job(session, job_id)
            if job is None or job.user_id is None or user_id != job.user_id:
                await self._mark_failed(session, job_id, "无权执行该任务")
                if file_path:
                    try:
                        os.remove(file_path)
                    except OSError:
                        logger.warning("resume_parse: 越权拒绝清理临时文件失败 %s", file_path)
                return

        # 分流提取（：图片/扫描件 → GLM 视觉；文本型 PDF → 原链路；临时文件解析后即删 C-008）
        mode = "text"
        vision_raw: dict | None = None
        try:
            if file_path:
                temp_path = file_path
                suffix = os.path.splitext(file_path)[1].lower()
                if suffix == ".pdf":
                    raw_text = extract_pdf_text(file_path)
                    mode = classify_resume_file(suffix, raw_text)
                else:
                    mode = classify_resume_file(suffix, "")
                if mode == "vision":
                    raw_text, vision_raw = await _extract_vision(file_path, suffix)
        except Exception as exc: # noqa: BLE001 解析失败 → 任务失败（前端引导手动补填）
            logger.exception("resume_parse: 简历解析失败")
            async with AsyncSessionLocal() as session:
                if mode == "vision":
                    msg = "简历解析失败：图片/扫描件视觉识别未成功，请手动补填画像"
                else:
                    msg = f"简历解析失败：{type(exc).__name__}"
                await self._mark_failed(session, job_id, msg)
            return
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    logger.warning("resume_parse: 临时文件删除失败 %s", temp_path)

        async with AsyncSessionLocal() as session:
            if not await self._update_progress(session, job_id, 20, "解析简历"):
                return
            deps = AgentDeps(llm=get_llm_client())
            if mode == "vision":
                profile = profile_from_vision(vision_raw, raw_text)
                state = initial_state(profile=profile, profile_raw=raw_text, user_id=str(user_id))
            else:
                state = initial_state(profile_raw=raw_text, user_id=str(user_id))
            try:
                result = await router_node(state, deps)
            except Exception as exc: # noqa: BLE001
                logger.exception("resume_parse: 解析节点失败")
                await self._mark_failed(session, job_id, f"简历解析失败：{type(exc).__name__}")
                return
            profile = result.get("profile") or {}
            if not await self._update_progress(session, job_id, 50, "结构化画像"):
                return
            if await self._is_cancelled(session, job_id):
                return # 取消不落库（决策③）
            row = await upsert_resume_profile(session, user_id, profile)
            await session.commit()
            if not await self._update_progress(session, job_id, 100, "保存画像"):
                return
            await self._mark_succeeded(
                session,
                job_id,
                result={
                    "profile_id": str(row.id),
                    "profile_complete": bool(result.get("profile_complete")),
                    "generated_by": profile.get("generated_by", "llm_or_rule"),
                },
                result_ref="/api/v1/profile", # OA-001：GET /profile/{id} 不存在，前端走 GET /profile
            )


ExecutorRegistry.register(ResumeParseExecutor())
