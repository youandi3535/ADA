# ADA v2 고도화 — 10일 무간섭 병렬 일정표

> 전제: Category Ownership 패턴 채택
> 멤버: **HJ** (시스템·메타·인프라) · **A** (timeseries 종주) · **B** (anomaly 종주) · **C** (tabular_ml + tabular_dl 종주)
> 보장: Day 1 이후 매일 4명이 동시 작업, **같은 파일 동시 수정 0건**

---

## 📐 단독 수정 파일 매트릭스 (Day 0 이후 영구 효력)

| 폴더/파일 | 단독 수정자 | 다른 멤버는? |
|---|---|---|
| `agents/handlers/timeseries/*` | **A** | 읽기만 |
| `agents/handlers/anomaly/*` | **B** | 읽기만 |
| `agents/handlers/tabular/*` | **C** | 읽기만 |
| `pipelines/timeseries/*` | **A** | 읽기만 |
| `pipelines/anomaly/*` | **B** | 읽기만 |
| `pipelines/tabular_ml/*` · `pipelines/tabular_dl/*` | **C** | 읽기만 |
| `tests/handlers/timeseries/*` | **A** | 읽기만 |
| `tests/handlers/anomaly/*` | **B** | 읽기만 |
| `tests/handlers/tabular/*` | **C** | 읽기만 |
| `agents/data_profiler.py` (얇은 dispatcher) + 6개 공유 dispatcher | **HJ** | 변경 요청만 |
| `agents/{supervisor,self_learning,auto_error_handler,security_guard,error_recovery}.py` | **HJ** | — |
| `ada/`, `orchestrator/`, `api/`, `outputs/*.py` carrier, `agents/personas.py`, `agents/base.py`, `agents/stubs.py` | **HJ** | — |
| `frontend/app.py` | **HJ** | UI 변경은 HJ 와 페어 |

**공유 규약**: `ada/core/state.py` 의 `state.category_extras["{cat}"]` 키 안에만 자기 카테고리 데이터 추가 (충돌 방지).

---

## 🗓️ Day 0 — HJ 단독 (4~6h, 리팩토링 골격)

**목표**: 이후 10일간 충돌 0건 보장하는 토대 까기.

| # | 작업 | 결과물 |
|---|---|---|
| H0-1 | `agents/handlers/{timeseries,anomaly,tabular,common}/` 생성 + 각 카테고리에 `profiler.py, preprocessor.py, eda.py, selector.py, evaluator.py, insight.py, output_extras.py, proposer.py` 8 빈 모듈 | 27 파일 (3×9) |
| H0-2 | 공유 8 에이전트를 dispatcher 로 리팩토링: `DataProfilerAgent, PreprocessingStrategistAgent, FeatureEngineerAgent, EDAAgent, ModelSelectionAgent, EvalAgent, InsightAgent, ReportComposerAgent` | 30줄 이하 dispatcher × 8 |
| H0-3 | `.github/CODEOWNERS` 단독 수정자 강제 | 신규 파일 |
| H0-4 | `PipelineState.category_extras: dict` 필드 추가 | `ada/core/state.py` |
| H0-5 | `tests/handlers/{timeseries,anomaly,tabular}/` 빈 conftest + smoke 테스트 1개 | 6 파일 |
| H0-6 | Day 0 검증 — `pytest tests/ -q` 19 passed 유지 | — |

**Day 0 PR**: `chore(HJ): category-ownership refactor for parallel work`

---

## Week 1 — Day 1 ~ 5 (foundations of each category)

### 📅 Day 1 — "내 카테고리 데이터부터 정확히 안다"

| 멤버 | 작업 (3~5) | 단독 수정 파일 | DoD |
|---|---|---|---|
| **HJ** | Supervisor — retry≥1 시 ErrorKB 조회 + 빠른 폴백 / SelfLearning — distill 후 `KBRAG.index_lesson` 자동 호출 / Prometheus metrics endpoint 골격 | `agents/supervisor.py`, `agents/self_learning.py`, `ada/observability/metrics.py`, `api/routes/metrics.py` | `curl /metrics` 에서 `ada_agent_duration_seconds` 노출 |
| **A** | timeseries profiler — ADF·KPSS·ACF·PACF·STL decompose · `outlier_iqr_ratio` / 데모 데이터 (AirPassengers) 시드 | `agents/handlers/timeseries/profiler.py`, `tests/handlers/timeseries/test_profiler.py`, `tests/handlers/timeseries/conftest.py` | pytest 그린 + profile dict 키 8개 |
| **B** | anomaly profiler — outlier 비율(IQR/Z) · PCA dim·dim별 isolation depth · contamination 추정 | `agents/handlers/anomaly/profiler.py`, `tests/handlers/anomaly/test_profiler.py`, `tests/handlers/anomaly/conftest.py` | pytest 그린 + `contamination_estimate` 필드 |
| **C** | tabular profiler — class balance · VIF · correlation cluster · cardinality 등급 | `agents/handlers/tabular/profiler.py`, `tests/handlers/tabular/test_profiler.py`, `tests/handlers/tabular/conftest.py` | pytest 그린 + `vif_top` 컬럼 |

### 📅 Day 2 — "내 카테고리 전처리"

| 멤버 | 작업 | 단독 수정 파일 | DoD |
|---|---|---|---|
| **HJ** | AutoErrorHandler 데몬화 — Celery beat 30초 폴링 / Vault Raft 마이그 스크립트 dry-run | `orchestrator/harness_tasks.py`, `ada/error_handler/daemon.py`, `scripts/security/vault_migrate_dev_to_raft.sh` | beat 기동 로그 `scanned N new failures` |
| **A** | timeseries preprocessor — lag·rolling·diff·boxcox·exog (사용자 명시 열) · time-order split | `agents/handlers/timeseries/preprocessor.py`, `tests/handlers/timeseries/test_preprocessor.py` | plan 적용 후 `_lag1`, `_rmean7` 컬럼 자동 생성 |
| **B** | anomaly preprocessor — RobustScaler·Winsorize·PCA(95% 분산) | `agents/handlers/anomaly/preprocessor.py`, `tests/handlers/anomaly/test_preprocessor.py` | 차원 줄어든 행렬 + scaler 객체 저장 |
| **C** | tabular preprocessor — target_encoding · class_weight 자동 · SMOTE 옵션 · VIF drop | `agents/handlers/tabular/preprocessor.py`, `tests/handlers/tabular/test_preprocessor.py` | Adult 데이터에서 SMOTE 후 balance 검증 |

### 📅 Day 3 — "내 카테고리 EDA"

| 멤버 | 작업 | 단독 수정 파일 | DoD |
|---|---|---|---|
| **HJ** | Langfuse 연동 검증 + audit 대시보드 라우터 `/admin/audit` (admin RBAC) | `ada/core/langfuse_client.py`, `api/routes/admin.py` | swagger 에 `/admin/audit` 등장 |
| **A** | timeseries EDA — line/ACF/STL/seasonality heatmap (월·요일) | `agents/handlers/timeseries/eda.py`, `tests/handlers/timeseries/test_eda.py` | MinIO `eda/timeseries/{job}/*.png` 4종 |
| **B** | anomaly EDA — feature 분포 + 이상치 산점 (top2 dim PCA) + 시간축 anomaly score | `agents/handlers/anomaly/eda.py`, `tests/handlers/anomaly/test_eda.py` | MinIO `eda/anomaly/{job}/*.png` 3종 |
| **C** | tabular EDA — 상관 히트맵·target 별 박스·계급별 분포·feature importance preview | `agents/handlers/tabular/eda.py`, `tests/handlers/tabular/test_eda.py` | MinIO `eda/tabular/{job}/*.png` 4종 |

### 📅 Day 4 — "G1/G2/G3 fallback 카테고리별 정교화"

| 멤버 | 작업 | 단독 수정 파일 | DoD |
|---|---|---|---|
| **HJ** | LLM Guard 풀 통합 (PII anonymize→re-attach 파이프라인) + 입력 차단 audit | `ada/security/guardrails.py`, `agents/security_guard.py` | PII 컬럼 자동 마스킹 후 결과 페이지에 *** |
| **A** | timeseries proposer — G1 3안(단기예측/이상시점/계절성분해), G2(SARIMA/Prophet/TFT 비교) 가중치 | `agents/handlers/timeseries/proposer.py`, `tests/handlers/timeseries/test_proposer.py` | n_rows<100 시 TFT 점수 down |
| **B** | anomaly proposer — G1 3안(점수화/정상학습/Top-N), G2(IForest/LOF/AE 우선순위 카드) | `agents/handlers/anomaly/proposer.py`, `tests/handlers/anomaly/test_proposer.py` | contamination 낮으면 OneClassSVM 우선 |
| **C** | tabular proposer — G1 3안(예측/세그먼트/피처중요도), G2 (ML vs DL 결정) | `agents/handlers/tabular/proposer.py`, `tests/handlers/tabular/test_proposer.py` | n_rows≥5000 + classes≤10 시 DL 1개 포함 |

### 📅 Day 5 — "내 카테고리 모델 selector 깊이"

| 멤버 | 작업 | 단독 수정 파일 | DoD |
|---|---|---|---|
| **HJ** | RS256 JWT 전환 + Vault 에서 키 로딩 (현재 HS256 dev) | `ada/security/jwt.py`, `scripts/security/jwt_keygen.sh` | `decode_token` RS256 통과 단위 테스트 |
| **A** | timeseries selector — 데이터 길이/계절성/exog 유무로 모델 점수 매트릭스 + KB recipe 우선 | `agents/handlers/timeseries/selector.py`, `tests/handlers/timeseries/test_selector.py` | exog 없으면 SARIMA exog 후보 제외 |
| **B** | anomaly selector — 차원·시간성·contamination으로 모델 점수 매트릭스 | `agents/handlers/anomaly/selector.py`, `tests/handlers/anomaly/test_selector.py` | 시간 컬럼 있으면 TranAD 점수 up |
| **C** | tabular selector — n_rows·n_classes·imbalance ratio 기반 ML/DL 결정 + FLAML warm-start 시드 | `agents/handlers/tabular/selector.py`, `tests/handlers/tabular/test_selector.py` | XGBoost·LightGBM 항상 포함, n>5000 시 FTTransformer 추가 |

**Week 1 종료 체크**: 4명 모두 자기 카테고리의 입력→EDA→모델 선택까지 종단 가능. `pytest tests/ -q` 30+ passed.

---

## Week 2 — Day 6 ~ 10 (modeling + outputs)

### 📅 Day 6 — "P0 블로커 #1·#2 해결 (HPO ↔ Training)"

| 멤버 | 작업 | 단독 수정 파일 | DoD |
|---|---|---|---|
| **HJ** | `HyperparameterTunerAgent` 진짜 구현 — trial 별 학습 + CV 호출 → 각 카테고리 `selector` 의 search space 사용 / `PipelineState.best_params: dict` 추가 | `agents/hyperparameter_tuner.py`, `agents/training_executor.py`, `ada/core/state.py` | Titanic 학습 → `best_params["XGBoost"]` 비어있지 않음 |
| **A** | timeseries pipeline 본격화 — SARIMA exog · Prophet seasonality 자동 · 8 epoch CPU 가드 (Informer/TFT/PatchTST) | `pipelines/timeseries/pipeline.py`, `tests/handlers/timeseries/test_pipeline.py` | AirPassengers 학습 → val_rmse 출력 |
| **B** | anomaly pipeline 본격화 — PyOD 7종 전수 + Otsu threshold 자동 + ensemble voting | `pipelines/anomaly/pipeline.py`, `tests/handlers/anomaly/test_pipeline.py` | 합성 이상치 데이터 → AUC > 0.8 |
| **C** | tabular_ml early stopping + tabular_dl 진짜 TabTransformer 학습 (CPU 5 epoch) | `pipelines/tabular_ml/pipeline.py`, `pipelines/tabular_dl/pipeline.py`, `tests/handlers/tabular/test_pipeline.py` | Adult → val_f1 ≥ 0.7 + MLflow 에 best_iteration 기록 |

### 📅 Day 7 — "내 카테고리 평가"

| 멤버 | 작업 | 단독 수정 파일 | DoD |
|---|---|---|---|
| **HJ** | `TrainingMonitorAgent` 본격화 — NaN/Inf + 학습 시간 초과 + val 메트릭 발산(3 연속 ↓) + 메모리 80% 경고 | `agents/training_monitor.py` | 합성 NaN/발산 케이스 단위 테스트 3건 |
| **A** | timeseries evaluator — naïve baseline 대비 개선율 · MASE · sMAPE · prediction interval coverage | `agents/handlers/timeseries/evaluator.py`, `tests/handlers/timeseries/test_evaluator.py` | `rmse_improvement_vs_naive` 필드 |
| **B** | anomaly evaluator — precision@k · ROC-AUC · F1 · threshold sweep 곡선 | `agents/handlers/anomaly/evaluator.py`, `tests/handlers/anomaly/test_evaluator.py` | `pr_at_10`, `auc`, `f1`, `threshold_curve_path` |
| **C** | tabular evaluator — accuracy/f1/ROC/calibration + 다중 임계치 sweep | `agents/handlers/tabular/evaluator.py`, `tests/handlers/tabular/test_evaluator.py` | `calibration_brier` 필드 |

### 📅 Day 8 — "내 카테고리 인사이트"

| 멤버 | 작업 | 단독 수정 파일 | DoD |
|---|---|---|---|
| **HJ** | InsightAgent 메트릭 인용 Guardrails — (a) 정확한 수치 1개+, (b) top3 피처 1개+, (c) 3~5문장, (d) 한국어 강제 | `agents/insight.py`, `ada/security/guardrails.py` | 미인용 시 retry 1회 후 fallback |
| **A** | timeseries insight 한국어 템플릿 — 추세·계절성·예측 수치 인용 (예: "다음 7일 매출이 평균 12% 증가") | `agents/handlers/timeseries/insight.py`, `tests/handlers/timeseries/test_insight.py` | 한국어 3~5문장 + 수치 2개 이상 |
| **B** | anomaly insight — Top-N 이상치 사례 + 원인 추정 (피처 기여도) | `agents/handlers/anomaly/insight.py`, `tests/handlers/anomaly/test_insight.py` | "거래 #12345 가 평균 대비 8.3σ 벗어남" 형식 |
| **C** | tabular insight — best 피처 top3 + 비즈니스 행동 권고 | `agents/handlers/tabular/insight.py`, `tests/handlers/tabular/test_insight.py` | "X 피처가 결과의 32% 설명" 형식 |

### 📅 Day 9 — "내 카테고리 산출물 차별화"

| 멤버 | 작업 | 단독 수정 파일 | DoD |
|---|---|---|---|
| **HJ** | OUT-01 PPT carrier · OUT-02 PDF carrier 에 **카테고리 색상 자동 적용** + handlers/{cat}/output_extras 호출 훅 | `outputs/ppt.py`, `outputs/pdf.py`, `outputs/base.py` | 4 카테고리 PPT 색상 다름 + handler 차트 슬라이드 자동 삽입 |
| **A** | timeseries output_extras — 예측 곡선 + 신뢰구간 + 분해 4단 그래프 + 미래 행동권고 | `agents/handlers/timeseries/output_extras.py`, `tests/handlers/timeseries/test_output.py` | OUT-04 에 `forecast_chart`, `decomposition` |
| **B** | anomaly output_extras — top-N 이상치 테이블 + 분포 비교 + 시간축 이상 시점 | `agents/handlers/anomaly/output_extras.py`, `tests/handlers/anomaly/test_output.py` | OUT-04 에 `top_n_table`, `anomaly_timeline` |
| **C** | tabular output_extras — ROC + Calibration + Confusion Matrix + 피처 중요도 차트 | `agents/handlers/tabular/output_extras.py`, `tests/handlers/tabular/test_output.py` | OUT-04 에 4 차트 추가 |

### 📅 Day 10 — "E2E 시연 + 성능 측정"

| 멤버 | 작업 | 단독 수정 파일 | DoD |
|---|---|---|---|
| **HJ** | KPI 자동 측정 스크립트 — KP1 E2E 성공률 · KP2 시간 · KP5 p95 응답 · KP9 KB 적용률. Streamlit 탭에 KPI 위젯 | `scripts/kpi_measure.py`, `frontend/app.py` (KPI 위젯만) | dashboard 에 KPI 5종 카드 |
| **A** | timeseries E2E 데모 — AirPassengers 5개 시나리오 (1일/7일/30일 forecast + 이상 시점) + 5게이트 응답 자동화 스크립트 | `tests/handlers/timeseries/test_e2e.py`, `scripts/demo/timeseries_demo.py` | `python scripts/demo/timeseries_demo.py` → 5분 안에 OUT-04 생성 |
| **B** | anomaly E2E 데모 — KDD Cup 99 또는 합성 시계열 이상 5개 시나리오 | `tests/handlers/anomaly/test_e2e.py`, `scripts/demo/anomaly_demo.py` | 5분 안에 OUT-04 + top-N 테이블 |
| **C** | tabular E2E — Titanic + Adult + Iris 3 시나리오 (분류·다중분류·회귀) | `tests/handlers/tabular/test_e2e.py`, `scripts/demo/tabular_demo.py` | 3 데이터 모두 val_f1/val_r2 통과 |

**Week 2 종료 체크**:
- `pytest tests/ -v` 50+ passed
- 4명 모두 `scripts/demo/{cat}_demo.py` 5분 내 완주
- Streamlit KPI 위젯에 KP1~KP5 표시
- MLflow 4 실험 × N run 누적
- MinIO `outputs/OUT-*/{job_id}/` 4 카테고리 산출물 확인

---

## 🔒 일일 충돌 방지 체크리스트 (매일 종료 30분 전)

각 멤버가 매일 실행:

```bash
# 1) 본인 파일만 수정했는지 확인
git diff --stat main..HEAD | grep -v "$(본인_허용_경로)"
# 위 결과가 비어있어야 함

# 2) 본인 테스트 그린
pytest tests/handlers/{본인카테고리}/ -q

# 3) 전체 통합 테스트 그린
pytest tests/ -q

# 4) main 머지 (rebase 권장)
git fetch origin
git rebase origin/main
git push origin feat/{본인}-day{N}
```

---

## 📊 진행률 추적 (매일 매니저용)

| Day | HJ | A | B | C | 누적 테스트 | PR |
|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| 0  | ✅ |  - |  - |  - | 19 | 1 |
| 1  | ⬜ | ⬜ | ⬜ | ⬜ | +3 → 22 | 4 |
| 2  | ⬜ | ⬜ | ⬜ | ⬜ | +3 → 25 | 4 |
| 3  | ⬜ | ⬜ | ⬜ | ⬜ | +3 → 28 | 4 |
| 4  | ⬜ | ⬜ | ⬜ | ⬜ | +3 → 31 | 4 |
| 5  | ⬜ | ⬜ | ⬜ | ⬜ | +3 → 34 | 4 |
| 6  | ⬜ | ⬜ | ⬜ | ⬜ | +3 → 37 | 4 |
| 7  | ⬜ | ⬜ | ⬜ | ⬜ | +3 → 40 | 4 |
| 8  | ⬜ | ⬜ | ⬜ | ⬜ | +3 → 43 | 4 |
| 9  | ⬜ | ⬜ | ⬜ | ⬜ | +3 → 46 | 4 |
| 10 | ⬜ | ⬜ | ⬜ | ⬜ | +6 → 52 | 4 |

각 멤버 = 일일 1 PR. Day 0 HJ 단독. Day 1~10 매일 4 PR 동시 머지 가능 (충돌 없음).

---

## 🔮 Day 11 ~ 20 예고

| 주차 | 테마 | 산출물 |
|---|---|---|
| Week 3 (Day 11~15) | v3 백로그 1차 도입 — Captum(해석성) · Ray Tune(분산 HPO) · Arize Phoenix(옵저버빌리티) · SUOD(이상탐지 가속) · Braintrust(LLM 평가) | 각자 카테고리 v3 도구 1개 통합 |
| Week 4 (Day 16~20) | 운영 안정성 — 백업 / DR Game Day / mTLS / cosign 모델 서명 / 침투 테스트 / 부하 테스트 | KPI 13종 (KP1~KP13) 모두 측정 통과 |

10일 사이클 끝나면 본 문서 §"진행률 추적" 표를 ✅ 로 채우고 Week 3 일정으로 갱신.

---

## 📌 한 줄 요약

- **Day 0**: HJ가 dispatcher 8개 + handlers 폴더 3종 + CODEOWNERS 깔기 (4~6h)
- **Day 1~10**: 4명 매일 동시 작업, 같은 파일 동시 수정 0건 보장
- **하루 분량**: 멤버당 3~5 작업, 4~6시간 추정
- **검증**: 매일 종료 시 본인 카테고리 pytest + 전체 통합 pytest 그린
- **PR**: 일 1건씩 총 41 PR (Day 0 HJ 1 + Day 1~10 매일 4) → 모두 conflict-free 머지

— 끝.
