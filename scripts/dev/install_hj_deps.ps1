# ============================================================
# scripts/dev/install_hj_deps.ps1
# ============================================================
# HJ 환경 의존성 일괄 설치 + 검증 (venv → .venv 재생성 후 보정용).
#
# 실행:
#   PowerShell 우클릭 "관리자 권한으로 실행" 불필요. 일반 PowerShell:
#     PS> .\scripts\dev\install_hj_deps.ps1
#
# 동작:
#   1) .venv 활성화 확인 (없으면 즉시 안내 후 종료)
#   2) Python 3.10 검증 (ADR-001)
#   3) requirements/worker.txt 설치 (HJ 운영 의존성 — base+api+worker 모두 포함)
#   4) dev 도구 설치 (mypy / pre-commit / ipython)
#   5) outputs/ 모듈 import 스모크 테스트
#   6) pytest collect-only 로 테스트 수집 가능 여부 확인
#
# 수정 권한: HJ 단독.
# ============================================================

$ErrorActionPreference = "Stop"
$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'
$env:PYTHONUTF8 = "1"

# 색상 헬퍼
function Write-Step($msg)    { Write-Host "`n▶ $msg" -ForegroundColor Cyan }
function Write-Ok($msg)      { Write-Host "  ✓ $msg" -ForegroundColor Green }
function Write-Warn($msg)    { Write-Host "  ⚠ $msg" -ForegroundColor Yellow }
function Write-Err($msg)     { Write-Host "  ✗ $msg" -ForegroundColor Red }

# 프로젝트 루트로 이동 (스크립트 위치 기준)
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot
Write-Host "Repo: $repoRoot" -ForegroundColor DarkGray

# ─── 0. .venv 검증 ───
Write-Step "0/6 .venv 환경 검증"
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    Write-Err ".venv 가 없습니다. 먼저 다음을 실행하세요:"
    Write-Host "      py -3.10 -m venv .venv" -ForegroundColor White
    exit 1
}
Write-Ok ".venv/Scripts/python.exe 존재"

# Python 버전
$pyver = & $pythonExe --version 2>&1
if ($pyver -notmatch "Python 3\.10\.") {
    Write-Err "Python 버전 불일치: $pyver  (ADR-001 = 3.10 필수)"
    exit 1
}
Write-Ok "$pyver"

# ─── 1. pip 업그레이드 ───
Write-Step "1/6 pip 최신화"
& $pythonExe -X utf8 -m pip install -q --upgrade pip
if ($LASTEXITCODE -ne 0) { Write-Err "pip 업그레이드 실패"; exit 1 }
Write-Ok "pip 최신화 완료"

# ─── 2. worker.txt 설치 (base+api+worker 포함, outputs/ 캐리어 의존성 전부) ───
Write-Step "2/6 requirements/worker.txt 설치 (시간 소요 — torch/transformers 포함)"
& $pythonExe -X utf8 -m pip install -r "requirements\worker.txt"
if ($LASTEXITCODE -ne 0) {
    Write-Err "worker.txt 설치 중 오류 발생. 위 로그 확인."
    exit 1
}
Write-Ok "worker.txt 설치 완료"

# ─── 3. dev 도구 (dev.txt 에만 있는 것 — mypy/pre-commit/ipython) ───
Write-Step "3/6 개발 도구 설치 (mypy / pre-commit / ipython)"
& $pythonExe -X utf8 -m pip install `
    "mypy==1.10.0" `
    "pre-commit==3.7.1" `
    "ipython==8.24.0"
if ($LASTEXITCODE -ne 0) {
    Write-Err "개발 도구 설치 중 오류"; exit 1
}
Write-Ok "개발 도구 설치 완료"

# ─── 4. pip check (의존성 충돌 점검) ───
Write-Step "4/6 pip check (의존성 충돌 확인)"
& $pythonExe -X utf8 -m pip check
if ($LASTEXITCODE -ne 0) {
    Write-Warn "pip check 가 충돌을 보고했습니다. 위 메시지 확인 후 결정."
} else {
    Write-Ok "충돌 없음"
}

# ─── 5. outputs/ 스모크 import ───
Write-Step "5/6 outputs/ 캐리어 import 검증"
$smoke = @"
import importlib, sys
mods = ['pptx', 'reportlab', 'plotly', 'psutil', 'shap', 'optuna', 'openpyxl', 'pypdf', 'presidio_analyzer']
failed = []
for m in mods:
    try:
        importlib.import_module(m)
        print(f'  OK   {m}')
    except Exception as e:
        print(f'  FAIL {m}: {e.__class__.__name__}: {e}')
        failed.append(m)
sys.exit(1 if failed else 0)
"@
& $pythonExe -X utf8 -c $smoke
if ($LASTEXITCODE -ne 0) {
    Write-Warn "일부 모듈 import 실패 — 위 로그 확인"
} else {
    Write-Ok "outputs/ 핵심 의존성 모두 import OK"
}

# ─── 6. pytest 수집 ───
Write-Step "6/6 pytest --collect-only (테스트 수집만, 실행 X)"
& $pythonExe -X utf8 -m pytest --collect-only -q 2>&1 | Select-Object -Last 10
if ($LASTEXITCODE -ne 0) {
    Write-Warn "pytest collect 실패 — collection error 메시지 확인"
} else {
    Write-Ok "pytest 수집 OK"
}

Write-Host "`n─────────────────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host "✅ HJ 의존성 설치 + 검증 완료" -ForegroundColor Green
Write-Host "─────────────────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host "후속 정리:" -ForegroundColor White
Write-Host "  Remove-Item -Recurse -Force .venv_broken_rename" -ForegroundColor DarkGray
Write-Host ""
