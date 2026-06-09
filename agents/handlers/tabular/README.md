# agents/handlers/tabular — jh 영역 reference

> **영역 소유자**: jh (tabular_ml + tabular_dl 종주)
> **목적**: 정형 데이터(분류·회귀)의 archetype 인식·모델 선택·해석·확률 보정·임계치 결정을 한 흐름으로 자동화.
> **계약**: `CLAUDE.md` §1 — `agents/handlers/tabular/`, `pipelines/tabular_{ml,dl}/`, `tests/handlers/tabular/`, `requirements/handlers-tabular.txt` 만 수정. 외부 영역 (`ada/`, dispatcher, `outputs/` 등)은 HJ 협의 필수.

---

## 한눈에

ADA 의 tabular 핸들러는 다음 honest 분석 체인을 제공합니다:

```
데이터 입력
    ↓
[1] profiler        → 신호 6 종 (imbalance / VIF / cardinality / leakage / id_like / MI)
    ↓
[2] archetype       → 데이터 종류 1 개 분류 + confidence
    ↓
[3] selector        → archetype 보정 점수 → top-3 모델 (G4)
[3] proposer        → 극단 imbalance 시 anomaly_detection 권고 (G2)
    ↓
[4] preprocessor    → archetype 의 preprocessing_must/should_not 룰 반영
    ↓
[5] training        → 학습 + 평가 (evaluator 가 임계치·CV·improvement)
    ↓
[6] explainability  → SHAP top-K + summary/dependence 차트
[6] calibration     → ECE 측정 + Platt/Isotonic 자동 보정
[6] threshold_opt   → 4 전략 (F1-max/cost-min/Youden J/recall-min) + expected_cost
    ↓
[7] insight         → 위 결과를 한국어로 인용해 사용자 설명
[7] output_extras   → 차트 + 운영 권고 표 4 종을 carrier 에 전달
```

핵심 정체성:
- **outcome 측정이 아니라 decision match 측정** — Titanic F1 0.83 → 0.84 는 의미 없음.
  "임의 데이터에서 적합한 결정을 했는가" 가 KPI.
- **강제 룰이 아니라 투명한 자동 의사결정** — archetype 매칭은 confidence 기반 점수 가중,
  사용자가 G4 에서 다른 선택 가능, 매칭 근거 (signals) 노출.

---

## 모듈 카탈로그

### 진입점 / Dispatcher 호출

| 모듈 | capability | 진입 함수 | 역할 |
|---|---|---|---|
| `profiler.py` | `profile` | `profile(df, state)` | 신호 6 종 추출 + archetype 분류 호출 |
| `preprocessor.py` | `plan`, `apply`, `apply_split` | `plan(state)` / `apply(df, plan, state)` | 15 transforms registry + 누수 가드 split |
| `eda.py` | `charts` | `charts(df, state)` | missing/hist/corr 3 차트 |
| `selector.py` | `score` | `score(state, recipes)` | archetype 보정 점수 → top-3 + baselines |
| `proposer.py` | `g1`, `g2` | `g1(state)` / `g2(state)` | G1/G2 fallback 제안, extreme_imbalance 라우팅 |
| `evaluator.py` | `evaluate` | `evaluate(state)` | 임계치 + CV 통계 + improvement_over_baseline |
| `insight.py` | (dispatcher 호출) | `prompt_payload(state)` / `fallback(state)` | LLM 페이로드 + 결정적 fallback 텍스트 |
| `output_extras.py` | `assets` | `assets(state, ctx=None)` | 차트·표 + SHAP/calibration/threshold 통합 |

### 분석 모듈 (Day 11++ 신설)

| 모듈 | 진입 함수 | 역할 |
|---|---|---|
| `archetype.py` | `classify_archetypes(profile, state)` | 10 종 archetype 분류 + EXPECTED_DECISIONS 룰 |
| `explainability.py` | `explain(state)` | TreeExplainer / LinearExplainer / KernelExplainer 자동 |
| `calibration.py` | `calibrate(state)` | ECE + Platt/Isotonic K-fold CV honest 평가 |
| `threshold_optimizer.py` | `optimize_thresholds(state)` | 4 전략 grid search + cost-sensitive |
| `diagnostics.py` | `permutation_importance_chart`, `pdp_chart`, `qq_plot_chart` | 진단 차트 3 종 |
| `_class_weight_adapters.py` | `to_sklearn/xgboost/...` | backbone 별 class weight 변환 |

---

## 통합 패턴 — state.category_extras 캐시

모든 신설 분석 모듈은 동일 패턴으로 결과를 저장 + insight·output_extras 가 인용:

```python
# output_extras.assets() 가 호출 시점에 분석 모듈 실행
shap_result = explainability.explain(state)
cal_result  = calibration.calibrate(state)
ts_result   = threshold_optimizer.optimize_thresholds(state)

# state.category_extras["tabular"][key] 에 저장 (_cache_in_state 헬퍼)
_cache_in_state(state, "shap",                  shap_result)
_cache_in_state(state, "calibration",           cal_result)
_cache_in_state(state, "threshold_strategies",  ts_result)

# insight.prompt_payload 가 동일 캐시 읽음 → LLM 인용
"shap_top":              cat_extras.get("shap", {}).get("shap_top_features"),
"calibration":           cat_extras.get("calibration"),
"threshold_strategies":  cat_extras.get("threshold_strategies"),
```

**왜 이 패턴인가**:
- dispatcher 미연결 환경에서도 결과가 산출물에 노출 (HJ 가 정식 dispatcher wiring 하기 전 임시 캐시)
- 동일 호출 사이클 내에서 중복 계산 방지
- 표준 키 구조 → 어떤 모듈 추가해도 동일 패턴

### 결과 dict 표준 구조

모든 분석 모듈은 graceful skip 시에도 동일 키 구조 반환:

```python
{
    # 핵심 결과 (skip 시 None 또는 [])
    "<primary_key>": value | None,

    # 메타데이터
    "skipped_reason": str | None,   # skip 사유, None 이면 정상 동작
    "n_samples_used": int,

    # MinIO 차트 경로 (있으면)
    "<chart>_path": str | None,
}
```

---

## 데이터 archetype 카탈로그 (10 종)

`archetype.py::EXPECTED_DECISIONS` 단일 권위.

| Priority | Archetype | 매칭 조건 | 핵심 결정 |
|---|---|---|---|
| 0 (긴급) | `target_leakage_suspected` | `target_leakage_suspects` 비어있지 않음 | selector top1 ∈ {RF/LR/Ridge/Dummy}, insight 누수 경고 |
| 0 (긴급) | `extreme_imbalance` | `class_imbalance_ratio ≥ 1000` | proposer → anomaly_detection, smote_resample 차단 |
| 1 (구조) | `p_gg_n` | `n_features / n_rows ≥ 0.5` | selector top1 ∈ {LR/Ridge/Lasso}, 트리/DL 배제 |
| 1 (구조) | `id_overload` | `id_like_columns / n_cols ≥ 0.30` | id 컬럼 학습 제외 권고 |
| 1 (구조) | `multicollinear_heavy` | `corr_clusters ≥ 2` OR `cond ≥ 100` | VIF drop, LR 배제 |
| 1 (구조) | `high_cardinality_heavy` | non-numeric `high` cardinality ≥ 3 | CatBoost/LightGBM 우선 |
| 2 (세부) | `imbalanced_moderate` | `10 ≤ ratio < 1000` | LGB/Cat/RF + class_weight + cost-sensitive 임계치 |
| 2 (세부) | `low_signal` | `max(mutual_info_top) < 0.05` | 피처 엔지니어링 권고 |
| 2 (세부) | `regression_heteroscedastic` | 회귀 + 변동계수 > 3 | distribution_transform 권고 |
| 2 (폴백) | `clean_balanced` | 위 모두 미매칭 + 결측 < 10% | 점수표대로 진행 |

### confidence (sigmoid)

매칭은 binary 룰이지만, 매칭 강도는 sigmoid 로 0~1 점수:

```python
# 예: extreme_imbalance threshold=1000, width=200
confidence = sigmoid((ratio - 1000) / 200)
# ratio=800 → 0.27   ratio=1000 → 0.50   ratio=1500 → 0.92
```

selector 가 보정 폭을 confidence 로 가중 (`±0.20 * conf`, `±0.30 * conf`).
insight 가 톤 조절 (`< 0.5` 인용 생략, `0.5~0.8` 추정 톤, `≥ 0.8` 단정 톤).

---

## 결정 품질 (Decision Quality) 측정

**outcome 메트릭(F1·AUC)이 아니라 decision match rate 가 핵심 KPI**.

### KP_tab 시리즈 (jh 단독 KPI)

| KPI | 기준 | 측정 위치 |
|---|---|---|
| `KP_tab1` 평균 결정 정확도 | ≥ 0.85 | `test_decision_quality.py::test_average_decision_quality` |
| `KP_tab2` 최악 케이스 정확도 | ≥ 0.70 | `test_decision_quality.py::test_per_scenario_decision_quality` |
| `KP_tab3` 완벽 처리율 | ≥ 0.50 | (수동 계산) |
| `KP_tab4` false alarm | ≤ 0.05 | `test_decision_quality.py::test_no_false_positive_on_clean_data` |

### Decision audit 시나리오 (8 종 합성 데이터)

`test_decision_quality.py::SCENARIOS`:
- `clean_balanced` — false positive 검증
- `extreme_imbalance` — anomaly 라우팅 검증
- `target_leakage` — 보수적 모델 강제 검증
- `p_gg_n` — 선형 모델 강제 검증
- `high_cardinality` — Cat/LGB 우선 검증
- `multicollinear` — Ridge 강제 + LR 배제
- `imbalanced_moderate` — class_weight 권고
- `id_overload` — archetype 매칭 검증

각 시나리오마다 `expected_decisions` 와 실제 시스템 결정을 비교 → match rate 산출.

### 시스템 정체성 측정

| Before | After |
|---|---|
| "Titanic F1 0.83 → 0.84" (outcome) | "임의 데이터에서 적합한 결정 88% 일치" (decision) |
| 같은 데이터 반복 비교 | 다양한 archetype 데이터 audit |

---

## 운영 가이드 — 어디서 결과가 보이는지

| 결과 | 노출 위치 | 모듈 |
|---|---|---|
| archetype primary + confidence | insight 텍스트 첫 문장, 배포 체크리스트 표 | archetype.py |
| SHAP top-3 + summary chart | PPT 슬라이드 13/14, OUT-07 MD, OUT-04 HTML | explainability.py |
| ECE before/after + reliability diagram | PPT 슬라이드 14·17, 배포 체크리스트, 모니터링 KPI 표 | calibration.py |
| 4 임계치 전략 + expected_cost + PR curve | PPT 슬라이드 14, 임계치 전략 비교 표 | threshold_optimizer.py |
| 운영 권고 표 4 종 (배포/모니터링/임계치/재학습) | PPT 슬라이드 18·19, OUT-02 PDF 부록 | output_extras.py |

### 사용자 입력 채널

| 입력 | 위치 | 효과 |
|---|---|---|
| `cost_matrix={"fp": 5, "fn": 180}` | `state.category_extras["tabular"]["cost_matrix"]` | cost-min 임계치 활성화, A/B 권고비율 조정 |
| (향후) `archetype_override` | 동일 위치 | archetype 보정 비활성화 (전문가 모드) |

---

## 테스트 카탈로그 (190+ 건)

```
tests/handlers/tabular/
├── conftest.py
├── test_smoke.py                       (2)   — 핸들러 등록 검증
├── test_e2e.py                         (5)   — Titanic·Iris·Adult E2E
├── test_profiler.py                    (23)  — 신호 6 종
├── test_preprocessor.py                (57)  — 15 transforms + 누수 가드
├── test_selector.py                    (89)  — baselines + CV + diagnostics + EDA + insight
│
├── test_decision_quality.py            (13)  — 8 archetype 시나리오 audit
├── test_shap_explainability.py         (24)  — explainer 자동 선택 + sanity
├── test_calibration.py                 (23)  — ECE + Platt/Isotonic + honest CV
├── test_threshold_optimizer.py         (24)  — 4 전략 + cost 비대칭
└── test_robustness.py                  (12)  — distribution shift / drift / adversarial / extreme
```

실행:
```bash
pytest tests/handlers/tabular/ -q      # 전체 (~30s)
pytest tests/handlers/tabular/test_decision_quality.py -v   # decision audit
pytest tests/handlers/tabular/test_robustness.py -v         # 방어 테스트
```

---

## 확장 가이드

### 새 archetype 추가

1. `archetype.py::ARCHETYPE_PRIORITY` 에 이름 추가 (우선순위 결정)
2. `EXPECTED_DECISIONS` 에 룰 추가 (selector_top1_in / preprocessing_must 등)
3. `classify_archetypes()` 본체에 매칭 조건 추가
4. `_compute_confidence()` 에 sigmoid 임계값·width 추가
5. `insight.py::_archetype_insight_line()` 에 1 문장 메시지 추가
6. `test_decision_quality.py` 에 시나리오 합성 데이터 + audit 추가
7. `test_robustness.py` 의 false positive 가드에 영향 없는지 확인

### 새 explainer 추가 (예: DeepExplainer for NN)

1. `explainability.py::_select_explainer_type()` 에 라우팅 규칙 추가
2. `explain()` 본체에 explainer 인스턴스화 분기
3. `test_shap_explainability.py::TestExplainerSelection` 에 케이스 추가

### 새 calibration 방법 (예: Temperature scaling for DL)

1. `calibration.py::fit_temperature()` 신설 (이미 docstring 자리만 있음)
2. `calibrate()` 의 methods_tried 에 시도 추가
3. `test_calibration.py::TestCalibratorFit` 에 검증 추가

### 새 임계치 전략

1. `threshold_optimizer.py::find_<strategy>()` 신설
2. `optimize_thresholds()` 의 strategies dict 에 추가
3. PR curve 차트의 색 + 마커 추가
4. `_build_threshold_strategy_table()` 의 표 행 추가

---

## 자주 묻는 질문

**Q. archetype 매칭이 잘못된 것 같다. 어떻게 진단?**
A. `state.category_extras["tabular"]["selector_expert"]` 또는 selector 의 `archetype.signals` 값 확인. 매칭 근거가 거기 있음. confidence 가 0.5 근처면 경계선 매칭 — 임계값 튜닝 후보.

**Q. SHAP top features 가 비어있다.**
A. `shap_result["skipped_reason"]` 확인. 일반적 원인:
- `no_best_model` — best_model 미설정
- `baseline_skip` — Dummy/LR/Ridge/Lasso 는 의미 없어서 skip
- `shap_import_failed` — `pip install shap==0.45.1`
- `model_reload_failed` — MinIO 경로 또는 SHA256 불일치

**Q. ECE 가 NaN 나옴.**
A. `calibration.compute_ece` 가 빈 입력에서 0.0 반환. NaN 나오면 y_proba 자체에 NaN 있음 — predict_proba 출력 점검.

**Q. cost-min 임계치가 0.01 이나 0.99 끝점에 박힘.**
A. cost_matrix 가 극단 비대칭 (FN/FP > 100×) 이거나 데이터에 양성/음성 한쪽 신호 매우 약함. 정상 동작이지만 사용자에게 알릴 가치 있음.

**Q. proposer.g2 가 anomaly_detection 권고했는데 무시하고 tabular_ml 가고 싶다.**
A. G2 에서 두번째 옵션 (state.category 유지) 선택. archetype 룰은 권고일 뿐 — 사용자 의도 우선.

---

## 변경 이력

### Day 11 ~ Day 11++ 세션 (5 단위)

| 단위 | 변경 | 신규 모듈 | 신규 테스트 | 누적 |
|---|---|---|---|---|
| 1. Archetype + confidence | profiler/selector/proposer/insight/output_extras 통합 | `archetype.py` | 13 | 191 |
| 2. SHAP | TreeExplainer/LinearExplainer/KernelExplainer 자동 | `explainability.py` | 24 | 215 |
| 3. Calibration | ECE + Platt/Isotonic + K-fold CV honest | `calibration.py` | 23 | 238 |
| 4. Cost-sensitive threshold | 4 전략 + expected_cost + 보정 확률 사용 | `threshold_optimizer.py` | 24 | 262 |
| 5. Robustness | 4 모듈 방어 테스트 | — | 12 | 274 |

**누적: 신규 모듈 4 + 테스트 +97 (177 → 274) + 회귀 0건**

### 다음 작업 우선순위

| 우선 | 항목 | 비고 |
|---|---|---|
| 🟡 | `tabular_dl` 본구현 | pytorch-tabular wired + MC Dropout + DL E2E |
| 🟡 | SMOTE import 에러 해결 | imbalanced-learn ↔ sklearn ABI 핀 |
| 🟢 | Temperature scaling (DL용 캘리브레이션) | `calibration.py::fit_temperature` 자리 비어있음 |
| 🟢 | archetype_override 채널 | 전문가 모드 |

---

## 관련 문서

- `CLAUDE.md` — 팀 룰, 영역 매트릭스
- `AGENTS.md` — 룰 카탈로그 (R-001~R-1008)
- `작업설계/Day10_jh_tabular_E2E_design.md` — Day 10 E2E 설계
- `작업설계/Day10_jh_tabular_E2E_detailed_design.md` — 상세 구현 명세
- `docs/PARALLEL_WORK_GUARDS.md` — 병렬 작업 가드 구조
- `agents/handlers/timeseries/` — CS 영역 (참고용)
- `agents/handlers/anomaly/` — NY 영역 (참고용)
