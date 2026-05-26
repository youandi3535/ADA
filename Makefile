# ============================================================
# ADA  -  Makefile
# 사용법: make <target>
# Windows PowerShell 사용자: . .\scripts\ada.ps1 후 ada-up 등 사용
# ============================================================

COMPOSE = docker compose -f docker/docker-compose.yml --env-file .env

.PHONY: up down ps logs build mlflow-init migrate migrate-down migrate-status help

up:
	$(COMPOSE) --profile core up -d --pull never

down:
	$(COMPOSE) --profile core down

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f

logs-%:
	$(COMPOSE) logs -f $*

build:
	$(COMPOSE) --profile core build

mlflow-init:
	$(COMPOSE) run --rm worker-pipeline python scripts/mlflow_init.py

# ----- DB migrations (alembic) ------------------------------------------------
# migrate        : 미적용 마이그레이션 모두 적용 (= alembic upgrade head)
# migrate-down   : 가장 최근 1개 마이그레이션 롤백
# migrate-status : 현재 리비전 + 전체 히스토리 출력
# run --rm 는 api 컨테이너가 떠 있지 않아도 동작 (depends_on 으로 postgres 가 함께 뜸).
migrate:
	$(COMPOSE) run --rm api alembic upgrade head

migrate-down:
	$(COMPOSE) run --rm api alembic downgrade -1

migrate-status:
	$(COMPOSE) run --rm api alembic current
	$(COMPOSE) run --rm api alembic history

help:
	@echo ""
	@echo "  make up           컨테이너 시작 (core)"
	@echo "  make down         컨테이너 종료"
	@echo "  make ps           상태 확인"
	@echo "  make logs         전체 로그"
	@echo "  make logs-api     api 로그만"
	@echo "  make logs-mlflow  mlflow 로그만"
	@echo "  make build        이미지 빌드"
	@echo "  make mlflow-init  MLflow 실험 초기화"
	@echo ""
	@echo "  make migrate         DB 마이그레이션 적용 (alembic upgrade head)"
	@echo "  make migrate-down    가장 최근 1개 마이그레이션 롤백"
	@echo "  make migrate-status  현재 리비전 + 히스토리"
	@echo ""
