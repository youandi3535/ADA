# ADA v2.4 리뉴얼 스펙 (신설 Day 흡수)

> **v2.1 결정일**: 2026-05-18 (스코프 축소)
> **v2.2 결정일**: 2026-05-19 (감사 보고서 반영)
> **v2.3 결정일**: 2026-05-19 (Notion 도구 카탈로그 18종 통합)
> **v2.4 결정일**: 2026-05-19 (Day-A/B/C/D/E 5개 신설 Day → 기존 Day 흡수 + 삭제)
> **권위**: 본 문서가 모든 작업지시서·README의 단일 권위 (Day00 마스터설계서보다 우선)
> 모든 daily/*.md 파일은 이 스펙에 일치하도록 갱신되어야 한다.

---

## 0. v2.4 변경 요약 (신설 Day 흡수, 2026-05-19)

> Day-A/B/C/D/E 5개 신설 작업지시서를 v2.2~v2.3 의 의도대로 만들었으나, 운영 편의를 위해 본 v2.4 부터는 **기존 Day 안으로 흡수**한다. 모든 본문 내용은 보존되며, 권위 위치만 이전된다.

### v2.4.1 흡수 매핑

| 원래 신설 Day | 통합 위치 | 통합 헤더 |
|---|---|---|
| Day-A 백업·DR | Day17 | 📦 통합본 (v2.4) — 원래 Day-A |
| Day-B 자가학습 폐쇄 | Day19 | 📦 통합본 (v2.4) — 원래 Day-B |
| Day-C 보안 보강 | Day17 | 📦 통합본 (v2.4) — 원래 Day-C |
| Day-D §1 Langfuse | Day03 | 📦 통합본 (v2.4) — 원래 Day-D §1 |
| Day-D §2 LLM Guard | Day17 | 📦 통합본 (v2.4) — 원래 Day-D §2 |
| Day-D §3 PyOD v3 | Day12 | 📦 통합본 (v2.4) — 원래 Day-D §3 |
| Day-D §4 python-docx | Day15 | 📦 통합본 (v2.4) — 원래 Day-D §4 |
| Day-E §1 Guardrails AI | Day17 | 📦 통합본 (v2.4) — 원래 Day-E §1 |
| Day-E §2 FLAML | Day07 | 📦 통합본 (v2.4) — 원래 Day-E §2 |
| Day-E §3 StatsForecast | Day08 | 📦 통합본 (v2.4) — 원래 Day-E §3 |
| Day-E §4 Chart.js/Plotly | Day15 | 📦 통합본 (v2.4) — 원래 Day-E §4 |

### v2.4.2 변경된 권위 위치

기존 `Day-A/B/C/D/E` 파일 참조는 **모두 통합 위치로 변경**된다. 룰·KPI·테이블·스크립트 명세는 그대로 유지.

### v2.4.3 스프린트 일정

21일 일정 유지. Day17(보안)·Day19(자가학습 통합) 분량이 증가하므로 해당 Day의 작업 시간 60% 정도 추가 배정 권고.

---

## 0. v2.3 변경 요약 (도구 카탈로그, 2026-05-19)

> 출처: [Notion 카탈로그](https://www.notion.so/365545ab947d8100b8c7fa0165da49b4) → `TOOL_CATALOG_2026.md`

### v2.3.1 신설 작업지시서 2종
- **Day-D** — 도구 즉시 도입 4종 (Langfuse · LLM Guard · PyOD v3 · python-docx)
- **Day-E** — 도구 단기 도입 4종 (Guardrails AI · FLAML · StatsForecast · Chart.js/Plotly)

### v2.3.2 신설 백로그 문서
- **v3_backlog.md** — 중기 5종 (Ray Tune · NeuralForecast · Captum · Arize Phoenix · SUOD) + 장기 5종 (Qdrant · ClearML · SWE-agent · Braintrust · Galileo)

### v2.3.3 신설 룰
- **R-1001 ~ R-1008** — Langfuse trace, LLM Guard sanitize 폴백, PyOD 레지스트리, Word 초안, Guardrails schema, FLAML 폴백, StatsForecast Top-3, Chart.js/Plotly 정책
- **R-1101 ~ R-1105** (v3 백로그) — Ray Tune 분산 모드, NeuralForecast 진입점, Captum 우선, Phoenix 알람, SUOD 자동 활성화

### v2.3.4 도구 분야별 카테고리 (8개)
옵저버빌리티 · 벡터DB · ML/HPO · 시계열 · 이상탐지 · 보안 · 산출물 · 해석성 · 자가치유

---

# ADA v2.2 리뉴얼 스펙 (감사 보고서 반영 — 유지)

---

## 0. v2.2 변경 요약 (2026-05-19)

> 출처: `ADA_v2_감사보고서.docx` — 22개 Day + 보조 문서 4종 프로덕션급 감사.

### 0.1 신설 Day 3종
- **Day-A** — 백업·DR·복구 인프라 (P0)
- **Day-B** — 자가학습 사이클 폐쇄 + Stage 1 (P0)
- **Day-C** — 보안 보강 (mTLS·MFA·SBOM·회로차단기) (P1)

### 0.2 정책 변경
- **R-403 완화** — 트랜스포머 강제 → 데이터·GPU 조건부 + max_retries=3.
- **R-501·503·504·505 신설** — KB 인용 강제·사용 결과 피드백·자동 retraction·confidence decay.
- **R-601 보강** — Claude CLI subprocess → Anthropic SDK 비동기 + pybreaker + Redis 토큰 버킷.
- **R-703~709 신설** — mTLS·MLflow 인증·MFA·cosign·JWT RS256·indirect injection·회로차단기 의무.
- **R-901~903 신설** — backup_catalog·model artifact SHA256·Vault Dev 모드 폐지.

### 0.3 KPI 재조정
- **KP2** — 트랙 분리: 트리만 90s / 트랜스포머 포함 180s.
- **KP7** — 동일 데이터 +5% → 유사 데이터 군집 30일 회귀 기울기.
- **KP11** — gate_recommendation_shadow.matched 자동 측정.
- **KP12 신설** — 백업 RPO 준수율 ≥ 99% (월간).
- **KP13 신설** — 분기 Game Day 통과율 (4/4).

### 0.4 아키텍처 변경
- 에이전트 플랫폼 4계층 분리 (L1 Runtime / L2 인터페이스 / L3 구현 / L4 오케스트레이션).
- Redis Streams 이벤트 버스 도입.
- 백업 사이드카 3종(postgres-backup·minio-mirror·vault-snapshot).
- DR 사이트(가상 단독 서버) — Postgres hot standby + MinIO mirror + Vault snapshot.
- Alembic 의무화.
- SBOM(syft)·이미지 서명(cosign)·취약점 스캔(trivy) CI 통합.

### 0.5 v3.0 백로그 (미해결)
- Contextual Bandit (Stage 2)·Offline RL (Stage 3)·Patroni HA·Kafka/NATS·Feast·Reflex.

---

## 1. 분석 카테고리 (6종 → 4종)

### 유지 (4종)
- `tabular_ml` — 정형 ML
- `tabular_dl` — 정형 DL
- `timeseries` — 시계열
- `anomaly_detection` — 이상탐지

### 제거 (2종)
- ❌ `image` — 이미지
- ❌ `nlp` — 자연어

---

## 2. 산출물 (13종 → 5종)

### 유지 (5종)
- OUT-01 PPT 발표자료 (.pptx)
- OUT-02 상세 PDF 리포트 (.pdf)
- OUT-03 발표 대본 (.txt)
- OUT-04 정적 웹 대시보드 (.html 단일)
- OUT-07 인사이트 정리 (.md)

### 제거 (8종)
- ❌ OUT-05 영상 제작 프롬프트
- ❌ OUT-06 외부 PPT 생성기 프롬프트
- ❌ OUT-08 학술 논문 초안
- ❌ OUT-09 기획안
- ❌ OUT-10 Executive Summary
- ❌ OUT-11 상세 비즈니스 리포트
- ❌ OUT-12 인포그래픽 프롬프트
- ❌ OUT-13 팟캐스트 프롬프트

---

## 3. 모델 카탈로그

### 유지 모델 (19종)

**정형 ML (4)**: RandomForest, XGBoost, LightGBM, CatBoost
**정형 DL (3)**: TabTransformer, FTTransformer, TabPFN
**시계열 (6)**: ARIMA, SARIMA, Prophet, Informer, TFT, PatchTST
**이상탐지 (6)**: IsolationForest, LOF, OneClassSVM, AutoEncoder, TranAD, AnomalyTransformer

### 제거 모델 (이름 언급도 제거)
- ResNet, ResNet50
- EfficientNet, EfficientNet-B0, EfficientNetB0
- ViT, ViT-B/16, ViT-Tiny, ViT-B
- Swin-T, SwinT
- DeiT-S, DeiTS, DeiT
- klue/bert-base, KLUE_BERT, klue-bert, BERT
- XLM-RoBERTa, XLMRoBERTa
- DeBERTa, DeBERTa-v3, DeBERTaV3

### TRANSFORMER_REGISTRY (14종 → 8종)
- TabTransformer, FTTransformer, TabPFN
- Informer, TFT, PatchTST
- TranAD, AnomalyTransformer

---

## 4. 데이터 입력 형식 (10종 → 8종)

### 유지
csv, xlsx, parquet, json, zip, pdf, txt, html

### 제거
- ❌ jpg, png, jpeg (이미지)
- ❌ wav, mp3 (오디오)

---

## 5. Python 버전

**3.10 사용 (3.11 표기 모두 변경)**

- `python:3.11-slim` → `python:3.10-slim`
- `Python 3.11` → `Python 3.10`
- `python-version: 3.11` → `python-version: 3.10`
- `python-version: "3.11"` → `python-version: "3.10"`

---

## 6. MLflow 실험 (6종 → 4종)

### 유지
- ada-tabular-ml
- ada-tabular-dl
- ada-timeseries
- ada-anomaly

### 제거
- ❌ ada-image
- ❌ ada-nlp

---

## 7. 카테고리별 색상 테마 (6색 → 4색)

### 유지
- tabular_ml: 파랑 `#2563eb` / `RGBColor(37, 99, 235)`
- tabular_dl: 청록 `#0891b2` / `RGBColor(8, 145, 178)`
- timeseries: 초록 `#16a34a` / `RGBColor(22, 163, 74)`
- anomaly_detection: 빨강 `#dc2626` / `RGBColor(220, 38, 38)`

### 제거
- ❌ image: 보라 `#7c3aed` / `RGBColor(124, 58, 237)`
- ❌ nlp: 주황 `#ea580c` / `RGBColor(234, 88, 12)`

---

## 8. 변경되는 수치/카운트

| 표현 | 이전 | 신규 |
|---|---|---|
| 산출물 종류 | 13종 | **5종** |
| 생성기 유틸리티 | 13종 | **5종** |
| 분석 카테고리 | 6종 (6/6) | **4종 (4/4)** |
| 트랜스포머 레지스트리 | 14종 (또는 9종) | **8종** |
| MLflow 실험 | 6종 | **4종** |
| API 엔드포인트 | ~30 | **~25** |
| 데모 매트릭스 | 5×5 | **4×5** (4 카테고리 × 5 산출물) |
| 통합 테스트 IT | IT-1~IT-5 | **IT-1~IT-4** |
| 인수 테스트 AT | AT-1~AT-5 | *