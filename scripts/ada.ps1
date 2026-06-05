# ADA Docker ï¿½ï¿½ï¿½ï¿½ ï¿½ï¿½ï¿½É¾ï¿½ (PowerShell)
# VS Code ï¿½Í¹Ì³Î¿ï¿½ï¿½ï¿½ ï¿½Îµï¿½: . .\scriptsda.ps1

$ADA_ROOT = "C:\IT\workspace_python\ADA"

# ï¿½ï¿½ï¿½ï¿½È¯ï¿½ï¿½ ï¿½Úµï¿½ È°ï¿½ï¿½È­
$_venv = "$ADA_ROOT\.venv\Scripts\Activate.ps1"
if (Test-Path $_venv) {
    & $_venv
    Write-Host "[ADA] .venv È°ï¿½ï¿½È­ï¿½ï¿½" -ForegroundColor DarkGreen
}


function ada-up {
    Write-Host "[ADA] ï¿½ï¿½ï¿½ï¿½ï¿½Ì³ï¿½ ï¿½ï¿½ï¿½ï¿½ (core + ml)..." -ForegroundColor Cyan
    docker compose -f "$ADA_ROOT\docker\docker-compose.yml" --env-file "$ADA_ROOT\.env" --profile core --profile ml up -d --pull never
}

function ada-down {
    Write-Host "[ADA] ï¿½ï¿½ï¿½ï¿½ï¿½Ì³ï¿½ ï¿½ï¿½ï¿½ï¿½ (core + ml)..." -ForegroundColor Yellow
    docker compose -f "$ADA_ROOT\docker\docker-compose.yml" --env-file "$ADA_ROOT\.env" --profile core --profile ml down
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
    Write-Host "[ADA] ï¿½Ì¹ï¿½ï¿½ï¿½ ï¿½ï¿½ï¿½ï¿½ ï¿½ï¿½ (core + ml)..." -ForegroundColor Cyan
    docker compose -f "$ADA_ROOT\docker\docker-compose.yml" --env-file "$ADA_ROOT\.env" --profile core --profile ml build
}

function ada-mlflow-init {
    Write-Host "[ADA] MLflow ï¿½ï¿½ï¿½ï¿½ ï¿½Ê±ï¿½È­..." -ForegroundColor Cyan
    docker compose -f "$ADA_ROOT\docker\docker-compose.yml" --env-file "$ADA_ROOT\.env" run --rm worker-pipeline python scripts/mlflow_init.py
}

function ada-migrate {
    Write-Host "[ADA] DB ï¿½ï¿½ï¿½Ì±×·ï¿½ï¿½Ì¼ï¿½ ï¿½ï¿½ï¿½ï¿½ (alembic upgrade head)..." -ForegroundColor Cyan
    docker compose -f "$ADA_ROOT\docker\docker-compose.yml" --env-file "$ADA_ROOT\.env" run --rm api alembic upgrade head
}

function ada-migrate-down {
    Write-Host "[ADA] ï¿½ï¿½ï¿½ï¿½ ï¿½Ö±ï¿½ 1ï¿½ï¿½ ï¿½ï¿½ï¿½Ì±×·ï¿½ï¿½Ì¼ï¿½ ï¿½Ñ¹ï¿½ (alembic downgrade -1)..." -ForegroundColor Yellow
    docker compose -f "$ADA_ROOT\docker\docker-compose.yml" --env-file "$ADA_ROOT\.env" run --rm api alembic downgrade -1
}

function ada-migrate-status {
    Write-Host "[ADA] ï¿½ï¿½ï¿½ï¿½ ï¿½ï¿½ï¿½ï¿½ï¿½ï¿½ + ï¿½ï¿½ï¿½ï¿½ï¿½ä¸®..." -ForegroundColor Cyan
    docker compose -f "$ADA_ROOT\docker\docker-compose.yml" --env-file "$ADA_ROOT\.env" run --rm api alembic current
    docker compose -f "$ADA_ROOT\docker\docker-compose.yml" --env-file "$ADA_ROOT\.env" run --rm api alembic history
}

function ada-help {
    Write-Host ""
    Write-Host "  ada-up             ï¿½ï¿½ï¿½ï¿½ï¿½Ì³ï¿½ ï¿½ï¿½ï¿½ï¿½ (core + ml: serving/training/output ï¿½ï¿½ï¿½ï¿½)" -ForegroundColor Green
    Write-Host "  ada-down           ï¿½ï¿½ï¿½ï¿½ï¿½Ì³ï¿½ ï¿½ï¿½ï¿½ï¿½ (core + ml ï¿½ï¿½ï¿½ï¿½)" -ForegroundColor Green
    Write-Host "  ada-ps             ï¿½ï¿½ï¿½ï¿½ È®ï¿½ï¿½" -ForegroundColor Green
    Write-Host "  ada-logs           ï¿½ï¿½Ã¼ ï¿½Î±ï¿½" -ForegroundColor Green
    Write-Host "  ada-logs api       api ï¿½Î±×¸ï¿½" -ForegroundColor Green
    Write-Host "  ada-logs mlflow    mlflow ï¿½Î±×¸ï¿½" -ForegroundColor Green
    Write-Host "  ada-build          ï¿½Ì¹ï¿½ï¿½ï¿½ ï¿½ï¿½ï¿½ï¿½" -ForegroundColor Green
    Write-Host "  ada-mlflow-init    MLflow ï¿½ï¿½ï¿½ï¿½ ï¿½Ê±ï¿½È­" -ForegroundColor Green
    Write-Host ""
    Write-Host "  ada-migrate         DB ï¿½ï¿½ï¿½Ì±×·ï¿½ï¿½Ì¼ï¿½ ï¿½ï¿½ï¿½ï¿½ (alembic upgrade head)" -ForegroundColor Green
    Write-Host "  ada-migrate-down    ï¿½ï¿½ï¿½ï¿½ ï¿½Ö±ï¿½ 1ï¿½ï¿½ ï¿½ï¿½ï¿½Ì±×·ï¿½ï¿½Ì¼ï¿½ ï¿½Ñ¹ï¿½" -ForegroundColor Green
    Write-Host "  ada-migrate-status  ï¿½ï¿½ï¿½ï¿½ ï¿½ï¿½ï¿½ï¿½ï¿½ï¿½ + ï¿½ï¿½ï¿½ï¿½ï¿½ä¸®" -ForegroundColor Green
    Write-Host "  ada-env-push        ·ÎÄÃ .env¸¦ VPS·Î Àü¼Û + Àç½ÃÀÛ + Çï½ºÃ¼Å©" -ForegroundColor Green
    Write-Host "  ada-env-check       ·ÎÄÃ .env¿Í VPS .env ¿ÏÀü ÀÏÄ¡ È®ÀÎ" -ForegroundColor Green
    Write-Host ""
}

Write-Host "[ADA] ï¿½Îµï¿½ ï¿½Ï·ï¿½ - ada-help ï¿½ï¿½ ï¿½ï¿½ï¿½É¾ï¿½ ï¿½ï¿½ï¿?È®ï¿½ï¿½" -ForegroundColor Green
