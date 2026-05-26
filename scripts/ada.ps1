# ADA Docker 단축 명령어 (PowerShell)
# VS Code 터미널에서 로드: . .\scriptsda.ps1

$ADA_ROOT = "C:\IT\workspace_python\ADA"

function ada-up {
    Write-Host "[ADA] 컨테이너 시작..." -ForegroundColor Cyan
    docker compose -f "$ADA_ROOT\docker\docker-compose.yml" --env-file "$ADA_ROOT\.env" --profile core up -d --pull never
}

function ada-down {
    Write-Host "[ADA] 컨테이너 종료..." -ForegroundColor Yellow
    docker compose -f "$ADA_ROOT\docker\docker-compose.yml" --env-file "$ADA_ROOT\.env" --profile core down
}

function ada-ps {
    docker compose -f "$ADA_ROOT\docker\docker-compose.yml" --env-file "$ADA_ROOT\.env" ps
}

function ada-logs {
    param(
        [string]$Service = ""
    )
    if ($Service -ne "") {
        docker compose -f "$ADA_ROOT\docker\docker-compose.yml" --env-file "$ADA_ROOT\.env" logs -f $Service
    } else {
        docker compose -f "$ADA_ROOT\docker\docker-compose.yml" --env-file "$ADA_ROOT\.env" logs -f
    }
}

function ada-build {
    Write-Host "[ADA] 이미지 빌드 중..." -ForegroundColor Cyan
    docker compose -f "$ADA_ROOT\docker\docker-compose.yml" --env-file "$ADA_ROOT\.env" --profile core build
}

function ada-mlflow-init {
    Write-Host "[ADA] MLflow 실험 초기화..." -ForegroundColor Cyan
    docker compose -f "$ADA_ROOT\docker\docker-compose.yml" --env-file "$ADA_ROOT\.env" run --rm worker-pipeline python scripts/mlflow_init.py
}

function ada-migrate {
    Write-Host "[ADA] DB 마이그레이션 적용 (alembic upgrade head)..." -ForegroundColor Cyan
    docker compose -f "$ADA_ROOT\docker\docker-compose.yml" --env-file "$ADA_ROOT\.env" run --rm api alembic upgrade head
}

function ada-migrate-down {
    Write-Host "[ADA] 가장 최근 1개 마이그레이션 롤백 (alembic downgrade -1)..." -ForegroundColor Yellow
    docker compose -f "$ADA_ROOT\docker\docker-compose.yml" --env-file "$ADA_ROOT\.env" run --rm api alembic downgrade -1
}

function ada-migrate-status {
    Write-Host "[ADA] 현재 리비전 + 히스토리..." -ForegroundColor Cyan
    docker compose -f "$ADA_ROOT\docker\docker-compose.yml" --env-file "$ADA_ROOT\.env" run --rm api alembic current
    docker compose -f "$ADA_ROOT\docker\docker-compose.yml" --env-file "$ADA_ROOT\.env" run --rm api alembic history
}

function ada-help {
    Write-Host ""
    Write-Host "  ada-up             컨테이너 시작 (core)" -ForegroundColor Green
    Write-Host "  ada-down           컨테이너 종료" -ForegroundColor Green
    Write-Host "  ada-ps             상태 확인" -ForegroundColor Green
    Write-Host "  ada-logs           전체 로그" -ForegroundColor Green
    Write-Host "  ada-logs api       api 로그만" -ForegroundColor Green
    Write-Host "  ada-logs mlflow    mlflow 로그만" -ForegroundColor Green
    Write-Host "  ada-build          이미지 빌드" -ForegroundColor Green
    Write-Host "  ada-mlflow-init    MLflow 실험 초기화" -ForegroundColor Green
    Write-Host ""
    Write-Host "  ada-migrate         DB 마이그레이션 적용 (alembic upgrade head)" -ForegroundColor Green
    Write-Host "  ada-migrate-down    가장 최근 1개 마이그레이션 롤백" -ForegroundColor Green
    Write-Host "  ada-migrate-status  현재 리비전 + 히스토리" -ForegroundColor Green
    Write-Host ""
}

Write-Host "[ADA] 로드 완료 - ada-help 로 명령어 목록 확인" -ForegroundColor Green
