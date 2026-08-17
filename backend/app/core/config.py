"""应用配置：从环境变量 / backend/.env 读取（pydantic-settings）。"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 目录（config.py 位于 backend/app/core/，上溯两级）
BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "CareerAI API"
    APP_VERSION: str = "0.1.0"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = False
    TESTING: bool = False # pytest 环境标记（conftest 注入，Fake embedding 判定用）

    # 数据库 / 缓存
    DATABASE_URL: str = "postgresql+asyncpg://careerai:careerai@localhost:5432/careerai"
    REDIS_URL: str = "redis://localhost:6380/0"

    # JWT
    # 开发占位符（≥32 字节，消除 PyJWT InsecureKeyLengthWarning；RFC 7518 要求 HS256 密钥 ≥256 bit）。
    # 生产环境必须通过 .env / Secret Manager 注入真实随机密钥，禁止默认占位值上线。
    JWT_SECRET: str = "dev-only-change-me-please-generate-a-real-random-secret-32b"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6380/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6380/2"

    # 密码强度
    PASSWORD_MIN_LENGTH: int = 8

    # --- AI（：DeepSeek / bge-m3 / RAG，全部 env 注入，禁止硬编码密钥）---
    # DeepSeek（OpenAI 兼容接口，architecture.md）
    DEEPSEEK_API_KEY: str = "" # 缺失时 LLMClient 进入 fallback 模式（规则模板/兜底输出）
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-v4-flash" # 主模型（定案）
    DEEPSEEK_FALLBACK_MODEL: str = "" # 备选模型；空 = 不降级模型，仅降级兜底模板
    DEEPSEEK_TIMEOUT_SECONDS: float = 30.0 # 单次调用 ≤30s（）
    DEEPSEEK_MAX_RETRIES: int = 3 # 指数退避重试次数（429/5xx）
    DEEPSEEK_TEMPERATURE: float = 0.3
    DEEPSEEK_MAX_OUTPUT_TOKENS: int = 4096 # 2048→4096，降低 JSON 节点首轮失败率（实测）

    # GLM 多模态视觉（：简历图片/扫描件 OCR + 结构化；智谱 OpenAI 兼容接口，环境变量注入）
    GLM_API_KEY: str = "" # 缺失时视觉链路不可用（图片/扫描件简历 → mark_failed 引导手动补填）
    GLM_VISION_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4"
    GLM_VISION_MODEL: str = "glm-4.6v-flash" # 智谱免费视觉模型（128K 上下文）
    GLM_VISION_TIMEOUT_SECONDS: float = 60.0 # 视觉 OCR 单次放宽（多页/复杂排版 > DeepSeek 30s）
    GLM_VISION_MAX_RETRIES: int = 3 # 免费模型限流 429，指数退避重试

    # bge-m3 本地向量化（：1024 维，无 API 成本/无数据出境）
    BGE_M3_MODEL_NAME: str = "BAAI/bge-m3"
    BGE_M3_MODEL_PATH: str = "" # 本地模型目录（部署后注入；空 = 走 model_name 在线加载）
    BGE_M3_DEVICE: str = "cpu"

    # RAG 检索（：Top-K=10、相似度阈值 ≥0.7）
    RAG_TOP_K: int = 10
    RAG_SIMILARITY_THRESHOLD: float = 0.7
    RAG_MAX_CONTEXT_CHARS: int = 6000 # 检索上下文注入上限（Token 预算）

    # RAG Rerank（：本地交叉编码器重排，architecture.md 契约偏离——见回报）
    # 链路：RRF 融合候选池放大到 RERANK_CANDIDATE_POOL → Rerank 重排 → 截断 Top-K。
    # Rerank 为可选增强：模型不可用/超时/失败时降级到 RRF 原序（不改变命中集合，检索不失败）。
    RERANK_ENABLED: bool = True # 重排总开关（false=跳过重排，候选池直接按 RRF 序截断）
    RERANK_MODEL: str = "BAAI/bge-reranker-v2-m3" # 本地交叉编码器 reranker（多语言含中文）
    RERANK_MODEL_PATH: str = "" # 本地模型目录（部署后注入；空 = HF 缓存快照/在线加载，同 bge-m3）
    RERANK_DEVICE: str = "cpu"
    RERANK_CANDIDATE_POOL: int = 40 # RRF 融合后候选池大小（放大前置：Rerank 只重排候选内部顺序，池须 >Top-K 才能把池外候选排入 Top-K）
    RERANK_TIMEOUT_SECONDS: float = 5.0 # 单次 Rerank 调用超时上限（≤5s，architecture.md 30s 调用约束内）
    RERANK_API_KEY: str = "" # 云端 Rerank API key 占位（本地方案不使用；云端方案由用户/项目负责人 填 .env，不入库）

    # AI 成本/安全（/）
    AI_DAILY_REPORT_LIMIT: int = 3 # 每用户每日报告生成次数上限
    AI_DAILY_TASK_LIMIT: int = 10 # 每用户每日 AI 任务配额（resume_parse/plan_regenerate/plan_reassess 聚合计数）
    AI_WATCHDOG_SECONDS: float = 180.0 # 整图 watchdog（单轮 ≤3min）
    AI_GUARD_ENABLED: bool = True # Input/Output Guard 总开关（默认开启，禁止为方便关闭）
    AI_AUDIT_LOG_ENABLED: bool = True # 安全审计日志

    # 人机协同（architecture.md）：关键操作二次确认开关。
    # false = 自动批准 + 审计落库（本地演示默认，不打断现有体验）；
    # true = 先返回待确认 ID，用户调用 /operations/{id}/approve|reject 后才执行/放弃。
    REQUIRE_CONFIRMATION: bool = False

    # CORS（Vite dev server）
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
