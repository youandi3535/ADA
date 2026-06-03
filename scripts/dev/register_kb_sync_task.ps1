# scripts/dev/register_kb_sync_task.ps1
# ADA KB cross-team puller 를 Windows 작업 스케줄러에 등록
#
# 사용법 (PowerShell, 일반 권한이면 사용자 영역 등록 / 관리자면 시스템 영역):
#   .\scripts\dev\register_kb_sync_task.ps1
#
# 제거 (필요 시):
#   .\scripts\dev\register_kb_sync_task.ps1 -Uninstall
#
# 동작:
#   1. ADA 프로젝트 경로 자동 감지 (스크립트 위치 기준)
#   2. .venv\Scripts\python.exe 가 있으면 venv Python 사용 (권장),
#      없으면 시스템 python.exe 폴백
#   3. 하루 3회 (8:00 / 14:00 / 21:00) `linux_kb_sync.py --mode=both` 실행
#   4. 이미 등록돼 있으면 재등록 (덮어쓰기)

[CmdletBinding()]
param(
    [switch]$Uninstall,
    [string]$TaskName = "ADA-KB-Sync",
    [string]$Description = "ADA SelfLearningKB cross-team puller (Day24)"
)

$ErrorActionPreference = "Stop"

# --- 경로 결정 ---------------------------------------------------------------
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$SyncScript = Join-Path $ProjectRoot "scripts\linux_kb_sync.py"

if (-not (Test-Path $SyncScript)) {
    Write-Error "linux_kb_sync.py not found at: $SyncScript"
    exit 1
}

if (Test-Path $VenvPython) {
    $PythonExe = $VenvPython
    Write-Host "[INFO] venv Python 사용: $PythonExe" -ForegroundColor Cyan
} else {
    $PythonExe = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
    if (-not $PythonExe) {
        Write-Error ".venv\Scripts\python.exe 도 없고 시스템 python.exe 도 없습니다. 먼저 venv 만들거나 Python 설치하세요."
        exit 1
    }
    Write-Host "[WARN] venv 없음 → 시스템 Python 폴백: $PythonExe" -ForegroundColor Yellow
}

# --- Uninstall ---------------------------------------------------------------
if ($Uninstall) {
    try {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
        Write-Host "[OK] 작업 제거 완료: $TaskName" -ForegroundColor Green
    } catch {
        Write-Host "[INFO] 등록된 작업이 없습니다: $TaskName" -ForegroundColor Yellow
    }
    exit 0
}

# --- 이미 등록돼 있으면 제거 후 재등록 -----------------------------------------
$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Existing) {
    Write-Host "[INFO] 기존 등록 발견 → 재등록을 위해 제거" -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# --- Action / Trigger / Settings ---------------------------------------------
$Action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "`"$SyncScript`" --mode=both" `
    -WorkingDirectory $ProjectRoot

$Triggers = @(
    New-ScheduledTaskTrigger -Daily -At 8:00am
    New-ScheduledTaskTrigger -Daily -At 2:00pm
    New-ScheduledTaskTrigger -Daily -At 9:00pm
)

# 노트북이 절전 / 배터리여도 실행, 실패 시 재시도, 콘솔 창 안 뜸
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 5)

# 사용자 권한으로 등록 (관리자 권한 불필요)
$Principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

# --- 등록 --------------------------------------------------------------------
try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Description $Description `
        -Action $Action `
        -Trigger $Triggers `
        -Settings $Settings `
        -Principal $Principal | Out-Null

    Write-Host ""
    Write-Host "[OK] 작업 스케줄러 등록 완료" -ForegroundColor Green
    Write-Host "     이름      : $TaskName"
    Write-Host "     Python    : $PythonExe"
    Write-Host "     스크립트  : $SyncScript"
    Write-Host "     스케줄    : 매일 08:00 / 14:00 / 21:00"
    Write-Host ""
    Write-Host "다음 실행 확인:"
    Write-Host "  Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
    Write-Host ""
    Write-Host "지금 한 번 시험 실행:"
    Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
    Write-Host ""
    Write-Host "제거하려면:"
    Write-Host "  .\scripts\dev\register_kb_sync_task.ps1 -Uninstall"
} catch {
    Write-Error "등록 실패: $_"
    exit 1
}
