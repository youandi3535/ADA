#Requires -Version 5.0
<#
.SYNOPSIS
    Ollama 서버를 ADA v2 최적화 설정으로 시작.

.DESCRIPTION
    Phase 1 — Ollama 서버 환경변수 (속도 튜닝):
      - NUM_PARALLEL=2          → DataProfiler·ReportComposer gather 실제 병렬화
      - KEEP_ALIVE=30m          → 모델 메모리 유지 (게이트 간 재로드 비용 제거)
      - FLASH_ATTENTION=1       → 어텐션 연산 최적화 (~10–20%↑)
      - MAX_LOADED_MODELS=1     → 같은 모델 1개만 적재 (RAM 절약)

    예상 효과: 전체 분석 시간 20~30% 단축.

.NOTES
    이 스크립트는 "현재 세션" 에만 적용됨. 영구 등록은:
      scripts/dev/register_ollama_env_permanent.ps1
    또는 시스템 환경변수 → 사용자 변수에 직접 추가.

    기존 ollama 프로세스가 실행 중이면 먼저 종료해야 환경변수 반영됨.

.EXAMPLE
    PS> .\scripts\dev\start_ollama_optimized.ps1
#>

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  ADA v2 — Ollama 최적화 시작 (Phase 1)" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan

# ── 1. 기존 ollama 프로세스 종료 ─────────────────────────────────────
$existing = Get-Process -Name "ollama*" -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[1/3] 기존 ollama 프로세스 종료 중..." -ForegroundColor Yellow
    $existing | Stop-Process -Force
    Start-Sleep -Seconds 2
} else {
    Write-Host "[1/3] 실행 중인 ollama 프로세스 없음 — 건너뜀." -ForegroundColor Gray
}

# ── 2. 환경변수 세팅 ────────────────────────────────────────────────
Write-Host "[2/3] 최적화 환경변수 설정..." -ForegroundColor Yellow

$env:OLLAMA_NUM_PARALLEL = "2"
$env:OLLAMA_KEEP_ALIVE = "30m"
$env:OLLAMA_FLASH_ATTENTION = "1"
$env:OLLAMA_MAX_LOADED_MODELS = "1"

Write-Host "    OLLAMA_NUM_PARALLEL      = $($env:OLLAMA_NUM_PARALLEL)" -ForegroundColor Green
Write-Host "    OLLAMA_KEEP_ALIVE        = $($env:OLLAMA_KEEP_ALIVE)" -ForegroundColor Green
Write-Host "    OLLAMA_FLASH_ATTENTION   = $($env:OLLAMA_FLASH_ATTENTION)" -ForegroundColor Green
Write-Host "    OLLAMA_MAX_LOADED_MODELS = $($env:OLLAMA_MAX_LOADED_MODELS)" -ForegroundColor Green

# ── 3. Ollama 서버 시작 ─────────────────────────────────────────────
Write-Host "[3/3] ollama serve 시작..." -ForegroundColor Yellow
Write-Host ""
Write-Host "  >> 이 창을 닫지 마세요. Ctrl+C 로 종료." -ForegroundColor Cyan
Write-Host "  >> 다른 터미널에서: curl http://localhost:11434/api/tags" -ForegroundColor Cyan
Write-Host ""

ollama serve
