# 분석 파이프라인 깊이 감사 리포트 (2026-06-16)

> 목적: "어떤 데이터가 와도 4개 카테고리(tabular_ml / tabular_dl / timeseries / anomaly)
> 전 단계(EDA·전처리·피처엔지니어링·모델선택·튜닝·평가)가 실무 빅데이터 분석가 수준으로
> 빈틈없이 수행되는가"를 코드 근거로 전수 진단.
>
> 방법: ① 단계별 실무 체크리스트(이상값)를 기준으로 grep 커버리지 1차 측정 →
> ② 의심 영역 정독 검증. grep 카운트는 힌트일 뿐이며, 갭은 정독으로 확정 표기.
>
> 제약 반영: 서버 성능 한계로 **무거운 딥러닝·대형 모델은 의도적으로 제외**. 따라서
> "무거운 모델 부재"는 갭이 아니라 설계 결정으로 본다. 모델선택·튜닝은 "경량 모델
> 내에서의 정교함"으로 평가한다.

---

## 0. 카테고리 결정 시점

- **G1(데이터 프로파일링)** 에서 `data_profiler.py` 가 LLM+휴리스틱으로 카테고리를 자동 1차 결정
  ([data_profiler.py:135-176](../agents/data_profiler.py)).
- **G2(사용자 옵션 선택)** 에서 최종 확정·보정 ([data_profiler.py:482](../agents/data_profiler.py) 재분류).
- 즉 G1 통과 시 잠정 카테고리, G2 선택이 최종.

## 1. 아키텍처 사실

- 단계 dispatch: 공유 에이전트(`data_profiler`, `eda_agent`, `feature_engineer`,
  `model_selection`, `hyperparameter_tuner`, `eval_agent`)가 카테고리 핸들러
  `agents/handlers/{cat}/` 로 위임.
- capability 목록: `profile/plan/apply/apply_split/charts/score/evaluate/generate/assets/build/g1/g2`
  ([_base.py:62-75](../agents/handlers/_base.py)).
- **피처엔지니어링 전용 capability·모듈이 없음** — `feature_engineer.py` 는 dispatcher일 뿐,
  실제 파생피처는 `preprocessor.apply()` 안에 전처리와 통합.
- 누수 안전 분할(apply_split → train fit → val transform) 인프라는 견고(전 카테고리 적용).

## 2. 단계 × 카테고리 커버리지 매트릭스 (grep 1차)

낮을수록 갭 후보. `★` = 정독으로 확정한 실제 갭.

| 단계 / 항목 | tabular | timeseries | anomaly |
|---|---|---|---|
| EDA 이상치 진단 | 0 ★ | 35 | 87 |
| EDA 분포/정규성 | 4 | 0 | 25 |
| EDA 상관/공선성(VIF) | 16 | 4 | 5 |
| 전처리 결측대체 | 28 | 3 | 2 ★ |
| 전처리 인코딩 | 34 | 0 | 1 ★ |
| 전처리 문자/타입정제 | 21 | 9 | 3 ★ |
| 전처리 누수안전 | 21 | 29 | 9 |
| FE 파생/변환 | 50 | 71 | 6 ★ |
| FE 피처선택 | 6 ★ | 0 ★ | 0 ★ |
| 평가 교차검증 | 24 | 14 | 0 |
| 평가 캘리브/강건성 | 별도파일* | 7 | 1 |
| 튜닝 탐색엔진 | 30 | 68 | 0 ★ |

\* tabular 캘리브/강건성은 evaluator.py 가 아니라 calibration.py·diagnostics.py 별도 모듈에 존재(커버됨).

## 3. 확정 갭 (정독 검증 완료)

### P0 — "어떤 데이터가 와도" 직결 (사용자 핵심 우려)

**G-1. anomaly·timeseries 입력 견고성 결여 — 범주형/문자 컬럼 폐기**
- 근거: [anomaly/preprocessor.py:158](../agents/handlers/anomaly/preprocessor.py) `select_dtypes(include=[np.number])`,
  [timeseries/preprocessor.py:630](../agents/handlers/timeseries/preprocessor.py) 동일.
- 영향: 범주형·문자 컬럼을 통째로 버림. 인코딩(anomaly 1, ts 0)·문자정제 미흡으로
  "글자가 엉망인 데이터", `"$1,234"`·`"1.2K"` 같이 문자로 들어온 숫자, 깨진 인코딩이
  오면 **그냥 무시되어 정보 손실**. tabular(인코딩 34, 문자정제 21)만 견고.

**G-2. anomaly 결측 대체 단순 — 행 통째 삭제**
- 근거: [anomaly/preprocessor.py:164-187](../agents/handlers/anomaly/preprocessor.py)
  (결측률 >30% 컬럼 drop + 점 데이터 `dropna()`).
- 영향: 결측이 흩어진 와이드 데이터에서 행 대량 삭제 → 표본 급감. KNN/MICE 등 대체 없음.

### P1 — 구조/깊이

**G-3. 피처선택 단계 전 카테고리 부재 (구조적)**
- 근거: FE가 전처리에 통합, 피처선택 capability 없음. grep: tabular 6 / ts 0 / anomaly 0.
- 영향: 고차원·노이즈 피처 자동 제거(분산/상호정보/중요도 기반) 미흡.

**G-4. anomaly·tabular_dl 하이퍼파라미터 튜닝 통째 스킵**
- 근거: [hyperparameter_tuner.py:32-35](../agents/hyperparameter_tuner.py) 가
  `pipelines.anomaly.search_space` / `pipelines.tabular_dl.search_space` 를 import 하나
  **두 파일 모두 없음** → `hpo_skip_no_search_space` 로 튜닝 미수행.
- 비고: anomaly는 비지도라 튜닝 설계가 까다롭지만, contamination·n_estimators 등
  핵심 파라미터는 경량 탐색 가능.

**G-5. anomaly 파생피처 부재**
- 근거: `apply()` 가 RobustScaler→Winsorize→PCA 만, 파생피처 생성 없음(FE grep 6).

### P2 — 보강

**G-6. tabular EDA 이상치 시각/진단 부재** (전처리엔 처리 있으나 EDA 산출물엔 없음).
**G-7. timeseries EDA 분포/정규성·잔차 진단 약함** (grep 0).
**G-8. anomaly 교차검증/안정성 평가 약함** (비지도 특성 감안하되 bootstrap 안정성 등 보강 여지).

## 4. 보완 우선순위 & 영역

| 우선 | 갭 | 영역(담당) | 회귀 위험 |
|---|---|---|---|
| P0 | G-1 입력 견고성(범주형/문자/깨진숫자) | anomaly(NY), timeseries(CS) | 중 — 전처리 입력단 변경 |
| P0 | G-2 결측 대체 고도화 | anomaly(NY) | 중 |
| P1 | G-3 피처선택 단계 도입 | 공통 구조(HJ) + 각 핸들러 | 중~상 |
| P1 | G-4 anomaly/tabular_dl search_space 추가 | anomaly(NY), tabular(jh) | 하 — 신규 파일 |
| P1 | G-5 anomaly 파생피처 | anomaly(NY) | 중 |
| P2 | G-6~8 EDA/평가 보강 | 각 핸들러 | 하 |

## 5. 보완 시 불변 원칙 (회귀 0)

1. 각 갭은 **독립 변경 + 즉시 테스트**(`pytest tests/handlers/{cat}/`)로 격리.
2. 모든 신규 처리는 **graceful fallback** — 실패 시 기존 동작으로 떨어져 "오늘보다 나쁠 수 없음".
3. 입력 견고화는 **추가만**(범주형도 살린다) — 기존 수치 경로의 결과 비트는 보존.
4. 백엔드 변경은 [deploy-backend-worker-restart] 절차로 워커 재시작·검증까지 직접 수행.
5. 영역 외(타 멤버) 수정은 사용자(마스터) 승인 하에 진행, 변경 전 고지.
