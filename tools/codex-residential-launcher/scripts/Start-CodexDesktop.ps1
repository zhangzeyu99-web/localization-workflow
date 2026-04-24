<#
.SYNOPSIS
  启动 Clash Verge（如未运行）→ 等待本地 mixed-port → 为子进程设置 HTTP 代理 → 启动 Codex Desktop。

.DESCRIPTION
  Codex Desktop 的 Electron 主进程可能直连；真正调 OpenAI 的是 resources\codex.exe 子进程，
  该子进程会继承本脚本设置的 HTTPS_PROXY/HTTP_PROXY，从而走 127.0.0.1:<port> → Clash 规则 → 住宅 IP。

  不使用 TUN：避免影响公司网/全局 DNS；仅 Codex 树内走代理。

.PARAMETER KillExisting
  启动前结束已有 Codex Desktop，避免多实例争用 refresh token。
#>
param(
    [switch]$KillExisting
)

$ErrorActionPreference = "Stop"

function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return }
    Get-Content $Path -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $i = $line.IndexOf("=")
        if ($i -lt 1) { return }
        $k = $line.Substring(0, $i).Trim()
        $v = $line.Substring($i + 1).Trim()
        [System.Environment]::SetEnvironmentVariable($k, $v, "Process")
    }
}

Import-DotEnv (Join-Path (Split-Path $PSScriptRoot) ".env")

$ClashExe = $env:CLASH_VERGE_EXE
if (-not $ClashExe) { $ClashExe = "${env:ProgramFiles}\Clash Verge\clash-verge.exe" }
$Port = [int]($env:CLASH_MIXED_PORT)
if (-not $Port) { $Port = 7897 }

$CodexDesktop = $env:CODEX_DESKTOP_EXE
if (-not $CodexDesktop) {
    $CodexDesktop = Join-Path $env:LOCALAPPDATA "Programs\OpenAI\CodexDesktop\Codex.exe"
}

if (-not (Test-Path $ClashExe)) {
    Write-Error "找不到 Clash Verge：$ClashExe 。请安装或设置 CLASH_VERGE_EXE（见 env.example）。"
}
if (-not (Test-Path $CodexDesktop)) {
    Write-Error "找不到 Codex Desktop：$CodexDesktop 。请安装或设置 CODEX_DESKTOP_EXE。"
}

$proxyUrl = "http://127.0.0.1:$Port"

$cv = Get-Process -Name "clash-verge" -ErrorAction SilentlyContinue
if (-not $cv) {
    Write-Host "[*] 正在启动 Clash Verge..." -ForegroundColor Yellow
    Start-Process -FilePath $ClashExe
    $deadline = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $deadline) {
        $ok = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($ok) { break }
        Start-Sleep -Milliseconds 400
    }
    if (-not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
        Write-Error "等待本地端口 $Port 超时。请在 Clash Verge 中确认 mixed-port。"
    }
    Write-Host "[OK] Clash Verge 已就绪（监听 $Port）" -ForegroundColor Green
} else {
    Write-Host "[OK] Clash Verge 已在运行" -ForegroundColor Green
}

if ($KillExisting) {
    Get-Process -Name "Codex" -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -like "*CodexDesktop*" } |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

$env:HTTP_PROXY = $proxyUrl
$env:HTTPS_PROXY = $proxyUrl
$env:ALL_PROXY = $proxyUrl

Write-Host "[OK] 子进程代理: $proxyUrl（仅本进程树；不影响系统浏览器）" -ForegroundColor Cyan
Start-Process -FilePath $CodexDesktop
Write-Host "[OK] 已启动 Codex Desktop" -ForegroundColor Green
