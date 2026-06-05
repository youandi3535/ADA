#Requires -Version 5.0
<#
.SYNOPSIS
    Ollama 최적화 환경변수를 Windows 사용자 환경에 영구 등록.

.DESCRIPTION
    setx 명령으로 환경변수를 사용자 레벨에 영구 저장 → 재부팅·로그인 후에도 유지.
    이후 Ollama 데스크톱 앱·서비스가 자동 환경변수 읽음.

    적용 후 반드시:
      1. 현재 PowerShell 창 닫고 새로 열어야 변수 반영
      2. Ollama 서버 (시스템 트레이 아이콘 우클릭 → Quit) 종료
      3. Ollama 다시 시작 (시작 메뉴 또는 ollama serve)

.NOTES
    setx 는 관리자 권한 불필요 (사용자 환경변수 등록).
    시스템 전체 적용하려면 [Machine] 으로 변경하고 관리자 권한 필요.

.EXAMPLE
    PS> .\scripts\dev\register_ollama_env_permanent.ps1
#>

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  Ollama 최적화 환경변수 영구 등록 (사용자 레벨)" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan

$vars = @{
    "OLLAMA_NUM_PARALLEL"      = "2"
    "OLLAMA_KEEP_ALIVE"        = "30m"
    "OLLAMA_FLASH_ATTENTION"   = "1"
    "OLLAMA_MAX_LOADED_MODELS" = "1"
}

foreach ($key in $vars.Keys) {
    $value = $vars[$key]
    [Environment]::SetEnvironmentVariable($key, $value, "User")
    Write-Host "  [OK] $key = $value" -ForegroundColor Green
}

Write-Host ""
Write-Host "================================================================" -ForegroundColor Yellow
Write-Host "  적용 완료. 다음 단계:" -ForegroundColor Yellow
Write-Host "================================================================" -ForegroundColor Yellow
Write-Host "  1. 이 PowerShell 창 닫고 새 창 열기" -ForegroundColor White
Write-Host "  2. 시스템 트레이 → Ollama 아이콘 우클릭 → Quit Ollama" -ForegroundColor White
Write-Host "  3. 시작 메뉴에서 'Ollama' 검색해서 다시 실행" -ForegroundColor White
Write-Host "     (또는 새 터미널에서: ollama serve)" -ForegroundColor White
Write-Host ""
Write-Host "  검증:" -ForegroundColor Cyan
Write-Host "    Get-ChildItem env: | Where-Object Name -like 'OLLAMA_*'" -ForegroundColor Gray
Write-Host ""
