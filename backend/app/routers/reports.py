"""报告端点（reports-contract）：Stage1 提交/列表/详情 + Stage2（gap）/计划重生成。"""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.base import get_db
from app.models import User
from app.schemas.audit import OperationConfirmationOut
from app.schemas.common import ApiResponse
from app.schemas.reports import GapRequest, ReportCreateRequest, ReportDetailOut, ReportListItemOut
from app.schemas.task import TaskTriggerResult
from app.services.report_service import ReportService

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("", response_model=ApiResponse[TaskTriggerResult])
async def create_report(
    req: ReportCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await ReportService(db).create_report(current_user, req))


@router.get("", response_model=ApiResponse[dict])
async def list_reports(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await ReportService(db).list_reports(current_user, page, page_size))


@router.get("/{report_id}", response_model=ApiResponse[ReportDetailOut])
async def get_report(
    report_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await ReportService(db).get_report(current_user, report_id))


@router.post("/{report_id}/gap", response_model=ApiResponse[TaskTriggerResult])
async def create_gap_analysis(
    report_id: uuid.UUID,
    req: GapRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await ReportService(db).create_gap_analysis(current_user, report_id, req))


@router.post("/{report_id}/plan", response_model=ApiResponse[TaskTriggerResult | OperationConfirmationOut])
async def regenerate_plan(
    report_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await ReportService(db).regenerate_plan(current_user, report_id))
