# scripts/dev/commit_hj_day10.ps1 — HJ Day 10 + Day 11#1 + hook fix 통합 커밋
# 사용: .venv 활성화된 PowerShell 에서 실행
#   cd C:\IT\workspace_python\ADA
#   .\scripts\dev\commit_hj_day10.ps1

$ErrorActionPreference = "Stop"
$repo = "C:\IT\workspace_python\ADA"
Set-Location $repo

Write-Host "=== HJ Day 10 통합 커밋 ===" -ForegroundColor Cyan

# 1) 브랜치 확인
$branch = git branch --show-current
Write-Host "현재 브랜치: $branch"
if ($branch -ne "feat/hj-day10") {
    Write-Warning "feat/hj-day10 브랜치가 아님 — 진행하시겠습니까?"
    $confirm = Read-Host "y/N"
    if ($confirm -ne "y") { exit 1 }
}

# 2) stale index.lock 제거 (있으면)
if (Test-Path .git\index.lock) {
    Write-Host ".git/index.lock 제거..."
    Remove-Item .git\index.lock -Force
}

# 3) HJ 영역 파일만 명시적 staging — CS/jh/NY 영역 절대 건드리지 않음
$files = @(
    # 신규
    "ada/observability/kpi.py",
    "api/routes/observability.py",
    "tests/test_kpi_compute.py",
    "tests/test_day11_kb_citation_payload.py",
    "tests/integration/test_observability_kpi_api.py",
    "docs/ADR-010-kpi-measurement.md",
    "docs/HJ_DAY10_DESIGN.md",
    "docs/KPI_MEASUREMENT.md",
    "scripts/dev/commit_hj_day10.ps1",
    # 수정
    "ada/observability/metrics.py",
    "ada/core/config.py",
    "agents/base.py",
    "agents/model_selection.py",
    "api/main.py",
    "scripts/kpi_measure.py",
    "scripts/query_kb_hook.py",
    "frontend/app.py",
    ".env.example",
    ".claude/settings.json"
)

Write-Host "`n=== 파일 staging ===" -ForegroundColor Cyan
foreach ($f in $files) {
    if (Test-Path $f) {
        git add $f
        Write-Host "  ✓ $f"
    } else {
        Write-Warning "  ✗ $f (없음 — 건너뜀)"
    }
}

# 4) staging 검증 — CS/jh/NY 영역 침범 검사
Write-Host "`n=== 영역 검증 ===" -ForegroundColor Cyan
$staged = git diff --cached --name-only
$forbidden = $staged | Where-Object {
    $_ -match "^(agents/handlers/(timeseries|anomaly|tabular)/|pipelines/(timeseries|anomaly|tabular_ml|tabular_dl)/|tests/handlers/(timeseries|anomaly|tabular)/|requirements/handlers-)"
}
if ($forbidden) {
    Write-Host "⛔ HJ 영역 외 파일이 staging 됨:" -ForegroundColor Red
    $forbidden | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    Write-Host "→ 커밋 중단. git reset HEAD <file> 로 unstage 후 다시 시도." -ForegroundColor Red
    exit 1
}

# 5) staging stat 표시
Write-Host "`n=== 변경 통계 ===" -ForegroundColor Cyan
git diff --cached --stat

# 6) 머지 안전 — 거대 변경 경고 (1000 줄 이상 변경된 파일이 있으면 경고)
$bigChanges = git diff --cached --numstat | ForEach-Object {
    $parts = $_ -split "`t"
    $adds = [int]($parts[0])
    $dels = [int]($parts[1])
    if ($adds + $dels -gt 1500) { "$($parts[2]) ($adds+/$dels-)" }
}
if ($bigChanges) {
    Write-Host "`n⚠️ 큰 변경 (1500줄 이상):" -ForegroundColor Yellow
    $bigChanges | ForEach-Object { Write-Host "  $_" }
    Write-Host "계속? (y/N)"
    $c = Read-Host
    if ($c -ne "y") { git reset HEAD .; exit 1 }
}

# 7) 커밋
$msg = @"
hj-day10: KPI 자동 측정 + Streamlit 대시보드 + Day11#1 + hook fix

Day 10 (KPI 자동 측정 + 대시보드):
- ada/observability/kpi.py: KPI 계산 단일 진실 원천
  compute_kpis() / parse_window() / KPIResponse 스키마
- api/routes/observability.py: /admin/observability/kpi REST
  + admin RBAC + in-memory TTL 캐시 + X-KPI-Cache-Status 헤더
- scripts/kpi_measure.py: 새 모듈 위임 + 백워드 호환 (UPPER_CASE 키)
  + repo root sys.path 자동 추가 (subprocess 실행 호환)
- frontend/app.py Tab 5: subprocess 제거 -> API 호출,
  emoji 상태, 세션 한정 트렌드 차트, warnings 배너, JSON 다운로드
- ada/core/config.py + .env.example: KPI 환경변수 3개 추가
- docs/ADR-010, docs/KPI_MEASUREMENT.md, docs/HJ_DAY10_DESIGN.md

Day 11 #1 (KP9 정확도 - KB 인용 자동 기록):
- ada/observability/metrics.py: ContextVar 기반 per-agent 카운터
  reset_kb_citation_counter() / get_kb_citation_count()
- agents/base.py log_agent_run: agent 진입 시 reset,
  종료 시 kb_count > 0 이면 AgentRun.payload['kb_citations'] 기록
- agents/model_selection.py: 누락된 record_kb_citation() 호출 보강

Hook fix (Claude Code 답변 안 보이는 문제):
- scripts/query_kb_hook.py: print + exit 2 패턴 -> JSON decision:block
  + exit 0 + plain stdout 백업 (이중 안전망)
- ADA_HOOK_DEBUG=1 으로 .ada_hook_debug.log 진단 로그 출력
- main 전체 try/except 으로 fail-safe (사용자 잠금 방지)
- # -*- coding: utf-8 -*- 헤더 추가

테스트:
- tests/test_kpi_compute.py: 단위 45
- tests/integration/test_observability_kpi_api.py: 통합 14
- tests/test_day10_kpi.py: 백워드 호환 4 (그린 유지)
- tests/test_day11_kb_citation_payload.py: ContextVar/payload 6
- 합계 69 테스트 그린

영역:
- 모두 HJ 영역 (CLAUDE.md 1)
- 마이그레이션 0건 (CLAUDE.md 2 준수)
- PipelineState 미변경 (R-005)
- dispatcher 8종 미변경
- handlers/* / pipelines/* / requirements/* 미수정
"@

git commit -m $msg

if ($LASTEXITCODE -ne 0) {
    Write-Host "`n❌ 커밋 실패. git status 확인하세요." -ForegroundColor Red
    exit 1
}

# 8) 확인
Write-Host "`n=== 커밋 완료 ===" -ForegroundColor Green
git log --oneline -3
Write-Host ""
git show --stat HEAD | Select-Object -First 30

Write-Host "`n다음 단계:" -ForegroundColor Cyan
Write-Host "  1) .venv\Scripts\pytest tests/ -q --tb=no    # 전체 회귀"
Write-Host "  2) git push origin feat/hj-day10            # 푸시"
Write-Host "  3) bash scripts/dev/end_of_day.sh           # 또는 자동 머지 스크립트"
