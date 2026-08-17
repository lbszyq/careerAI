"""CareerAI FastAPI 应用入口。"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.errors import ApiError, ErrorCode
from app.routers import audit, auth, feedback, health, market, metrics, plans, profile, reports, tasks

logger = logging.getLogger("careerai")

settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="CareerAI 本地 本地版本 后端骨架",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    return JSONResponse(
        status_code=exc.http_status,
        content={"code": exc.code, "message": exc.message, "data": None},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    # 缺失必填字段 → 2002 MISSING_REQUIRED；格式/值非法 → 2001 INVALID_PARAM（architecture.md）
    first = exc.errors()[0] if exc.errors() else {}
    if first.get("type") == "missing":
        code = ErrorCode.MISSING_REQUIRED
        message = f"缺少必填字段: {first.get('loc', [])}"
    else:
        code = ErrorCode.INVALID_PARAM
        message = f"参数校验失败: {first.get('loc', [])} {first.get('msg', '')}"
    return JSONResponse(
        status_code=400,
        content={"code": code, "message": message, "data": None},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception("未处理异常: %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"code": ErrorCode.INTERNAL_ERROR, "message": "服务器内部错误", "data": None},
    )


app.include_router(health.router)
app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(tasks.router, prefix=settings.API_V1_PREFIX)
app.include_router(profile.router, prefix=settings.API_V1_PREFIX)
app.include_router(reports.router, prefix=settings.API_V1_PREFIX)
app.include_router(plans.router, prefix=settings.API_V1_PREFIX)
app.include_router(market.router, prefix=settings.API_V1_PREFIX)
app.include_router(feedback.router, prefix=settings.API_V1_PREFIX)
app.include_router(audit.router, prefix=settings.API_V1_PREFIX)
app.include_router(metrics.router, prefix=settings.API_V1_PREFIX)


@app.get("/")
async def root():
    return {"code": 0, "message": "ok", "data": {"service": settings.APP_NAME, "docs": "/docs"}}
