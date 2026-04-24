<#
.SYNOPSIS
  启动 Clash Verge → 设置代理环境变量 → 在当前终端启动 Codex CLI（可传参）。
#>
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CodexArgs
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
$CodexCli = $env:CODEX_CLI_EXE
if (-not $CodexCli) {
    $CodexCli = Join-Path $env:LOCALAPPDATA "Programs\OpenAI\Codex\bin\codex.exe"
}

if (-not (Test-Path $ClashExe)) { Write-Error "找不到 Clash Verge：$ClashExe" }
if (-not (Test-Path $CodexCli)) { Write-Error "找不到 Codex CLI：$CodexCli" }

if (-not (Get-Process -Name "clash-verge" -ErrorAction SilentlyContinue)) {
    Start-Process $ClashExe
    Start-Sleep -Seconds 6
}

$u = "http://127.0.0.1:$Port"
$env:HTTP_PROXY = $u
$env:HTTPS_PROXY = $u
$env:ALL_PROXY = $u

& $CodexCli @CodexArgs
