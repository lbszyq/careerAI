"""profile 业务编排：画像查询/保存（upsert）/简历上传（→ resume_parse 异步任务）。"""
import logging
import os
import tempfile
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.core.errors import ApiError, ErrorCode
from app.models import User
from app.repositories.profile_repository import ProfileRepository
from app.schemas.profile import ProfileOut, ProfileUpdate
from app.schemas.task import TaskTriggerRequest, TaskTriggerResult
from app.services.error_codes import ProfileErrorCode
from app.services.task_service import TaskService

logger = logging.getLogger("careerai.profile")

ALLOWED_RESUME_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg"}
ALLOWED_RESUME_TYPES = {"application/pdf", "image/png", "image/jpeg"}
MAX_RESUME_BYTES = 10 * 1024 * 1024 # 10MB（profile-contract）


class ProfileService:
    def __init__(self, session):
        self.session = session
        self.profile_repo = ProfileRepository(session)

    async def get_profile(self, user: User) -> ProfileOut | None:
        profile = await self.profile_repo.get_active(user.id)
        if profile is None:
            return None
        return ProfileOut.model_validate(profile)

    async def save_profile(self, user: User, payload: ProfileUpdate) -> ProfileOut:
        """PUT /profile：upsert 草稿（允许不完整，最低门槛在 POST /reports 校验）。"""
        cities = payload.preferred_cities or []
        industries = payload.preferred_industries or []
        if len(cities) > 5:
            raise ApiError(ErrorCode.INVALID_PARAM, "意向城市最多 5 个", 400)
        if len(industries) > 5:
            raise ApiError(ErrorCode.INVALID_PARAM, "意向行业最多 5 个", 400)

        data = {
            "name": payload.name,
            "school": payload.school,
            "major": payload.major,
            "education": payload.education,
            "graduation_year": payload.graduation_year,
            "gpa": payload.gpa,
            "skills": _dedupe(payload.skills or []),
            "internships": payload.internships or [],
            "projects": payload.projects or [],
            "certificates": payload.certificates or [],
            "preferred_cities": _dedupe(cities),
            "preferred_industries": _dedupe(industries),
            "expected_salary": payload.expected_salary,
            "is_active": True,
        }
        row = await self.profile_repo.upsert(user.id, data)
        await self.session.commit()
        # updated_at 由 onupdate=func.now() 生成 SQL 表达式，commit 后需 refresh 才能读取
        await self.session.refresh(row)
        return ProfileOut.model_validate(row)

    async def upload_resume(self, user: User, file: UploadFile) -> TaskTriggerResult:
        """POST /profile/resume：校验类型/大小 → 临时文件 → resume_parse 异步任务。

        临时文件由执行器解析后删除（C-008），本层不落长期存储。
        """
        suffix = Path(file.filename or "").suffix.lower()
        content_type = (file.content_type or "").lower()
        if suffix not in ALLOWED_RESUME_SUFFIXES or (
            content_type and content_type not in ALLOWED_RESUME_TYPES
        ):
            raise ApiError(
                ProfileErrorCode.FILE_TYPE_UNSUPPORTED, "仅支持 PDF/PNG/JPG 格式的简历文件", 400
            )

        content = await file.read(MAX_RESUME_BYTES + 1)
        if len(content) > MAX_RESUME_BYTES:
            raise ApiError(ProfileErrorCode.FILE_SIZE_EXCEEDED, "文件超过 10MB", 400)

        temp_dir = Path(tempfile.gettempdir()) / "careerai_resumes"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / f"{uuid.uuid4().hex}{suffix}"
        try:
            temp_path.write_bytes(content)
        except OSError as exc: # noqa: BLE001
            logger.exception("upload_resume: 临时文件写入失败")
            raise ApiError(ErrorCode.INTERNAL_ERROR, "文件保存失败，请稍后重试", 500) from exc

        try:
            task_service = TaskService(self.session)
            job = await task_service.create_and_dispatch(
                user,
                "resume_parse",
                {"user_id": str(user.id), "file_path": str(temp_path)},
            )
            return TaskTriggerResult(task_id=job.id, status=job.status)
        except Exception:
            # 任务创建失败时清理临时文件，避免残留（C-008）
            try:
                if temp_path.exists():
                    os.remove(temp_path)
            except OSError:
                logger.warning("upload_resume: 清理临时文件失败 %s", temp_path)
            raise


def _dedupe(values: list[str]) -> list[str]:
    """技能/意向去重且保序（C-003）。"""
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out
