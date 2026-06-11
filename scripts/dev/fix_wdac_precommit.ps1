# UTF-8 console output (prevents garbled Korean on Windows PowerShell 5.1)
chcp 65001 | Out-Null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# =============================================================================
# fix_wdac_precommit.ps1
# Smart App Control (SAC) 차단으로 인한 pre-commit 훅 실행 불가 문제 해결
#
# 증상:  git commit 시 "check for added large files" 훅에서
#        [WinError 4551] 애플리케이션 제어 정책에서 이 파일을 차단했습니다
#
# 원인:  Smart App Control(SAC) ON 상태 → 서명 없는 로컬 .exe 차단
#        (pre-commit 캐시의 Python 래퍼 .exe 들은 서명 없음)
#
# 조치:  SAC를 Evaluation 모드로 전환
#        - Evaluation: 차단하지 않고 적합성만 평가
#        - 개발자 머신(서명 없는 툴 다수)에서는 자동으로 Off 전환됨
#        - 수동 Off(값=0)와 달리 OS가 자동 결정 → 덜 파괴적
#
# 실행:  관리자 PowerShell에서 실행 필요
#        .\scripts\dev\fix_wdac_precommit.ps1
#
# 재부팅: 변경 후 반드시 재부팅해야 적용됨
# =============================================================================

# 관리자 권한 확인
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "관리자 권한으로 실행해야 합니다. PowerShell을 '관리자 권한으로 실행' 후 다시 시도하세요."
    exit 1
}

$regPath = "HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy"
$valueName = "VerifiedAndReputablePolicyState"

# 현재 상태 확인
$current = (Get-ItemProperty -Path $regPath -Name $valueName -ErrorAction SilentlyContinue).$valueName
Write-Host "[현재 SAC 상태] $valueName = $current" -ForegroundColor Cyan
switch ($current) {
    0 { Write-Host "  → Off (이미 비활성화됨. 재부팅 없이 pre-commit이 동작해야 합니다.)" -ForegroundColor Yellow }
    1 { Write-Host "  → On (차단 활성화 — 이것이 원인)" -ForegroundColor Red }
    2 { Write-Host "  → Evaluation (이미 평가 모드. 재부팅 후 동작 확인 필요)" -ForegroundColor Yellow }
}

if ($current -eq 0 -or $current -eq 2) {
    Write-Host "`nSAC가 이미 비활성화 또는 평가 모드입니다. 추가 조치 불필요." -ForegroundColor Green
    Write-Host "여전히 문제가 있다면 재부팅 후 다시 시도하세요."
    exit 0
}

# Evaluation 모드로 전환 (1 → 2)
Write-Host "`n[변경] SAC On(1) → Evaluation(2) 으로 전환합니다..." -ForegroundColor Cyan
try {
    Set-ItemProperty -Path $regPath -Name $valueName -Value 2 -Type DWord -Force
    $after = (Get-ItemProperty -Path $regPath -Name $valueName).$valueName
    if ($after -eq 2) {
        Write-Host "[완료] SAC가 Evaluation 모드로 변경되었습니다." -ForegroundColor Green
    } else {
        Write-Error "값 변경 실패: 현재 값 = $after"
        exit 1
    }
} catch {
    Write-Error "레지스트리 쓰기 실패: $($_.Exception.Message)"
    exit 1
}

Write-Host @"

===================================================
 다음 단계
===================================================
 1. PC를 재부팅하세요 (변경 사항 적용)
 2. 재부팅 후 다음 명령으로 커밋 재시도:
      git commit -m "커밋 메시지"

 참고:
   - Evaluation 모드에서 Windows가 개발자 환경을 감지하면
     자동으로 SAC Off(영구 비활성화)로 전환됩니다.
   - pre-commit 캐시 위치: $env:USERPROFILE\.cache\pre-commit\
===================================================
"@ -ForegroundColor Green