#Requires -Version 5.0
<#
.SYNOPSIS
    Ollama 최적화 환경변수를 Windows 사용자 환경에 영구 등록.
.EXAMPLE
    PS> .\scripts\dev\register_ollama_env_permanent.ps1
#>

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  Ollama 환경변수 영구 등록 (사용자 레벨)" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan

function Set-OllamaVar($name, $value) {
    [Environment]::SetEnvironmentVariable($name, $value, "User")
    Write-Host "  [OK] $name = $value" -ForegroundColor Green
}

Set-OllamaVar "OLLAMA_KEEP_ALIVE"        "30m"
Set-OllamaVar "OLLAMA_FLASH_ATTENTION"   "1"
Set-OllamaVar "OLLAMA_MAX_LOADED_MODELS" "1"
Set-OllamaVar "OLLAMA_NUM_PARALLEL"      "1"
# HJ 2026-06-09 G1 단축 W — KV cache 양자화 (메모리 절반, 처리 약간 ↑).
# f16(기본) → q8_0: 정확도 손실 거의 0, KV cache 메모리 50% 절감, prompt cache hit 률 ↑.
Set-OllamaVar "OLLAMA_KV_CACHE_TYPE"     "q8_0"

Write-Host ""
Write-Host "================================================================" -ForegroundColor Yellow
Write-Host "  적용 완료. 다음 단계:" -ForegroundColor Yellow
Write-Host "================================================================" -ForegroundColor Yellow
Write-Host "  1. 이 PowerShell 창 닫고 새 창 열기" -ForegroundColor White
Write-Host "  2. 시스템 트레이 -> Ollama 아이콘 우클릭 -> Quit Ollama" -ForegroundColor White
Write-Host "  3. 시작 메뉴에서 'Ollama' 검색해서 다시 실행" -ForegroundColor White
Write-Host ""
Write-Host "  검증:" -ForegroundColor Cyan
Write-Host "    Get-ChildItem env: | Where-Object Name -like 'OLLAMA_*'" -ForegroundColor Gray
Write-Host ""
