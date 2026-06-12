# CS 의도 핸드오버 — G2~G6 헤더 정합 + 카테고리 인지 (2026-06-11)

> Claude Code (또는 다른 작업자) 가 본인 CS 의 의도를 빠르게 파악할 수 있게 정리한 문서.
> 본인 = CS (timeseries 종주), HJ G2/G3 작업을 위임 받아 frontend·api·schema_validator 도 손댐.

---

## 1. 본인 소개 + 권한

- **본인 = CS** — timeseries 카테고리 종주. 본인 단독 영역:
  - `agents/handlers/timeseries/`
  - `pipelines/timeseries/`
  - `tests/handlers/timeseries/`
  - `requirements/handlers-timeseries.txt`
- **HJ 위임 영역** — 본 작업 한정 위임:
  - `frontend/app.py` — G2~G6 헤더·desc·modal 정합
  - `api/routes/pipeline.py` / `api/routes/upload.py` — 카테고리 전달 흐름
  - `agents/data_profiler.py` — 카테고리 분류 후처리 (최후 수단 가드)
  - `agents/schema_validator.py` — 검증 fallback 완화
- **R-규칙 회피** — 페르소나 (`_CATEGORY_SYSTEM_PROMPT` 등) 는 수정 안 함. 영역 침범 최소화.

---

## 2. 작업 목적

**ADA 의 G2~G6 화면 (분석 방향 / 방법론 / 모델 전략 / 모델 채택 / 산출물) 의 헤더·desc·팝업이 사용자가 업로드한 데이터의 카테고리 (시계열·정형 ML·정형 DL·이상탐지) 에 맞춰 정확히 표시되도록.**

기존 문제:
- 시계열 데이터를 넣어도 frontend 가 "정형 데이터" 로 표시
- 사용자가 G2 응답 후 cur=2 진입 시점에 시계열로 보정됨 (= G2→G3 구간이 꼬임)
- desc 가 일반 표현 ("정형 ML 데이터에 맞는 EDA…") 뿐, 실제 EDA 항목 (정상성·자기상관 등) 없음
- modal (팝업) 헤더가 "N단계 분석 중" 으로 고정, 카테고리 무관
- 정형 ML / 정형 DL 구분 표시 없음 ("정형 데이터" 통합)
- **anomaly_detection 카테고리를 frontend 가 "이상치" 라고 표시** (통계 용어와 헷갈림)

---

## 3. 본인 의도 (완전 명세)

### 3-1. 최종 기능 요구사항

1. **각 cur 화면의 헤더·desc·팝업** 이 카테고리별 (`timeseries` / `tabular_ml` / `tabular_dl` / `anomaly_detection` / `_default`)
2. **desc 는 실제 EDA·전처리·모델 항목** 반영
   - 시계열 EDA: 정상성·자기상관·계절성
   - 정형 ML EDA: 분포·결측·상관관계·클래스 균형
   - 정형 DL EDA: 고차원 시각화·피처 상호작용
   - 이상탐지 EDA: 이상탐지 신호·contamination·heavy-tail
3. **게이트 정체성 정합** — frontend cur 값과 backend AGENT_PHASE_MAP 단계 매핑 정확:
   - cur=0 (G1) = 데이터 파악 (supervisor → data_profiler → schema_validator)
   - cur=1 (G2) = 분석 방향 결정 (gate_direction LLM)
   - cur=2 (G3) = 방법론 결정 (eda_agent + gate_methodology — **본격 EDA**)
   - cur=3 (G4) = 모델 전략 (preprocessing + feature_engineer)
   - cur=4 (G5) = 모델 채택 (model_selection + training)
   - cur=5 (G6) = 산출물 (eval + insight)
4. **G1→G2 팝업 (cur=0 modal)** = G1 인라인 헤더와 동기화 ("데이터를 파악하는 중입니다" / "G1 — Data Understanding")
5. **G2→G3 팝업 (cur=2 modal + cur=1 modal)** = cur=2 loading 헤더와 동기화
   - cur=1 modal 도 포함 — 사용자 G2 응답 후 eda_agent 진행 시점이 cur=1 유지라서
6. **정형 ML / DL 구분** — `tabular_ml.h2` 에 "ML" 추가 ("정형 ML 데이터"), `tabular_dl.h2` 는 "DL" 그대로
7. **"이상치" → "이상탐지"** — anomaly_detection 카테고리 표현 정정
8. **사용자 직전 cur 선택값 plug-in** (2차 작업) — 모델명 등 직전 선택이 다음 cur 의 desc 에 반영:
   - cur=1 "단기 예측 (1~14일)" 선택 → cur=2 desc 에 "단기 예측 (1~14일) 분석 방향에 맞춰…"
   - cur=2 "Prophet" 선택 → cur=3 desc 에 "Prophet 방법론에 맞춰…"
   - cur=3 "Prophet + Seasonal Boost" 선택 → cur=4 desc 에 "Prophet + Seasonal Boost 모델 전략을 학습·튜닝…"
   - cur=4 "Prophet" 선택 → cur=5 desc 에 "Prophet 모델의 평가·인사이트…"
   - 사용자 미선택 / G1 auto → plug-in 빠지고 generic 폴백
9. **backend 카테고리 인지 정확** — LLM 이 데이터 자체 (date 컬럼, 의도 키워드, 데이터 크기) 보고 자연스럽게 분류
10. **강제 override 는 최후 수단** — LLM 정확도 우선, 강한 신호 누락 시만 보정

### 3-2. 본인이 한 정정 (시간 순)

| # | 정정 내용 | 정정 사유 |
|---|---|---|
| 1 | "ML 은 설명란에만" → "h2 에도 ML 표시" | 정형 DL 과 구분 위해. 본인 화면이 "정형 데이터" 로만 나오면 정형 ML 인지 정형 DL 인지 모름. |
| 2 | "이상치" → "이상탐지" | **anomaly_detection 카테고리를 frontend desc 에서 "이상치" 라고 잘못 표기. "이상치" 는 통계 용어 (= outlier 값 자체), "이상탐지" 는 분석 task 이름. 본인 명시: "이상탐지를 이상치라고 (잘못) 해서 그런 거야".** 카테고리 표현은 "이상탐지" 로 통일. |
| 3 | "강제 X" → "강제는 최후 수단" | LLM 정확도 우선 + 강한 신호 누락 시만 보정. 강제 override 가 나쁜 게 아니라 정상 흐름이 안 잡힐 때 최후 수단으로 쓰는 것. |
| 4 | "오늘 풀 받은 기준 원본 복구 + 진짜 필요한 것만" | 변경 최소화. 잘못 박은 코드 정리. |
| 5 | "없으면 굳이 하지마" | 진짜 필요한 변경 없으면 안 박음. |
| 6 | "잘되어 있으면 놔도" | 작동 정상이면 현 상태 유지. 불필요한 추가 변경 X. |
| 7 | "유연하게 들어오는 데이터로" | 데이터 자체 신호 (date 컬럼, intent, 크기) 로 LLM 이 자연 인지. 강제 룰로 맞추는 게 아님. |

### 3-3. 1차 구현 범위 (현재 진행 중)

**G2 + G2→G3 + G2→G3 팝업 만**:
- C-1: cur=1 static (G2 분석 방향 선택 화면)
- C-2: cur=2 loading (G2→G3 EDA 작업 중)
- C-3: cur=2 modal + cur=1 modal (G2→G3 팝업)

별개 트랙: cur=0 modal (G1→G2 팝업 = G1 인라인 헤더 동기화).

### 3-4. 2차 작업 (1차 완료 후)

- cur=3·4·5 카테고리별 매핑 (G3·G4·G5·G6)
- 각 cur 의 static + loading + modal 모두 같은 패턴
- **user_choice plug-in** (모델명 등 직전 선택 반영)
- 주제 선정 팝업 (TOPIC_HEADER_BY_CATEGORY) 카테고리화 (별도 트랙)
- API `gate_detail` 의 user_choice forward
- Dockerfile 최적화 (재빌드 시간 단축)

### 3-5. 별개 트랙

- **G1→G2 트랙** — cur=1 loading 인라인 헤더 + cur=1 modal (또는 cur=0 modal) 동기화 — "G2~G6 와는 별개로 생각"

### 3-6. 안 건드림

- **G1 화면 자체 (cur=0)** — 업로드·분석 의도 입력 화면 그대로
- **`STAGE_LOAD_MSGS` shift** — HJ 원안 유지
- **navbar `steps[i].sub`** ("G2 · EDA" 등) — HJ 원안 유지

---

## 4. 현재 상태 진단 + 핵심 원인

### 4-1. 본인이 본 화면 흐름

| 시점 | 표시 | 원인 |
|---|---|---|
| 0~5% | 시계열 (사용자 선택 또는 prefetch) | 정상 |
| **5~33%** | **정형 (잘못)** | `data_profiler` LLM 잘못 + `_persist_detection` 가 DB 즉시 박음 + prefetch cache 우회 |
| 33% (cur=2 진입) | 시계열 (보정) | `gate_methodology` 가 사용자 G2 응답 보고 재분류 |

### 4-2. 핵심 원인 (정독 결과)

**(1) `agents/data_profiler.py:121` 의 `_persist_detection` 가 LLM 결과 즉시 DB 에 박음**:
```python
await self._persist_detection(state, category, target_column)
# 내부: job.category = category  ← DB 즉시 변경
```

**(2) `_detect_category_safe()` 의 3가지 경로 중 가드가 1개만 통과**:
- (a) `state.category` 그대로 (사용자 G1 명시 선택) → 가드 우회
- (b) `_try_prefetch_cache(df)` hit → 가드 우회
- (c) `_llm_detect_category()` → 가드 통과

**(3) `agents/schema_validator.py` 의 fallback 강제 변경** (HEAD 시점):
```python
fallback = "tabular_ml"   # 검증 실패 시 모든 카테고리 → 정형 강제
```

### 4-3. 해결 (오늘 박은 변경)

**(A) `__call__` 본체 (라인 121 직전) 에 최후 수단 가드 박음** — 3가지 경로 모두 통과:
```python
# 시계열 가드: date 컬럼 명확하면 보정
if category != "timeseries":
    _dc = _detect_date_column(df)
    if _dc:
        category = "timeseries"

# 이상탐지 가드: intent 키워드 + target 없음 보정
if category not in ("timeseries", "anomaly_detection"):
    if anomaly_intent_keywords and not target_column:
        category = "anomaly_detection"

await self._persist_detection(state, category, target_column)
```

**(B) `schema_validator` fallback 완화** — 검증 실패 시 카테고리 유지 + warning:
```python
# 기존: category = "tabular_ml" 강제 변경
# 변경: 카테고리 유지 + warning 추가 + 다음 단계 진행
return state.with_update(
    validation={**v, "warnings": [warn_msg]},
    next_agent="gate_direction",
)
```

**(C) `_llm_detect_category` user_prompt 에 4 카테고리 인지 신호 추가**:
```
date_column_detected: {col_name 또는 none}
anomaly_intent_keywords: {매칭 키워드 또는 none}
data_scale: rows=N, cols=M
```

**(D) `prefetch_analyze` (api/routes/upload.py) user_prompt 에 동일 신호 추가** — Ollama LLM 도 정확도 향상

**(E) `_detect_date_column` (본인 영역 timeseries handler) 의 2.5순위 wide format 감지** — `2010.01, 2024-Q1, 201001` 등 통계청 wide format CSV 인식

**(F) frontend `modalHtml` cur=0 / cur=1 / cur=2 분기 동기화** — 카테고리별 헤더 표시

**(G) frontend `GATE_HEADER_BY_CATEGORY` 의 desc 를 실제 EDA 항목으로 정정 + ML/DL 표시 + 이상탐지 정정**

---

## 5. 변경 파일 목록

| 파일 | 변경 내용 |
|---|---|
| `agents/data_profiler.py` | __call__ 본체에 최후 수단 가드 (시계열·이상탐지) + _llm_detect_category user_prompt 에 4 카테고리 인지 신호 |
| `agents/schema_validator.py` | fallback 완화 (검증 실패 시 카테고리 유지) |
| `agents/handlers/timeseries/profiler.py` (CS 영역) | _detect_date_column 의 2.5순위 wide format 감지 추가 |
| `api/routes/upload.py` | prefetch user_prompt 에 동일 4 카테고리 신호 |
| `frontend/app.py` | GATE_HEADER_BY_CATEGORY 정정 (실제 EDA 항목 + ML/DL + 이상탐지) + modalHtml cur=0/1/2 분기 + gateHeader 휴리스틱 제거 |
| `docs/g2_header_revamp_plan.md` | 기획안 v4 |
| `docs/cs_g2_g6_intent_handover.md` | 본 핸드오버 문서 |

---

## 6. 작업 방식 규칙 (본인 명시)

1. **항상 시작 전 정독** — 프로젝트 + 기획안 모든 폴더·파일 첫글자~마지막글자
2. **헷갈리지 않게 기획안 만들고** 본인 검토 후 진행
3. **한 commit = 한 작업** — claude 는 commit 안 만듦. 본인이 직접 commit.
4. **docker 재빌드 + 화면 확인은 본인 수행** — frontend 는 bind mount 라 `docker restart ada-frontend` 면 충분. backend (data_profiler, schema_validator, upload.py 등) 는 `docker compose build ada-api ada-worker` 필수
5. **Edit/Write 잘림 주의** — 큰 변경은 bash heredoc + awk 또는 작은 단위 Edit
6. **회귀 시 즉시 복원** — 디버깅보다 정상화 우선
7. **솔직한 대답** — 본인 다른 정책과 어긋나면 동조 금지
8. **본인 의도 핵심 = 최후 수단 강제 + LLM 인지 우선** — 강제로만 풀려 하지 말고 본인 의도 (= 데이터 자체로 자연 인지) 우선
9. **G1 (cur=0) 안 건드림** — modal 헤더 동기화만 (인라인 헤더는 그대로)
10. **본인 명시 범위만** — "추가로 박지 마", "없으면 굳이 하지마" 정신

---

## 7. 본인 측 다음 단계

```cmd
docker compose -f docker\docker-compose.yml build ada-api ada-worker
docker compose -f docker\docker-compose.yml up -d --no-deps ada-api ada-worker
docker restart ada-frontend
```

확인:
- 시계열 데이터 (COVID19, 산업별 취업자 등) 업로드 → 5%부터 끝까지 시계열 표시
- 이상탐지 데이터 + 의도 "이상탐지" → 이상탐지 표시
- 정형 ML / DL 구분 표시
- G2→G3 modal 동기화 (cur=1, cur=2 둘 다)

확인 OK → 1차 완료 → 2차 (cur=3·4·5 카테고리 매핑 + user_choice plug-in + 주제 선정 팝업) 진행.

---

## 8. 본인 검토 받을 것

본 문서 작성 후 본인이 검토 → 다음 4 가지 확인:

1. **의도 정합** — 위 §3 의 본인 요구사항 정확히 반영?
2. **변경 파일 (§5)** — HJ 위임 받은 영역 외 침범 없음?
3. **1차 구현 범위 (§3-3)** — G2 + G2→G3 + G2→G3 팝업만 확정?
4. **본인 측 docker 재빌드 결과** — 카테고리 인식 + 헤더 표시 정상?

본인이 답 / 정정 알려주면 다음 단계 진행.
