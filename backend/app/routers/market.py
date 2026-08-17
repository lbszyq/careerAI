"""市场数据端点（market-contract，公开访问：无鉴权）。"""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.schemas.common import ApiResponse
from app.schemas.market import MarketFacetsOut, MarketJobDetailOut, MarketListOut
from app.services.market_service import MarketService

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/jobs", response_model=ApiResponse[MarketListOut])
async def list_jobs(
    city: str | None = Query(default=None),
    industry: str | None = Query(default=None),
    job_title: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50),
    sort: str = Query(default="default"),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(
        data=await MarketService(db).list_jobs(city, industry, job_title, page, page_size, sort)
    )


@router.get("/jobs/{job_id}", response_model=ApiResponse[MarketJobDetailOut])
async def get_job_detail(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await MarketService(db).get_job(job_id))


@router.get("/facets", response_model=ApiResponse[MarketFacetsOut])
async def get_facets(
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await MarketService(db).facets())
