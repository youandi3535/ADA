# category_extras 표준 키 명세

> 작성자 : HJ
> 작성일 : 2026-06-05
> 근거 : CS HJ-6 협의 항목 (`docs/cs_hj_handoff_report.md`)
> 영역 : `ada/core/state.py:101` `category_extras: dict[str, dict[str, Any]]`

## 개요

`PipelineState.category_extras` 는 카테고리별 격리 컨테이너입니다. CS/NY/jh 멤버가 자기 카테고리 키 안에만 쓰기로 충돌을 방지합니다 (Day 0 H0-4).

본 문서는 **각 멤버가 사용 중인 키를 명세화** 하여 cross-category 의존 발생 시 호환성 검토의 기준점으로 삼습니다.

## 키 매핑 — `state.category` vs `category_extras` 최상위 키

⚠ **중요**: `state.category` (4 카테고리 enum) 와 `category_extras` 의 최상위 키가 **다름**.

| state.category | category_extras 키 | 담당 |
|----------------|-------------------|------|
| `"timeseries"` | `"timeseries"` | CS |
| `"anomaly_detection"` | `"anomaly"` ⚠ | NY |
| `"tabular_ml"` | `"tabular"` ⚠ | jh (tabular_ml + tabular_dl 공유) |
| `"tabular_dl"` | `"tabular"` ⚠ | jh |

→ **소비측은 `state.category` 로 분기하되, `category_extras` 접근 시 위 매핑 테이블을 따라야 함**. 핸들러 dispatcher (`agents/handlers/__init__.py`) 가 이미 매핑하므로 일반 에이전트는 자기 핸들러 내부에서만 접근.

## 카테고리별 표준 키

### CS — `category_extras["timeseries"]`

| 키 | 타입 | 채우는 곳 | 사용처 |
|----|------|----------|--------|
| `freq` | str | profiler.g1 / proposer.g1 | preprocessor, pipeline, output_extras (FREQ_UNIT_KO) |
| `horizon_hint` | int | proposer.g1 | pipeline, output_extras 차트 제목 |
| `forecast_kind` | str ("point"/"interval"/"quantile") | proposer.g1 | output_extras 표·차트 |
| `variate` | str ("univariate"/"multivariate") | proposer.g1 | output_extras 차트 제목 |
| `exog_columns` | list[str] | preprocessor (권위 소스) | selector, pipeline SARIMAX |
| `seasonal_period` | int | profiler / eda | preprocessor STL, output_extras decomposition |
| `outlier_detail` | dict | profiler | preprocessor 이상치 처리 |
| `horizon` | int | proposer (선택) | search_space (tuner) |

### NY — `category_extras["anomaly"]`

| 키 | 타입 | 채우는 곳 | 사용처 |
|----|------|----------|--------|
| `preprocessing` | dict | preprocessor / proposer | eda, selector, proposer |
| `pipeline` | dict | pipeline / training_executor | insight |

비고: `evaluator` 는 `category_extras` 의존 제거 (X-6: top-level state 가 데이터 버스). `state.eval_result` 사용.

### jh — `category_extras["tabular"]`

| 키 | 타입 | 채우는 곳 | 사용처 |
|----|------|----------|--------|
| (자유 — preprocessor 가 dict 통째로 저장) | dict | preprocessor.g1 | preprocessor, output_extras |

→ `tabular_ml` 와 `tabular_dl` 이 동일 키를 공유 (jh 담당 단일 영역).

## 규약

1. **격리 원칙** — 각 카테고리 키 안에만 쓰기. 다른 카테고리 키 접근 금지.
2. **권위 소스** — 같은 정보를 여러 곳에서 채우지 말 것. 명세표의 "채우는 곳" 이 유일 권위 소스.
3. **타입 안전** — 신규 키 추가 시 본 문서 갱신 + TypedDict 정의 권장 (`ada/core/category_extras_types.py` 신설 예정).
4. **호환성 변경** — 키 이름·타입 변경은 HJ 협의 필수 (영향 멤버 사전 통보).

## 향후 작업

- [ ] `ada/core/category_extras_types.py` TypedDict 신설 (mypy 지원)
- [ ] `state.category` → `category_extras` 최상위 키 매핑 헬퍼 (`get_category_extras(state)`) 신설
- [ ] anomaly_detection 의 키 `"anomaly"` → `"anomaly_detection"` 통일 검토 (호환성 변경, NY 협의 필요)

## 변경 이력

| 일자 | 변경 | 담당 |
|------|------|------|
| 2026-06-05 | 초안 (CS HJ-6 협의 항목 응답) | HJ |
