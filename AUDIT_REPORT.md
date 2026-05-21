# ADA v2 전수 검증 보고서

> 작성일: 2026-05-21
> 범위: Day01~21 구현 산출물의 정적 분석 / 상호참조 / 일관성 / 동작 검증
> 결과: **🟢 19/19 테스트 통과 + 1개 critical 이슈 수정 완료**

---

## 1. 검증 결과 요약

| 검증 항목 | 결과 |
|---|:---:|
| Python syntax (110 파일) | ✅ 100% 컴파일 |
| 모듈 import (73 모듈) | ✅ 73/73 |
| 27 에이전트 클래스 카운트 | ✅ 27/27 |
| 27 에이전트 ↔ 페르소나 매핑 | ✅ 빠짐/잉여 0 |
| 27 에이전트 ↔ AGENT_NAME_TO_CLASS | ✅ 일치 |
| 27 에이전트 ↔ seeds.AGENT_META | ✅ 일치 |
| 25 LangGraph 노드 + 5 게이트 인터럽트 | ✅ 25 + START/END |
| AGENT_PROGRESS_MAP 키 ↔ 그래프 노드 | ✅ 0 mismatch |
| next_agent literal ↔ 그래프 노드 | ✅ 0 invalid |
| 4 카테고리 (PipelineFactory) | ✅ tabular_ml/dl/timeseries/anomaly |
| 5 산출물 (GENERATORS) | ✅ OUT-01/02/03/04/07 |
| 26 ORM 테이블 ↔ Alembic 001 | ✅ 0 mismatch |
| FastAPI 라우터 (19 endpoint) | ✅ 모두 등록 |
| Celery 큐 4종 (pipeline/training/output/harness) | ✅ task_routes 정확 |
| pytest 통과율 | ✅ **19/19 (100%)** |

---

## 2. 발견 → 수정한 Critical 이슈

### ❗ 이슈 #1 — `agents/stubs.py` 가 본격 구현을 무력화
**현상**: `orchestrator/graph.py` 는 `from agents.stubs import SupervisorAgent, ...` 로 27 클래스를 가져오는데, `stubs.py` 에는 **자체 정의된 통과용 스텁** 클래스가 있었음. 결과적으로 `agents/supervisor.py`, `agents/data_profiler.py` 등의 **본격 구현이 그래프에서 사용되지 않았음**.

```python
# 검증 출력:
SupervisorAgent:        stub is real? False
DataProfilerAgent:      stub is real? False
PreprocessChoice:       stub is real? False
graph imports SupervisorAgent from: agents.stubs   ← 스텁 모듈
```

**수정**:
- `agents/stubs.py` 를 **re-export aggregator** 로 재작성. 27 클래스 모두 본격 구현 모듈(`agents/<name>.py`, `agents/gates/<name>.py`)에서 임포트.
- 누락되어 있던 5 게이트 Proposer + FineTuneExecutor 6개 본격 구현 신규 작성:
  - `agents/gates/_base_gate.py` — BaseGate 공통 베이스
  - `agents/gates/analysis_proposer.py` (G1)
  - `agents/gates/methodology_proposer.py` (G2)
  - `agents/gates/model_strategy_proposer.py` (G3)
  - `agents/gates/model_comparison_reporter.py` (G4)
  - `agents/gates/output_type_selector.py` (G5)
  - `agents/fine_tune_executor.py`

**검증 후**:
```
✓ SupervisorAgent                    ← agents.supervisor
✓ AnalysisProposerAgent              ← agents.gates.analysis_proposer
✓ ModelComparisonReporterAgent       ← agents.gates.model_comparison_reporter
✓ FineTuneExecutorAgent              ← agents.fine_tune_executor
... (27/27 모두 본격 구현 모듈에서 옴)
```

### ⚠ 이슈 #2 — `tools/__init__.py` 부재
**현상**: `tools/` 는 implicit namespace package 로 동작은 했지만, 명시적 패키지 마커가 없어 IDE/lint 도구가 혼동.
**수정**: `tools/__init__.py` 추가.

### ℹ 이슈 #3 — `agents/stubs.py` 파일에 NUL 바이트 잔재 (Cowork Write 툴 부산물)
**현상**: 파일 끝에 3,838바이트의 NUL(\x00) 패딩이 남아 Python 임포트 시 `AGENT_NAME_TO_CLASS` 가 인식 안 됨.
**수정**: bash heredoc 로 파일을 깨끗이 재작성.

---

## 3. 검증 후에도 정상 동작 확인 (실제 실행)

### 에이전트 4개 미니 실행
```
Supervisor       → next_agent: intent_elicitor, task: auto         ✓
IntentElicitor   → G0 spec keys: [task_keyword,target_kind,...]    ✓
DataProfiler     → next_agent: error_recovery (MinIO 미연결 fallback) ✓
```

### 게이트/메트릭/평가 시나리오 (LLM 키 없이 fallback)
```
MetricsAggregator → best=XGBoost(val_f1=0.86) / next=gate_best_model ✓
G4 ModelComparisonReporter → proposals=[XGBoost,LightGBM,RandomForest] ✓
G5 OutputTypeSelector → proposals=[발표 패키지, 리포트 패키지, 최소 패키지] ✓
ModelSelection (fallback) → top3=[XGBoost,LightGBM,RandomForest]      ✓
FineTune (XGBoost)        → skipped, next=eval_agent                  ✓
FineTune (TabTransformer) → fine_tuned=True, next=eval_agent          ✓
EvalAgent (val_f1=0.86)   → passed=True, next=explainability          ✓
```

### LangGraph 25 노드 + 5 게이트 인터럽트
```
엣지 수: 34
__start__ → supervisor
supervisor → intent_elicitor / data_profiler / error_recovery (조건부 3)
intent_elicitor → data_profiler
data_profiler → schema_validator
schema_validator → gate_direction / error_recovery (조건부 2)
gate_direction → eda_agent
eda_agent → gate_methodology
gate_methodology → preprocessing_strategist
preprocessing_strategist → feature_engineer
feature_engineer → preprocessing_choice / gate_model_strategy (조건부 2)
preprocessing_choice → gate_model_strategy
gate_model_strategy → model_selection → hyperparameter_tuner → training_executor
training_executor → training_monitor → metrics_aggregator → gate_best_model
gate_best_model → fine_tune_executor / eval_agent (조건부 2)
fine_tune_executor → eval_agent
eval_agent → explainability / training_executor / error_recovery (조건부 3)
explainability → insight → gate_outputs → report_composer → self_learning_dispatch → __end__
error_recovery → supervisor / __end__ (조건부 2)

INTERRUPT_AFTER: ['gate_direction','gate_methodology','gate_model_strategy','gate_best_model','gate_outputs']
```

---

## 4. v2 스코프 일관성 (메모리 ada_scope_decision)

| 권위 정의 | 코드 위치 | 일치 |
|---|---|:---:|
| 카테고리 4종 | `ada/core/state.py: CATEGORIES` | ✅ |
| 산출물 5종 | `outputs/__init__.py: GENERATORS` | ✅ |
| 5 게이트 | `orchestrator/graph.py: INTERRUPT_AFTER` | ✅ |
| 27 에이전트 | `agents/stubs.py: ALL_AGENT_CLASSES` | ✅ |
| MLflow 4 실험 | `scripts/mlflow_init.py: EXPERIMENTS` | ✅ |
| PPT 4 색상 | `outputs/__init__.py: CATEGORY_COLORS` | ✅ |
| 트랜스포머 8종 | `agents/fine_tune_executor.py: TRANSFORMER_MODELS` | ✅ |

---

## 5. 추가된 / 변경된 파일

| 위치 | 변경 |
|---|---|
| `agents/gates/__init__.py` | **신규** |
| `agents/gates/_base_gate.py` | **신규** — BaseGate 공통 |
| `agents/gates/analysis_proposer.py` | **신규** — G1 |
| `agents/gates/methodology_proposer.py` | **신규** — G2 |
| `agents/gates/model_strategy_proposer.py` | **신규** — G3 |
| `agents/gates/model_comparison_reporter.py` | **신규** — G4 |
| `agents/gates/output_type_selector.py` | **신규** — G5 |
| `agents/fine_tune_executor.py` | **신규** — 트랜스포머 미세조정 |
| `agents/stubs.py` | **전면 재작성** — re-export aggregator |
| `tools/__init__.py` | **신규** — 명시적 패키지 마커 |

---

## 6. 최종 통과한 19개 테스트

```
tests/integration/test_e2e_smoke.py::test_smoke_imports                PASSED
tests/integration/test_harness.py::test_kb_fingerprint_idempotent      PASSED
tests/integration/test_harness.py::test_distill_constants              PASSED
tests/integration/test_security.py::test_prompt_injection_blocked      PASSED
tests/integration/test_security.py::test_jwt_roundtrip                 PASSED
tests/integration/test_security.py::test_rbac_perm_matrix              PASSED
tests/test_agents_count.py::test_all_agent_classes_27                  PASSED
tests/test_graph_build.py::test_graph_builds                           PASSED
tests/test_outputs_registry.py::test_generator_count                   PASSED
tests/test_outputs_registry.py::test_generator_codes                   PASSED
tests/test_personas.py::test_personas_count                            PASSED
tests/test_personas.py::test_personas_prefix                           PASSED
tests/test_pipeline_factory.py::test_supported_categories              PASSED
tests/test_pipeline_factory.py::test_unknown_category_raises           PASSED
tests/test_schema_validator.py::test_tabular_ml_min_rows_fail          PASSED
tests/test_schema_validator.py::test_tabular_ml_ok                     PASSED
tests/test_schema_validator.py::test_timeseries_requires_date          PASSED
tests/test_state.py::test_state_with_update                            PASSED
tests/test_state.py::test_state_to_dict                                PASSED
===================== 19 passed in 1.10s =====================
```

---

## 7. 결론

🟢 ADA v2 의 Day01~21 구현은 **계획대로 설계되어 있고, 발견된 critical 이슈 1건 + minor 이슈 2건을 모두 수정 완료**했습니다.

특히 가장 중요했던 "stubs 가 본격 구현을 무력화하던 문제" 가 수정되면서, 이제 LangGraph 그래프가 **본격 구현된 27 에이전트** 를 노드로 실행합니다. 메모리의 v2 스코프(4 카테고리/5 산출물)도 코드 전반에 일관 적용되어 있음을 확인했습니다.

— 끝.
