# scripts/dev/register_kb_sync_task.ps1
# ADA KB cross-team puller ë¥?Windows ?‘ì—… ?¤ì?ì¤„ëŸ¬???±ë¡
#
# ?¬ìš©ë²?(PowerShell, ?¼ë°˜ ê¶Œí•œ?´ë©´ ?¬ìš©???ì—­ ?±ë¡ / ê´€ë¦¬ìë©??œìŠ¤???ì—­):
#   .\scripts\dev\register_kb_sync_task.ps1
#
# ?œê±° (?„ìš” ??:
#   .\scripts\dev\register_kb_sync_task.ps1 -Uninstall
#
# ?™ì‘:
#   1. ADA ?„ë¡œ?íŠ¸ ê²½ë¡œ ?ë™ ê°ì? (?¤í¬ë¦½íŠ¸ ?„ì¹˜ ê¸°ì?)
#   2. .venv\Scripts\python.exe ê°€ ?ˆìœ¼ë©?venv Python ?¬ìš© (ê¶Œì¥),
#      ?†ìœ¼ë©??œìŠ¤??python.exe ?´ë°±
#   3. ?˜ë£¨ 3??(8:00 / 14:00 / 21:00) `linux_kb_sync.py --mode=both` ?¤í–‰
#   4. ?´ë? ?±ë¡???ˆìœ¼ë©??¬ë“±ë¡?(??–´?°ê¸°)

[CmdletBinding()]
param(
    [switch]$Uninstall,
    [string]$TaskName = "ADA-KB-Sync",
    [string]$Description = "ADA SelfLearningKB cross-team puller (Day24)"
)

$ErrorActionPreference = "Stop"

# --- ê²½ë¡œ ê²°ì • ---------------------------------------------------------------
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
    Write-Host "[INFO] venv Python ?¬ìš©: $PythonExe" -ForegroundColor Cyan
} else {
    $PythonExe = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
    if (-not $PythonExe) {
        Write-Error ".venv\Scripts\python.exe ???†ê³  ?œìŠ¤??python.exe ???†ìŠµ?ˆë‹¤. ë¨¼ì? venv ë§Œë“¤ê±°ë‚˜ Python ?¤ì¹˜?˜ì„¸??"
        exit 1
    }
    Write-Host "[WARN] venv ?†ìŒ ???œìŠ¤??Python ?´ë°±: $PythonExe" -ForegroundColor Yellow
}

# --- Uninstall ---------------------------------------------------------------
if ($Uninstall) {
    try {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
        Write-Host "[OK] ?‘ì—… ?œê±° ?„ë£Œ: $TaskName" -ForegroundColor Green
    } catch {
        Write-Host "[INFO] ?±ë¡???‘ì—…???†ìŠµ?ˆë‹¤: $TaskName" -ForegroundColor Yellow
    }
    exit 0
}

# --- ?´ë? ?±ë¡???ˆìœ¼ë©??œê±° ???¬ë“±ë¡?-----------------------------------------
$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Existing) {
    Write-Host "[INFO] ê¸°ì¡´ ?±ë¡ ë°œê²¬ ???¬ë“±ë¡ì„ ?„í•´ ?œê±°" -ForegroundColor Yellow
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

# ?¸íŠ¸ë¶ì´ ?ˆì „ / ë°°í„°ë¦¬ì—¬???¤í–‰, ?¤íŒ¨ ???¬ì‹œ?? ì½˜ì†” ì°?????
$SettingsParams = @{
    AllowStartIfOnBatteries   = $true
    DontStopIfGoingOnBatteries = $true
    StartWhenAvailable        = $true
    RunOnlyIfNetworkAvailable = $true
    ExecutionTimeLimit        = (New-TimeSpan -Minutes 10)
    RestartCount              = 2
    RestartInterval           = (New-TimeSpan -Minutes 5)
}
$Settings = New-ScheduledTaskSettingsSet @SettingsParams

# ?¬ìš©??ê¶Œí•œ?¼ë¡œ ?±ë¡ (ê´€ë¦¬ì ê¶Œí•œ ë¶ˆí•„??
$Principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

# --- ?±ë¡ --------------------------------------------------------------------
try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Description $Description `
        -Action $Action `
        -Trigger $Triggers `
        -Settings $Settings `
        -Principal $Principal | Out-Null

    Write-Host ""
    Write-Host "[OK] ?‘ì—… ?¤ì?ì¤„ëŸ¬ ?±ë¡ ?„ë£Œ" -ForegroundColor Green
    Write-Host "     ?´ë¦„      : $TaskName"
    Write-Host "     Python    : $PythonExe"
    Write-Host "     ?¤í¬ë¦½íŠ¸  : $SyncScript"
    Write-Host "     ?¤ì?ì¤?   : ë§¤ì¼ 08:00 / 14:00 / 21:00"
    Write-Host ""
    Write-Host "?¤ìŒ ?¤í–‰ ?•ì¸:"
    Write-Host "  Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
    Write-Host ""
    Write-Host "ì§€ê¸???ë²??œí—˜ ?¤í–‰:"
    Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
    Write-Host ""
    Write-Host "?œê±°?˜ë ¤ë©?"
    Write-Host "  .\scripts\dev\register_kb_sync_task.ps1 -Uninstall"
} catch {
    Write-Error "?±ë¡ ?¤íŒ¨: $_"
    exit 1
}
