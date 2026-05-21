# ADR-001 Python 3.10 고정

## Status
Accepted (2026-05-19)

## Context
Day01 작업지시서에는 Python 3.11 로 통일되어 있으나, 사용자 결정 + DEV_SETUP_GUIDE 가 3.10 기준이므로 일관성 우선.

## Decision
모든 Docker 이미지·CI 매트릭스·로컬 venv 는 `python:3.10-slim`.

## Consequences
- `tomllib` 같은 3.11 stdlib 사용 금지 (대체: `tomli` 패키지)
- Ubuntu 22.04 시스템 패키지 의존성과 호환
