# CareerAI 本地部署与启动指南

> 本文档是本地启动与部署指南；公网部署、Nginx/HTTPS、日志监控等暂未包含，属于后续规划。
>
> **推荐路径：容器化一键启动**（见「二、容器化一键启动（推荐）」）——只需 Docker，一条命令拉起全部 5 个服务。
> 原手动 3 终端启动保留为**备选路径**（见「三、手动完整启动步骤（备选）」），供本地开发热重载 / 断点调试使用。

---

## 一、环境要求

| 模式 | 依赖 | 版本要求 | 说明 |
|------|------|---------|------|
| 容器化（推荐） | Docker + Docker Compose | Docker Engine 20.10+（Docker Desktop 4.x）/ Compose **v2.24+** | 唯一硬依赖；**无需本机安装 Python / Node / npm**（见「二」） |
| 手动（备选） | Docker + Docker Compose | compose v2 | 提供 PostgreSQL 16（pgvector 插件）+ Redis 7，见 `docker-compose.yml` |
| 手动（备选） | Python | 3.12（定案版本；3.11+ 亦可运行） | 后端 FastAPI，需可执行 `python` |
| 手动（备选） | Node.js | 18+（建议 20 LTS） | 前端 Vite 5 / React 18 |
| 手动（备选） | npm | 随 Node.js | 前端依赖安装 |

**端口占用（本地默认）**：

| 端口 | 服务 | 说明 |
|------|------|------|
| 5432 | PostgreSQL | compose 映射；被占用可改 compose 并同步 `DATABASE_URL` |
| 6380 | Redis | 刻意避开本机常见 6379；被占用可改 compose 并同步 `.env` |
| 8000 | 后端 API（容器 / uvicorn） | 被占用可换 8010（见「六、故障排查」） |
| 5173 | 前端（容器 Nginx / Vite dev server） | 被占用可改 `frontend/vite.config.ts` 的 `server.port` |

**资源**：bge-m3 本地权重约 2GB 量级（以实际下载为准），请预留磁盘空间；Embedding 在 CPU 上运行（`BGE_M3_DEVICE=cpu`）。

---

## 二、容器化一键启动（推荐）

> 本节为容器化部署说明：只需 Docker + Docker Compose，**无需本机安装 Python / Node / npm**。手动 3 终端流程见「三」，仅作本地开发备选。

### 1. 前置要求

| 依赖 | 要求 | 说明 |
|------|------|------|
| Docker Engine | 20.10+（Docker Desktop 4.x） | 需可运行 Linux 容器 |
| Docker Compose | **v2.24+** | 需支持 `env_file.required:false`（Compose v5 默认满足） |
| 空闲端口 | 5432 / 6380 / 8000 / 5173 | 被占用可改 `docker-compose.yml` 映射 |

> 首次启动会拉取基础镜像并构建应用镜像；backend 镜像含 `sentence-transformers`/`torch`（约 2–3GB），构建耗时较长属预期。

### 2. 一键启动

```powershell
.\start.ps1
# 或：powershell -ExecutionPolicy Bypass -File .\start.ps1
```

`start.ps1` 自动完成：

1. 检查 Docker / Docker Compose 可用性（缺失时给出安装指引）
2. `backend/.env` 不存在时从 `backend/.env.example` 复制生成；`DEEPSEEK_API_KEY` 为占位值则置空（保证无真实 key 时进入 fallback 模式）；新生成 `.env` 默认 `DEBUG=true`（FakeEmbedding，避免加载 bge-m3 2GB 权重，见本节第 5 条）
3. `docker compose up -d --build`：构建 backend/frontend 镜像，启动 **PG / Redis / backend / celery / frontend 5 个服务**
4. 健康检查等待（backend `GET /health` 返回 ok 且 backend/frontend 容器 healthy，最长 180s），输出各服务访问地址

### 3. 服务与访问地址

| 服务 | 容器名 | 宿主访问 | 说明 |
|------|--------|---------|------|
| PostgreSQL 16 + pgvector | `careerai-postgres` | `localhost:5432` | 数据卷 `careerai_pgdata` |
| Redis 7 | `careerai-redis` | `localhost:6380` | 数据卷 `careerai_redisdata` |
| FastAPI 后端 | `careerai-backend` | `http://localhost:8000` | `/health`、`/docs`；启动时自动 `alembic upgrade head` |
| Celery Worker | `careerai-celery` | （容器内） | 消费异步任务（简历解析 / 报告生成等） |
| Nginx 前端 | `careerai-frontend` | `http://localhost:5173` | 静态资源 + `/api` 反代到 backend |

> 组合项目名固定为 `careerai`（compose 顶层 `name` 字段）；数据卷实际命名为 `careerai_pgdata` / `careerai_redisdata`（Docker 按「项目名_卷名」规则命名）。

### 4. 配置与密钥

- 密钥统一走 `backend/.env`（已被 `.gitignore` 排除，**不入库、不进镜像**）；compose 通过 `env_file` 引用，缺失时自动跳过（`required:false`）。
- 数据库 / Redis / Celery 连接地址由 compose `environment` 覆盖为容器服务名（`postgres` / `redis`），**无需手动改 `backend/.env` 中的 localhost 地址**。
- 编辑 `backend/.env`（`JWT_SECRET` / `DEEPSEEK_API_KEY` 等）后重新执行 `.\start.ps1` 生效。
- **生产密钥强度（强制）**：生产环境必须通过 `backend/.env`（或 Secret Manager）注入 **≥32 字节**随机 `JWT_SECRET`（生成：`python -c "import secrets; print(secrets.token_urlsafe(64))"`），**禁止默认占位值上线**。代码内默认值 `dev-only-change-me-please-generate-a-real-random-secret-32b` 仅为本地开发占位符（消除 PyJWT InsecureKeyLengthWarning），公开可识别——默认值上线等于 JWT 可被伪造。
- **未配置 `DEEPSEEK_API_KEY`**：系统自动进入规则模板 fallback 模式——AI 报告为规则模板/兜底输出（非 LLM 生成），「注册 → 上传简历 → 生成报告 → 查看报告/计划」完整链路**仍可正常演示**；配置真实 Key 后即为 DeepSeek LLM 生成的高质量报告，无需其他操作。
- **未配置 `GLM_API_KEY`**：文本型 PDF 简历仍可正常解析；图片 / 扫描件简历会解析失败并引导手动补填。配置后即可用 GLM 视觉模型对图片/扫描件简历做 OCR 与结构化提取。
> 提示：无 Key fallback 下规则模板解析出的画像可能缺少姓名/学校/专业/毕业年份，`POST /reports` 会返回 3203「画像信息不完整」——属预期；UI 画像页按「AI 识别结果请确认」提示手动补填后再点「保存并生成报告」即可（API 路径先 `PUT /api/v1/profile` 补全）。

### 5. bge-m3 权重说明（真实模型用法）

- `start.ps1` 首次生成 `backend/.env` 时默认 `DEBUG=true` → 使用 `FakeEmbeddingProvider`（确定性伪嵌入，仅链路验证，**勿用于真实数据**）；复用已有 `.env`（如手动开发环境）则沿用其 `DEBUG` 值。
- 使用**真实 bge-m3**（约 2GB，CPU 推理）：
  1. 先在本机下载权重到 HuggingFace 缓存：`huggingface-cli download BAAI/bge-m3`（或 Python `snapshot_download('BAAI/bge-m3')`）；
  2. 在 `docker-compose.yml` 的 `backend` 与 `celery` 服务挂载宿主缓存目录（Windows 示例）：
     ```yaml
     volumes:
       - C:\Users\<用户名>\.cache\huggingface:/root/.cache/huggingface
     ```
  3. `backend/.env` 设 `DEBUG=false`；系统会按 `BGE_M3_MODEL_PATH` → HF 本地缓存快照 → 在线加载的顺序解析（见 `app/ai/rag/embedding.py`），命中本地缓存后强制 `HF_HUB_OFFLINE=1` 离线加载。
- 默认**不挂载**权重缓存，避免镜像过大、首启过慢；仅需演示/联调时无需真实模型。

### 6. 停止与清理

```powershell
.\stop.ps1 # 停止并删除容器（保留 PG/Redis 数据卷，数据仍在）
.\stop.ps1 -RemoveVolumes # 连同数据卷一并删除（数据清空）
```

---

## 三、手动完整启动步骤（备选）

> 本节为**备选路径**：仅当需要本地开发热重载 / 断点调试时使用；日常启动与演示请使用「二、容器化一键启动」。
> 以下命令在 **PowerShell** 下可直接复制执行；macOS/Linux（bash）将 `\.venv\Scripts\python.exe` 换成 `.venv/bin/python` 即可。所有后端命令均在 `backend/` 目录下执行。

### 1. 启动基础设施（PostgreSQL + Redis）

在项目根目录执行：

```powershell
docker compose up -d
```

首次执行会拉取 `pgvector/pgvector:pg16` 与 `redis:7` 镜像。验证：

```powershell
docker compose ps # postgres / redis 均应为 running（healthy）
```

### 2. 后端虚拟环境与依赖

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

> 提示：`requirements.txt` 含 `sentence-transformers`（bge-m3 本地向量化，随包安装 torch）。安装体积较大，属预期行为。

### 3. 配置环境变量（.env）

```powershell
Copy-Item .env.example .env
```

然后编辑 `backend/.env`，至少配置以下两项：

```dotenv
# 生产强度随机密钥（必改，≥32 字节）：python -c "import secrets; print(secrets.token_urlsafe(64))"
JWT_SECRET=换成上面命令的输出

# 真实报告生成必需；不配则 LLM 路径不可用，报告走规则模板兜底
DEEPSEEK_API_KEY=sk-你的-DeepSeek-API-Key
```

> `DEEPSEEK_API_KEY`：真实报告生成（简历解析、Stage1/Stage2 报告）必需；未配置时系统进入 fallback 模式（规则模板/兜底输出），「注册 → 上传简历 → 生成报告」链路仍可完整演示，系统其余功能不受影响。密钥为敏感凭证，已被 `.gitignore` 排除，不会入库。
>
> `GLM_API_KEY`（可选）：用于图片/扫描件简历 OCR；未配置时文本型 PDF 仍可解析，图片/扫描件会引导手动补填。

### 4. 执行数据库迁移（10 个 alembic 版本）

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current # 应显示 head（10 个版本全部应用）
```

当前迁移共 10 个版本（`backend/alembic/versions/`，base → head）：

1. `15528104623c_initial_schema` — 初始表结构（base）
2. `d2baf00450de_add_user_profile_preference_fields` — 用户画像偏好字段
3. `2d36e64f1408_market_data_quarter_tier_and_vector` — 市场数据表（季度/城市线级/向量列）
4. `a50cb7d4a7aa_create_norm_benchmarks_table` — 常模基准表
5. `c1a2b3d4e5f6_add_achievements_reassessments` — 成就记录与复盘评估表
6. `2a2911abafba_add_market_data_source_type` — 市场数据来源类型列（official_stat/job_post/ai_infer）
7. `a1b2c3d4e5f6_add_operation_reviews` — 关键操作审计/确认表
8. `8c5d2e7f4a1b_add_trace_spans` — trace_spans 表 + task_jobs.trace_id
9. `e5f7a9c1b3d2_add_user_profile_skills_sources` — 画像技能来源/provenance
10. `9c2a7b5e3f1d_add_market_education_responsibilities` — 市场数据学历/职责字段（head）

### 5. bge-m3 本地快照预置（建议；缺失时 RAG 自动降级）

系统按以下顺序解析 bge-m3 加载来源（`app/ai/rag/embedding.py`）：

1. `BGE_M3_MODEL_PATH`（显式本地目录）
2. **HuggingFace 本地缓存完整快照**（默认路径 `~/.cache/huggingface/hub`，Windows 为 `C:\Users\<用户名>\.cache\huggingface\hub`）下的 `models--BAAI--bge-m3/snapshots/<commit>/`，要求目录内含 `config.json` 且含权重文件（`model.safetensors` / `pytorch_model.bin`）
3. 以上均无 → 回退 `model_name` 在线加载（需网络）；仍不可用则 RAG 检索降级为空，市场 Agent 仅用 LLM 通用知识并标注「数据较少」

命中本地快照时强制 `HF_HUB_OFFLINE=1` 离线加载，**无网络依赖**。

可选下载命令（有网络时提前下载到缓存，供后续离线使用）：

```powershell
# 方式一：huggingface-cli
.\.venv\Scripts\python.exe -m pip install "huggingface_hub[cli]"
huggingface-cli download BAAI/bge-m3

# 方式二：Python API
.\.venv\Scripts\python.exe -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-m3')"
```

> 注意事项：`backend/.env` 默认 `DEBUG=false` 时使用真实 bge-m3；若将 `DEBUG` 设为 `true`，Embedding 会切换为 Fake 伪嵌入（仅链路验证，勿用于真实数据）。

### 6. 启动后端 API（uvicorn）

终端 1（`backend/` 目录）：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

> 8000 端口被占用时换 8010：`--port 8010`，同时需把 `frontend/vite.config.ts` 中 `/api` 代理的 `target` 同步改为 `http://localhost:8010`。

### 7. 启动异步任务 worker（celery）

终端 2（`backend/` 目录）：

```powershell
.\.venv\Scripts\python.exe -m celery -A app.tasks.celery_app worker --pool=solo -l info
```

> **Windows 必须 `--pool=solo`**（Celery 默认 prefork pool 在 Windows 不支持）。报告生成、简历解析等异步任务依赖 worker；不启动则任务停留在 pending。

### 8. 启动前端（Vite dev server）

终端 3（`frontend/` 目录）：

```powershell
cd ..\frontend
npm install
npm run dev
```

浏览器访问 <http://localhost:5173>。
> 提示：Vite 6 默认仅监听 IPv6 `::1`——浏览器请用 `http://localhost:5173`（`http://127.0.0.1:5173` 可能被拒，属正常，非故障）。

> 前端 API 地址：dev 环境通过 `frontend/vite.config.ts` 的 `/api` 代理指向 `http://localhost:8000`，前端代码内统一使用相对路径 `/api/v1`，**无需额外配置 API 地址**（如后端换端口，见步骤 6 提示同步修改代理）。

---

## 四、验证（冒烟）

### 1. 服务健康

- 后端：<http://localhost:8000/health>，应返回 `{"code":0,...,"data":{"status":"ok","database":"ok","redis":"ok"}}`
- Swagger：<http://localhost:8000/docs>
- 前端：<http://localhost:5173> 正常加载登录/首页

> 容器化模式下可补充自检：`docker compose ps` 全部服务 running，且 backend / frontend 为 healthy。

### 2. 最小业务冒烟（注册 → 登录 → 上传简历 → 生成报告）

> 上传简历→生成报告需已配置 `DEEPSEEK_API_KEY`（真实 LLM 路径）；未配置时报告走规则模板兜底，仍可走通流程但内容为规则模板输出。

```powershell
# 1) 注册
curl.exe -X POST http://localhost:8000/api/v1/auth/register -H "Content-Type: application/json" -d '{"username":"demo01","password":"password123"}'

# 2) 登录（取 data.tokens.access_token）
curl.exe -X POST http://localhost:8000/api/v1/auth/login -H "Content-Type: application/json" -d '{"account":"demo01","password":"password123"}'

# 3) 上传简历（文本型 PDF；multipart 字段名 file）→ 返回 data.task_id
curl.exe -X POST http://localhost:8000/api/v1/profile/resume -H "Authorization: Bearer <access_token>" -F "file=@resume.pdf"

# 4) 轮询解析任务（替换 <task_id>），直到 status=succeeded
curl.exe http://localhost:8000/api/v1/tasks/<task_id> -H "Authorization: Bearer <access_token>"

# 5) 查看画像（确认已落库）
curl.exe http://localhost:8000/api/v1/profile -H "Authorization: Bearer <access_token>"

# 6) 生成报告（profile_id 取第 5 步返回）→ 返回新 task_id，轮询到 succeeded 后按 result_ref 取报告
curl.exe -X POST http://localhost:8000/api/v1/reports -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" -d '{"profile_id":"<profile_id>","preferred_cities":["北京"],"preferred_industries":["互联网"]}'
```

也可在浏览器完成相同路径（UI 冒烟）：注册/登录 → 我的画像 → 上传简历 → 生成报告 → 查看报告/计划。

---

## 五、测试

### 后端（pytest，mock 隔离零 Docker 依赖）

> 前置：**无需 Docker / 数据库 / LLM Key**（测试基线：DB/Redis/LLM 全部 mock 隔离，393 用例可在纯 Python 环境运行）。

```powershell
.\.venv\Scripts\python.exe -m pytest tests -v
```

**基线**：**393 passed**（`backend/tests/` 全量，mock 隔离，零 Docker 依赖）。当前测试集不包含 live 门控用例，全部为离线用例。

### 前端

```powershell
cd frontend
npm run typecheck
npm run build
```

### AI 评估脚本（backend/scripts/）

`backend/scripts/` 当前包含 **AI 评估脚本**（非启动/冒烟脚本），在 `backend` 目录下执行：

| 脚本 | 用法 | 说明 |
|------|------|------|
| `backend/scripts/eval_rag.py` | `python -m scripts.eval_rag [--data DIR] [--mode auto\|mock\|real] [--json] [--out FILE]` | RAG 检索评估（recall@k / 命中率）；`--mode auto` 前置缺失时自动降级 mock，无 key 无权重可跑 |
| `backend/scripts/eval_report_quality.py` | `python -m scripts.eval_report_quality [--data DIR] [--json] [--out FILE]` | 报告质量规则校验（确定性规则，不调用 LLM） |

评测数据集见 `backend/evaluation_data/`（`README.md` 为说明）。

### 市场数据导入（开发者）

市场数据文件：`backend/data/market_records_2026Q2.json`。在 `backend/` 目录执行：

```powershell
python scripts/seed_market_data.py
```

字段说明、常用参数与真实向量化注意事项见 README「开发者：添加市场数据」。

---

## 六、故障排查（与 README「启动故障排查」一致）

| 现象 | 适用模式 | 处理 |
|------|---------|------|
| `docker compose ps` 无容器或状态 exited | 两者 | Docker 未启动 / 未就绪：先启动 Docker Desktop，等待引擎就绪后重跑 `docker compose up -d`，并用 `docker compose ps` 确认 postgres / redis 均为 running（healthy） |
| 5432 / 6380 端口被占用 | 两者 | 本机已有 PG / Redis：修改 `docker-compose.yml` 端口映射，并同步 `backend/.env` 中 `DATABASE_URL` / `REDIS_URL` / `CELERY_*` |
| 8000 端口被占用 | 手动 | uvicorn 改用 `--port 8010`，并同步 `frontend/vite.config.ts` 中 `/api` 代理的 `target` 为 `http://localhost:8010` |
| 8000 端口被占用 | 容器化 | 修改 `docker-compose.yml` 的 `backend` 端口映射后重跑 `.\start.ps1` |
| 5173 端口被占用 | 两者 | 修改 `frontend/vite.config.ts` 的 `server.port`（容器化另需同步 compose `frontend` 端口映射） |
| 任务一直停留在 pending | 两者 | Celery worker 未启动：手动模式另开终端启动 worker（**Windows 必须 `--pool=solo`**）；容器化模式用 `docker compose logs celery` 检查 worker 是否正常消费 |
| 报告内容为模板风格 | 两者 | `DEEPSEEK_API_KEY` 未配置——属预期 fallback 行为，不影响演示；配置 Key 后重启（容器化：重跑 `.\start.ps1`）即为真实 LLM 报告 |
| RAG 检索为空 / bge-m3 相关报错 | 两者 | bge-m3 模型未下载 → **自动降级**：RAG 检索降级为空，市场 Agent 仅用 LLM 通用知识并标注「数据较少」，系统正常可用；如需完整 RAG 能力，提前执行 `huggingface-cli download BAAI/bge-m3`（约 2GB，命中本地快照后离线加载）。注意：`DEBUG=true` 时 Embedding 为 Fake 伪嵌入（仅链路验证，勿用于真实数据） |
| 后端健康检查异常 | 两者 | PG / Redis 未就绪：访问 `http://localhost:8000/health`，确认返回 `database: ok` 与 `redis: ok` |
| 镜像拉取失败（`pull access denied` / `failed to resolve reference` / `dial tcp`） | 容器化 | 检查网络/代理（Docker Desktop → Settings → Resources → Proxies），或配置镜像加速器后重试 |
| 镜像构建失败（`failed to solve` / `npm ERR` / pip 错误） | 容器化 | `docker compose logs backend` / `logs frontend` / `logs celery` 查看构建与启动日志；前端构建失败检查 `frontend/src` 代码，后端依赖失败检查网络/源 |
| 前端镜像构建 `npm ci` 报 `ECONNRESET` / `network aborted` | 容器化 | 网络瞬断：直接重跑 `.\start.ps1` 或 `docker compose build frontend` 重试即可；持续失败再检查 npm registry 可达性/代理/镜像源 |
| 手动模式 `pip install` 报 `THESE PACKAGES DO NOT MATCH THE HASHES` | 手动 | 多为本机 pip 缓存污染（requirements 无 hash 时仍可能出现）：改用 `python -m pip install --no-cache-dir -r requirements.txt` |
| 8000 端口被占但 `netstat` 查不到对应进程（残留进程，PID 存在但 `Get-Process` 无结果） | 两者 | 多为其他会话/项目遗留的 uvicorn：`Get-NetTCPConnection -LocalPort 8000 -State Listen` 确认；无法终止时——容器化走 5173→nginx→backend 内网（UI 不受影响），API 直连可 `docker exec careerai-backend curl http://127.0.0.1:8000/health`；手动模式换 `--port 8010` |
| 简历解析任务 `failed`，日志 `FileNotFoundError` 指向宿主机 Windows 路径 | 两者 | 容器 worker 与手动 worker 混跑同一 Redis 队列，任务被错误 worker 消费：同一时刻只保留一套 celery（手动路径先 `docker compose stop backend celery frontend`）。另：容器化上传依赖 backend/celery 共享卷 `/tmp/careerai_resumes`（compose `resume_tmp` 卷 + Dockerfile 预建目录），勿删卷/改挂载 |
| 后端容器启动即退出 | 容器化 | `docker compose logs backend`：`alembic upgrade head` 失败会 fail-fast（容器退出），按日志修复迁移或 `.env` 配置后重跑 `.\start.ps1` |
| 首次构建很慢 / 磁盘不足 | 容器化 | backend 镜像含 torch 约 2–3GB，预留 8GB+ 磁盘；可用 `docker system prune` 清理旧镜像 |

> 容器模式与手动模式共享同一份 `backend/.env`；如需调试（热重载/断点），使用「三、手动完整启动步骤」。

---

## 七、已知限制

1. **市场数据为 458 条可溯源真实样本（2026Q2，非全量市场）**：官方统计 354 条 + 公开招聘 76 条 + 存量 28 条，覆盖 11 个专业大类；数据来源与口径见 `backend/data/market_source_manifest.md`。
2. **图片/扫描件简历依赖 GLM 视觉**：文本型 PDF 走 PyMuPDF；图片/扫描件需配置 `GLM_API_KEY` 后由 GLM 视觉模型 OCR 并结构化；未配置时解析失败并引导手动补填。
3. **LLM 依赖 `DEEPSEEK_API_KEY`**：未配置时报告走规则模板兜底（fallback 模式，见「二-4」/「三-3」）；备用模型（`DEEPSEEK_FALLBACK_MODEL`）降级路径未实测。
4. **Mobile 性能口径未达标**：antd 全量 chunk 约 993KB 导致 Mobile 模拟 FCP/LCP 未达标；已按桌面端口径验证（Perf 96–98），桌面浏览器优先。
5. **部署范围**：公网部署、Nginx/HTTPS、静态托管、日志监控、错误监控暂未包含，属于后续规划；CI 已内置（`.github/workflows/business-ci.yml` 后端 pytest + ruff、前端 lint/typecheck/test/build）。当前为本地可运行版本。

---

## 八、功能范围说明

**当前已支持**：

- 账号密码注册/登录（本地 JWT，PyJWT + bcrypt）
- 简历上传与解析（文本型 PDF / 图片扫描件 GLM 视觉）+ 职业画像（含手动表单补填）
- 职业分析报告 Stage1（画像评分 + 方向推荐，LangGraph 两图 + RAG）
- 差距分析 Stage2 + 成长计划（`/reports/{id}/gap`、`/reports/{id}/plan`）
- 市场数据浏览（`/api/v1/market/jobs`、`/facets`，458 条市场数据）
- 异步任务框架（Celery + `task_jobs` 持久化，离开不取消）
- 本地一键启动（本指南，推荐容器化路径）与测试基线（后端 pytest 393 用例 / 前端 Vitest 108 用例）

**暂不支持（后续规划）**：

- 手机号短信验证码 / 微信扫码登录
- 公网部署、Nginx/HTTPS、域名、静态托管（CloudBase）
- 日志监控告警、错误监控
- 全量市场数据采集管道（后续规划）
- 收藏、Mobile 性能专项、备用模型 fallback

---

## 附录：目录速览

```text
CareerAI/
├── DEPLOYMENT.md ← 本文件
├── docker-compose.yml ← 5 服务编排：PG16(pgvector) + Redis + backend + celery + frontend
├── start.ps1 / stop.ps1 ← 容器化一键启动/停止（推荐路径）
├── backend/ ← FastAPI + Celery + Alembic + pytest
│ ├── app/ ← 源码（main.py 入口；ai/rag/embedding.py 等）
│ ├── alembic/ ← 迁移（10 个版本，base → head）
│ ├── scripts/ ← AI 评估脚本（eval_rag / eval_report_quality）
│ ├── evaluation_data/ ← AI 评估数据集
│ ├── tests/ ← pytest（393 用例，mock 隔离）
│ ├── .env.example ← 环境变量模板
│ └── requirements.txt
└── frontend/ ← React 18 + AntD 5 + Vite（npm run dev → 5173）
```
