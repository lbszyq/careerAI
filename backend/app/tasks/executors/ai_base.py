"""AI 执行器公共基类：任务加载 / 取消检测 / 失败标记 / PDF 文本提取。"""
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TaskJob
from app.repositories.task_job_repository import TaskJobRepository
from app.tasks.executors.base import TaskExecutor

logger = logging.getLogger("careerai.ai.executors")


class AIExecutor(TaskExecutor):
    """AI 执行器基类：与 task_jobs 状态机对齐（pending→running→succeeded/failed/cancelled）。"""

    @staticmethod
    async def _get_job(session: AsyncSession, job_id: str) -> TaskJob | None:
        return await session.get(TaskJob, uuid.UUID(job_id))

    @staticmethod
    async def _is_cancelled(session: AsyncSession, job_id: str) -> bool:
        """跨会话检测取消：fresh SELECT 避开身份映射缓存（revoke 由 cancel 端点写入）。"""
        stmt = (
            select(TaskJob)
            .where(TaskJob.id == uuid.UUID(job_id))
            .execution_options(populate_existing=True)
        )
        job = (await session.execute(stmt)).scalars().first()
        return job is not None and job.status == "cancelled"

    async def _mark_running(self, session: AsyncSession, job_id: str, stage: str) -> None:
        job = await self._get_job(session, job_id)
        if job is not None and job.status != "cancelled":
            await TaskJobRepository(session).mark_running(job, stage)
            await session.commit()

    async def _update_progress(
        self, session: AsyncSession, job_id: str, progress: int, stage: str
    ) -> bool:
        """推进进度；返回 False 表示任务已被取消（调用方应停止）。"""
        if await self._is_cancelled(session, job_id):
            return False
        job = await self._get_job(session, job_id)
        if job is not None:
            await TaskJobRepository(session).update_progress(job, progress, stage)
            await session.commit()
        return True

    async def _mark_succeeded(
        self, session: AsyncSession, job_id: str, *, result: dict, result_ref: str
    ) -> bool:
        """成功落库；若期间被取消则不改写（保持 cancelled，由 cancel 端点语义决定）。"""
        if await self._is_cancelled(session, job_id):
            return False
        job = await self._get_job(session, job_id)
        if job is not None:
            await TaskJobRepository(session).mark_succeeded(job, result=result, result_ref=result_ref)
            await session.commit()
            return True
        return False

    @staticmethod
    async def _mark_failed(session: AsyncSession, job_id: str, message: str) -> None:
        job = await AIExecutor._get_job(session, job_id)
        if job is not None and job.status != "cancelled":
            await TaskJobRepository(session).mark_failed(job, message)
            await session.commit()


def extract_pdf_text(path: str) -> str:
    """PDF 简历文本提取（；扫描件/图片需 OCR，另行评估）。pymupdf 可选依赖。"""
    try:
        import fitz # PyMuPDF
    except ImportError as exc:
        raise RuntimeError("pymupdf 未安装，无法解析 PDF（请按 requirements.txt 安装）") from exc
    doc = fitz.open(path)
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()


# 简历文件分流（图片/扫描件走 GLM 视觉，文本型 PDF 走原链路）
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg"})
_SCAN_PDF_MIN_CHARS = 50 # PDF 提取文本 < 50 字符判定为扫描件（无文本层）→ 视觉链路


def classify_resume_file(suffix: str, text: str) -> str:
    """简历文件分流（纯函数可单测）：返回 'vision'（图片/扫描件）或 'text'（文本型）。

    判定规则写死：
    - 图片后缀（.png/.jpg/.jpeg）→ 'vision'（图片无文本层，PyMuPDF 提不到文字）；
    - .pdf 且 get_text() 总字符数 < 50 → 'vision'（扫描版 PDF 无文本层）；
    - 否则 → 'text'（原链路 PyMuPDF + DeepSeek，零改动）。
    """
    s = (suffix or "").strip().lower()
    if s in _IMAGE_SUFFIXES:
        return "vision"
    if s == ".pdf" and len((text or "").strip()) < _SCAN_PDF_MIN_CHARS:
        return "vision"
    return "text"


def pdf_to_images(path: str, *, dpi: int = 144) -> list[bytes]:
    """PDF 分页转 PNG 字节（：扫描版 PDF 走视觉，逐页 get_pixmap）。"""
    import fitz # PyMuPDF

    doc = fitz.open(path)
    try:
        out: list[bytes] = []
        for page in doc:
            out.append(page.get_pixmap(dpi=dpi).tobytes("png"))
        return out
    finally:
        doc.close()


def image_bytes_to_data_uri(data: bytes, *, max_edge: int = 1280) -> str:
    """图片字节 → base64 data URI（超过 max_edge 降采样 + JPEG 压缩，控制视觉 API 载荷）。"""
    import base64
    import io

    from PIL import Image

    img = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = img.size
    if max(w, h) > max_edge:
        scale = max_edge / max(w, h)
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def pdf_to_data_uris(path: str, *, dpi: int = 144, max_edge: int = 1280) -> list[str]:
    """扫描版 PDF → 分页 data URI 列表（走视觉链路）。"""
    return [image_bytes_to_data_uri(b, max_edge=max_edge) for b in pdf_to_images(path, dpi=dpi)]


def image_to_data_uri(path: str, *, max_edge: int = 1280) -> str:
    """本地图片文件 → data URI（走视觉链路）。"""
    with open(path, "rb") as f:
        return image_bytes_to_data_uri(f.read(), max_edge=max_edge)


def profile_to_dict(profile_row) -> dict:
    """UserProfile ORM → 结构化画像 dict（供 Agent 使用）。"""
    return {
        "name": profile_row.name,
        "school": profile_row.school,
        "major": profile_row.major,
        "education": profile_row.education,
        "gpa": profile_row.gpa,
        "skills": list(profile_row.skills or []),
        # provenance 随画像透传（Stage2 从 DB 读画像供差距分析消费；方案 b 接线点）
        "skills_sources": list(getattr(profile_row, "skills_sources", None) or []),
        "internships": list(profile_row.internships or []),
        "projects": list(profile_row.projects or []),
        "certificates": list(profile_row.certificates or []),
    }


async def safe_run_graph(session: AsyncSession, job_id: str, graph, state: dict) -> dict | None:
    """执行图并统一异常处理：整图超时/异常 → mark_failed（：超时用户文案「分析暂时失败，请稍后重试」）。

    返回图结果；失败时返回 None（调用方直接 return，不再落库）。

    ：task root span 由 worker 层统一写入（覆盖所有执行器，含 resume_parse / plan_reassess），
    本函数不再写 task span；trace 上下文（trace_id + parent_span_id）由 worker 经 contextvars 注入。
    """
    from app.ai.runner import run_graph

    try:
        return await run_graph(graph, state)
    except TimeoutError:
        logger.error("executor: 整图超时 job=%s", job_id)
        await AIExecutor._mark_failed(session, job_id, "分析暂时失败，请稍后重试")
        return None
    except Exception as exc: # noqa: BLE001
        logger.exception("executor: 图执行失败 job=%s", job_id)
        await AIExecutor._mark_failed(session, job_id, "分析失败，请稍后重试")
        return None
