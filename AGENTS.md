# AGENTS.md — ADA v2 개발 룰 카탈로그

> 권위 문서. 모든 코드/PR 이 본 문서를 따른다.
> 룰 코드 체계: 시리즈별 100 단위 (예: R-001 ~ R-099 시크릿/보안 기본, R-100~ DB 등)

## R-001 ~ R-005 핵심
- **R-001** 모든 시크릿은 `.env` 로만 관리. 코드 하드코딩 금지.
- **R-002** 공통 모듈(`ada/core/`, `agents/base.py`) 변경은 팀 합의 + PR 2인 승인.
- **R-003** 에이전트는 반드시 `BaseAgent` 상속. 독립 구현 금지.
- **R-004** 모든 LLM 호출은 `BaseAgent._call_llm()` 단일 진입점. 직접 SDK 호출 금지.
- **R-005** `PipelineState` 직접 수정 금지. `state.with_update(...)` 패턴만.
- **R-007** 페르소나 변경 시 `agent_registry.persona_version` 도 함께 bump.

## R-101 ~ R-103 데이터
- **R-101** DB 스키마 변경은 Alembic 마이그레이션으로만 (v2.2 의무화).
- **R-102** JSONB 컬럼 값은 Pydantic 모델 직렬화 결과여야 함.
- **R-103** PII (이메일/주민번호/전화) 로그 출력 금지 — `logger._pii_redactor` 자동 마스킹.

## R-201 ~ R-203 모델
- **R-201** 모든 학습은 MLflow run 기록 의무.
- **R-202** Celery worker_prefetch_multiplier=1 (Bulkhead).
- **R-203** `is_best=True` 모델은 job 당 1개만 존재.

## R-403 트랜스포머
- **R-403** 트랜스포머 강제는 데이터 ≥ 5,000 행 또는 GPU 가용일 때만 (v2.2 완화).

## R-501 ~ R-505 자체학습 Harness
- **R-501** RAG 검색 후 그래프 노드에 인용을 강제. 인용 없으면 KB 비사용으로 표시.
- **R-502** confidence cap = 0.95 (KB 오염 방지).
- **R-503** record_outcome 의무 — KB 사용 결과는 success/fail 로 자동 마킹.
- **R-504** 자동 retraction — confidence < 0.2 + 최근 5회 실패 시 retire.
- **R-505** decay — 60일 미사용 KB 의 confidence 0.9× 감쇠. 재루프 캡 max 2.

## R-601 ~ R-602 Claude CLI
- **R-601** Claude CLI 호출은 SDK 비동기로. subprocess 직접 호출은 sidecar 컨테이너 안에서만.
- **R-602** sidecar 의 workspace 마운트는 read-only. patches/ 만 read-write.

## R-703 ~ R-709 보안 풀스택
- **R-703** mTLS — 컨테이너 간 통신 TLS 의무 (Day20 완료 시점).
- **R-704** 모델 SHA256 무결성 — `models.model_sha256` 누락 금지.
- **R-705** MFA — admin 역할은 MFA 필수.
- **R-706** cosign — 외부 배포 모델은 cosign 서명.
- **R-707** JWT RS256 권장 (HS256 은 dev 만).
- **R-708** indirect prompt injection 가드 — LLM Guard 통과한 컨텐츠만 LLM 입력.
- **R-709** pybreaker — 외부 호출(Anthropic, MLflow, MinIO, Vault) 회로차단 의무.

## R-901 ~ R-903 백업/Vault
- **R-901** backup_catalog 테이블에 모든 백업 인벤토리 등록.
- **R-902** 백업 파일 SHA256 무결성 컬럼 의무.
- **R-903** Vault Dev 모드 운영 금지. Raft 스토리지 백엔드 + snapshot.

## R-1001 ~ R-1008 신규 도구 (v2.4)
- **R-1001** Langfuse — 모든 LLM 호출 trace 의무 (운영에서 PUBLIC/SECRET 키 설정 시).
- **R-1002** LLM Guard — 사용자 입력은 PII/injection 스캔 통과 후 그래프 진입.
- **R-1003** PyOD v3 — 이상탐지 카테고리 백본.
- **R-1004** python-docx — Word 산출물 (현재 v2 스코프 미사용, 백로그).
- **R-1005** Guardrails AI — JSON 스키마 응답은 Guardrails 검증 의무.
- **R-1006** FLAML — HPO warm-start 의무 (정형ML).
- **R-1007** StatsForecast — 시계열 기본 후보 포함.
- **R-1008** Chart.js / Plotly — HTML 대시보드(OUT-04) 차트 백본.

## 산출물 5종 (v2 스코프 — 2026-05-18)
| 코드 | 형식 | 책임 |
|---|---|---|
| OUT-01 | .pptx | python-pptx 기반 발표자료 |
| OUT-02 | .pdf  | reportlab + matplotlib |
| OUT-03 | .txt  | 발표 대본 |
| OUT-04 | .html | 정적 단일 파일 대시보드 (Chart.js inline) |
| OUT-07 | .md   | 인사이트 정리 |

OUT-05/06/08~13 은 v2 에서 제거됨.

## 4 카테고리
`tabular_ml`, `tabular_dl`, `timeseries`, `anomaly_detection` (image/nlp 제거).

## 27 에이전트 카테고리
supervisor (1) · input (3) · gates (5) · preprocessing (4) · modeling (6) · eval (3) · output (1) · meta (3) · recovery (1) = **27**.
