# scripts/dev/setup_team_kb.ps1
# ADA 팀 KB 수집·학습 원클릭 셋업 (팀원용)
#
# 하는 일:
#   1) .env 에 KB 수집 3줄 설정 (KB_SERVER_URL / KB_COLLECT_SECRET / KB_SYNC_DATABASE_URL)
#      - KB_SYNC_DATABASE_URL 은 본인 .env 의 POSTGRES_USER/PASSWORD/포트/DB 를 읽어 자동 생성
#        → 팀원마다 비번이 달라도 불일치 없음 (복붙의 함정 제거)
#   2) ADA-IngestHistory 작업 등록 (5분 주기, Cowork+과거이력 수집)
#   3) ADA-KB-Sync 작업 등록 (크로스팀 KB 동기화) — register_kb_sync_task.ps1 재사용
#   4) 결과 검증 출력
#
# 사용법 (PowerShell, 관리자 권한 불필요):
#   .\scripts\dev\setup_team_kb.ps1 -Secret "팀에서_받은_KB_COLLECT_SECRET"
#
# 옵션:
#   -ServerUrl   기본 https://ada-aiagent.com/api  (IP 직접은 SSL 실패하므로 도메인 고정)
#   -SkipSync    크로스팀 KB 동기화(ADA-KB-Sync) 등록 생략
#
# 사전 조건: 본인 PC 에서 docker 스택(postgres) 이 떠 있어야 KB_SYNC 가 동작.
#            (실시간 수집 KB_SERVER_URL/SECRET 은 docker 없어도 동작)

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Secret,
    [string]$ServerUrl = "https://ada-aiagent.com/api",
    [switch]$SkipSync
)

$ErrorActionPreference = "Stop"

# --- 경로 ---------------------------------------------------------------------
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$EnvPath     = Join-Path $ProjectRoot ".env"
$VenvPython  = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $EnvPath)) {
    Write-Error ".env 가 없습니다: $EnvPath  (먼저 .env 를 만들어 주세요)"
    exit 1
}
$PythonExe = if (Test-Path $VenvPython) { $VenvPython } else { (Get-Command python.exe -EA SilentlyContinue).Source }
if (-not $PythonExe) { Write-Error "python.exe 를 찾을 수 없습니다 (.venv 또는 시스템 Python 필요)"; exit 1 }

# --- .env 읽기 헬퍼 -----------------------------------------------------------
$envLines = Get-Content $EnvPath -Encoding UTF8

function Get-EnvVal([string]$key, [string]$default) {
    foreach ($l in $envLines) {
        if ($l -match "^\s*$([regex]::Escape($key))\s*=\s*(.+?)\s*$") {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return $default
}

# POSTGRES_* 자동 추출 (없으면 ADA 표준 기본값)
$pgUser = Get-EnvVal "POSTGRES_USER" "autoai"
$pgPass = Get-EnvVal "POSTGRES_PASSWORD" "devpassword1234"
$pgDb   = Get-EnvVal "POSTGRES_DB" "autoai"
$pgPort = Get-EnvVal "POSTGRES_HOST_PORT" "5433"   # docker-compose published 포트 기본 5433

$SyncDbUrl = "postgresql://${pgUser}:${pgPass}@localhost:${pgPort}/${pgDb}"

# --- .env upsert (BOM 없는 UTF-8 로 저장 → python dotenv 파서 호환) ----------
function Set-EnvVar([string]$key, [string]$value) {
    $pattern  = "^\s*#?\s*$([regex]::Escape($key))\s*="
    $newline  = "$key=$value"
    $replaced = $false
    $out = New-Object System.Collections.Generic.List[string]
    foreach ($l in $script:envLines) {
        if ($l -match $pattern) {
            if (-not $replaced) { $out.Add($newline); $replaced = $true }
            # 중복 줄은 버림
        } else {
            $out.Add($l)
        }
    }
    if (-not $replaced) { $out.Add($newline) }
    $script:envLines = $out
}

Set-EnvVar "KB_SERVER_URL"        $ServerUrl
Set-EnvVar "KB_COLLECT_SECRET"    $Secret
Set-EnvVar "KB_SYNC_DATABASE_URL" $SyncDbUrl

# BOM 없는 UTF-8 로 기록
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($EnvPath, $script:envLines, $utf8NoBom)

Write-Host "[OK] .env 설정 완료" -ForegroundColor Green
Write-Host "     KB_SERVER_URL        = $ServerUrl"
Write-Host "     KB_COLLECT_SECRET    = ****(설정됨)"
Write-Host "     KB_SYNC_DATABASE_URL = postgresql://${pgUser}:****@localhost:${pgPort}/${pgDb}"

# --- ADA-IngestHistory 등록 (5분 주기) ---------------------------------------
$IngestScript = Join-Path $ProjectRoot "scripts\ingest_history.py"
$action  = New-ScheduledTaskAction -Execute $PythonExe -Argument "-X utf8 `"$IngestScript`"" -WorkingDirectory $ProjectRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName "ADA-IngestHistory" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "ADA Cowork/Claude Code 대화이력 5분 주기 수집" -Force | Out-Null
Write-Host "[OK] ADA-IngestHistory 등록 (5분 주기)" -ForegroundColor Green

# --- ADA-KB-Sync 등록 (크로스팀 동기화) — 기존 스크립트 재사용 ---------------
if (-not $SkipSync) {
    $SyncRegister = Join-Path $ScriptDir "register_kb_sync_task.ps1"
    if (Test-Path $SyncRegister) {
        & $SyncRegister
        Write-Host "[OK] ADA-KB-Sync 등록 (register_kb_sync_task.ps1)" -ForegroundColor Green
    } else {
        Write-Host "[WARN] register_kb_sync_task.ps1 없음 → ADA-KB-Sync 수동 등록 필요" -ForegroundColor Yellow
    }
}

# --- 검증 --------------------------------------------------------------------
Write-Host ""
Write-Host "=== 등록된 작업 ===" -ForegroundColor Cyan
Get-ScheduledTask -TaskName "ADA-IngestHistory", "ADA-KB-Sync" -EA SilentlyContinue | Select-Object TaskName, State | Format-Table -AutoSize

Write-Host "다음 단계:" -ForegroundColor Cyan
Write-Host "  1) Claude Code 를 재시작하세요 (Stop/PostToolUse hook 활성화)."
Write-Host "  2) 즉시 한 번 백필하려면:  $PythonExe -X utf8 scripts\ingest_history.py --force --limit 5"
Write-Host "     → 'ok=5  fail=0' 이면 수집 정상."
