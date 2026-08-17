<#
.SYNOPSIS
CareerAI 一键停止（容器化）：docker compose down（默认保留 PG/Redis 数据卷）。

.DESCRIPTION
在项目根目录下执行。默认保留数据卷（下次 start.ps1 数据仍在）；
加 -RemoveVolumes 会连数据卷一并删除（PG/Redis 数据将清空）。

.EXAMPLE
.\stop.ps1
.\stop.ps1 -RemoveVolumes
#>
[CmdletBinding()]
param(
    [switch]$RemoveVolumes
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host '[错误] 未检测到 docker 命令。' -ForegroundColor Red
    exit 1
}

if ($RemoveVolumes) {
    docker compose down -v
} else {
    docker compose down
}

if ($LASTEXITCODE -eq 0) {
    Write-Host '[OK] 服务已停止（数据卷已保留）。如需连数据一并删除：.\stop.ps1 -RemoveVolumes' -ForegroundColor Green
} else {
    Write-Host '[错误] docker compose down 失败，见上方输出。' -ForegroundColor Red
    exit 1
}