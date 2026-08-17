# CareerAI 后端镜像（FastAPI + Celery worker 共用）
# 运行时：python:3.12-slim（项目定案版本，见 DEPLOYMENT.md 环境要求）
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先装依赖（利用构建缓存）；requirements 含 sentence-transformers/torch，镜像体积较大属预期
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 显式拷贝源码目录（不使用 COPY . .，避免 .env / 本地缓存进入镜像）
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY app/ ./app/

# 非 root 运行（容器规范）
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app \
    && mkdir -p /tmp/careerai_resumes && chown appuser:appuser /tmp/careerai_resumes
USER appuser

EXPOSE 8000

# 启动前自动执行数据库迁移（迁移失败即容器退出，fail-fast），随后启动 API
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
