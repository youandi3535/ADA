# ============================================================
# ADA  -  Makefile
# 사용법: make <target>
# Windows PowerShell 사용자: . .\scripts\ada.ps1 후 ada-up 등 사용
# ============================================================

COMPOSE = docker compose -f docker/docker-compose.yml --env-file .env

.PHONY: up down ps logs build mlflow-init help

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
