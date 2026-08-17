<#
.SYNOPSIS
CareerAI 一键启动（容器化）：环境检查 -> 准备 backend/.env -> docker compose up -d --build -> 健康检查 -> 输出访问地址。

.DESCRIPTION
需要 Docker Engine + Docker Compose v2.24+（Compose v5 默认满足）。
在项目根目录下执行，自动完成：
  1. 检查 docker / docker compose 可用性（不可用则给出安装指引）
  2. backend/.env 缺失时从 .env.example 生成，并清除 DEEPSEEK_API_KEY 占位值（无真实 key 时进入 fallback 模式）
  3. docker compose up -d --build 构建并启动 PG/Redis/backend/celery/frontend
  4. 健康检查等待（backend /health 返回 ok 且容器 healthy），输出各服务访问地址
端口占用 / 镜像拉取失败 / 依赖未装等异常会输出明确错误与解决指引，不静默失败。

.EXAMPLE
.\start.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Write-Step { param([string]$msg) Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok { param([string]$msg) Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Err { param([string]$msg) Write-Host "[错误] $msg" -ForegroundColor Red }

# ---- 1. 环境检查 ----
Write-Step '检查 Docker 环境...'
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Err '未检测到 docker 命令。'
    Write-Host '解决指引：安装 Docker Desktop（Windows/macOS）或 docker-ce（Linux），确认 `docker version` 可正常输出后重试。'
    exit 1
}
docker compose version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Err 'docker compose 不可用（需要 Compose v2.24+）。'
    Write-Host '解决指引：更新 Docker Desktop 到最新版本（设置中启用 Compose V2），或安装独立 compose 插件；确认 `docker compose version` 可输出。'
    exit 1
}
Write-Ok 'Docker + Docker Compose 可用'

# ---- 2. 准备 backend/.env ----
Write-Step '准备 backend/.env ...'
$envExample = Join-Path $PSScriptRoot 'backend\.env.example'
$envFile = Join-Path $PSScriptRoot 'backend\.env'
if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item -LiteralPath $envExample -Destination $envFile
    $envCreated = $true
    Write-Host ' backend/.env 不存在，已从 backend/.env.example 复制生成（密钥不入库）。'
    # 容器模式默认 DEBUG=true -> FakeEmbedding（避免加载 bge-m3 2GB 权重；真实模型见 DEPLOYMENT.md 七-5）
    $dbg = Get-Content -LiteralPath $envFile -Encoding UTF8 | ForEach-Object {
        if ($_ -match '^DEBUG=') { 'DEBUG=true' } else { $_ }
    }
    [System.IO.File]::WriteAllText($envFile, ($dbg -join "`r`n") + "`r`n", [System.Text.UTF8Encoding]::new($false))
    Write-Host ' 已设置 DEBUG=true（FakeEmbedding；真实 bge-m3 用法见 DEPLOYMENT.md 第 7 节）。'
} else {
    $envCreated = $false
}
# 清除 DEEPSEEK_API_KEY 占位值，保证未配置真实 key 时进入 fallback 模式
$lines = Get-Content -LiteralPath $envFile -Encoding UTF8
$newLines = @()
$changed = $false
foreach ($line in $lines) {
    if ($line -match '^DEEPSEEK_API_KEY=.*\$\{?YOUR_DEEPSEEK_API_KEY\}?.*$') {
        $newLines += 'DEEPSEEK_API_KEY='
        $changed = $true
    } else {
        $newLines += $line
    }
}
if ($changed) {
    # 显式 UTF-8 无 BOM 写回（避免 BOM 污染首行解析）
    [System.IO.File]::WriteAllText($envFile, ($newLines -join "`r`n") + "`r`n", [System.Text.UTF8Encoding]::new($false))
    Write-Host ' backend/.env 中 DEEPSEEK_API_KEY 为占位值，已置空 -> LLM 使用 fallback 模式（规则模板兜底）。'
}
$keyLine = $newLines | Where-Object { $_ -match '^DEEPSEEK_API_KEY=' } | Select-Object -First 1
if ($keyLine -and $keyLine -ne 'DEEPSEEK_API_KEY=') {
    Write-Ok 'DEEPSEEK_API_KEY 已配置（真实 LLM 调用可用）'
} else {
    Write-Host ' 提示：DEEPSEEK_API_KEY 未配置，AI 报告走规则模板兜底（fallback），系统其余功能正常。'
    Write-Host ' 配置真实 Key：编辑 backend/.env 后重新运行本脚本。'
}

# ---- 3. compose up -d --build ----
Write-Step '构建镜像并启动服务（首次构建较慢：backend 镜像含 torch 约 2-3GB，属预期）...'
$upOutput = & docker compose up -d --build 2>&1
$upCode = $LASTEXITCODE
if ($upCode -ne 0) {
    $text = ($upOutput | Out-String)
    Write-Err "docker compose up 失败（退出码 $upCode）。"
    if ($text -match 'port is already allocated|address already in use|bind: An attempt was made') {
        Write-Host '原因：端口被占用（默认占用 5432/6380/8000/5173）。'
        Write-Host '解决指引：'
        Write-Host ' 1) 定位占用进程：netstat -ano | findstr ":8000"'
        Write-Host ' 2) 结束占用进程，或修改 docker-compose.yml 中对应端口映射后重新运行。'
    } elseif ($text -match 'pull access denied|manifest unknown|failed to resolve reference|toomanyrequests|429 Too Many Requests|dial tcp|TLS handshake timeout|network is unreachable') {
        Write-Host '原因：镜像拉取失败（网络 / 代理 / 镜像源问题）。'
        Write-Host '解决指引：'
        Write-Host ' 1) 检查网络与代理设置（Docker Desktop -> Settings -> Resources -> Proxies）。'
        Write-Host ' 2) 配置镜像加速器后重试，或手动 docker pull 对应镜像。'
    } elseif ($text -match 'failed to solve|npm ERR|pip') {
        Write-Host '原因：镜像构建失败（依赖安装 / 前端构建）。'
        Write-Host '解决指引：查看下方完整错误；前端构建失败检查 frontend/src 代码，后端依赖失败检查网络/源。'
    } else {
        Write-Host '未知错误，完整输出如下。'
    }
    Write-Host '--- 完整输出（末尾 40 行）---'
    $upOutput | Select-Object -Last 40 | ForEach-Object { Write-Host $_ }
    Write-Host '--- 诊断命令 ---'
    Write-Host ' docker compose ps'
    Write-Host ' docker compose logs backend'
    Write-Host ' docker compose logs frontend'
    Write-Host ' docker compose logs celery'
    exit 1
}
Write-Ok 'docker compose up 完成'

# ---- 4. 健康检查等待 ----
Write-Step '等待服务健康（最长 180 秒）...'
$deadline = (Get-Date).AddSeconds(180)
$apiOk = $false
$bHealth = ''
$fHealth = ''
while ((Get-Date) -lt $deadline) {
    try {
        $resp = Invoke-RestMethod -Uri 'http://localhost:8000/health' -TimeoutSec 5
        if ($resp.data.status -eq 'ok') { $apiOk = $true } else { $apiOk = $false }
    } catch {
        $apiOk = $false
    }
    $bHealth = (& docker inspect -f '{{.State.Health.Status}}' careerai-backend 2>$null | Select-Object -First 1)
    $fHealth = (& docker inspect -f '{{.State.Health.Status}}' careerai-frontend 2>$null | Select-Object -First 1)
    if ($apiOk -and $bHealth -eq 'healthy' -and $fHealth -eq 'healthy') { break }
    Start-Sleep -Seconds 3
}

if (-not ($apiOk -and $bHealth -eq 'healthy' -and $fHealth -eq 'healthy')) {
    Write-Err '服务未在预期时间内达到健康状态（backend /health 或容器健康检查未通过）。'
    Write-Host '--- docker compose ps ---'
    & docker compose ps
    Write-Host '--- 诊断命令 ---'
    Write-Host ' docker compose logs backend'
    Write-Host ' docker compose logs frontend'
    Write-Host ' docker compose logs celery'
    exit 1
}
Write-Ok '全部服务 healthy'

# ---- 5. 输出访问地址 ----
Write-Host ''
Write-Host '========================================' -ForegroundColor Green
Write-Host ' CareerAI 已启动' -ForegroundColor Green
Write-Host '========================================' -ForegroundColor Green
Write-Host ' 前端页面 : http://localhost:5173'
Write-Host ' 后端 API : http://localhost:8000'
Write-Host ' API 文档 : http://localhost:8000/docs'
Write-Host ' 健康检查 : http://localhost:8000/health'
Write-Host ''
Write-Host ' 停止服务 : .\stop.ps1'
Write-Host '========================================' -ForegroundColor Green
exit 0
