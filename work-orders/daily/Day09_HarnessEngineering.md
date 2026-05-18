# Day 9 — Harness Engineering 전체
> 프로젝트: Adaptive AutoAI Pipeline Agent | 2주 스프린트 Day 9/14

---

## 📋 오늘의 목표

파이프라인의 자가 진화(Self-Evolving) 핵심 메커니즘인 **Harness 시스템** 전체를 구축한다.
EvalAgent가 모델 품질을 1차 룰 기반 + 2차 LLM 심층 평가로 검증하고, 실패 시 HarnessAuditor가
실패 원인을 분석하여 새로운 규칙을 자동으로 AGENTS.md에 누적한다.
LangSmith 기반 텔레메트리로 모든 에이전트 실행 이력을 추적한다.

- EvalAgent: 임계치 판정 + Claude Opus 4.7 심층 평가
- RulesManager: 신뢰도 기반 자동/수동 규칙 분기
- HarnessAuditor: 실패 분석 → proposed_rule JSON 생성
- SkillsLoader: 카테고리별 도메인 지식 주입
- Telemetry: LangSmith + PostgreSQL 이중 추적

---

## 👤 담당자

**D** (Harness Engineering 전담)

---

## ✅ 작업 목록

### 1. EvalAgent 구현

- [ ] `agents/eval_agent.py` 파일 생성
  - `EvalAgent(BaseAgent)` 클래스 정의
  - LLM 사용: Claude Opus 4.7
  - **임계치 상수 정의:**
    ```python
    THRESHOLDS = {
        'classification':    {'val_f1': 0.6},
        'regression':        {'val_r2': 0.5},
        'forecasting':       {'val_mape': 0.3, 'mode': 'max_below'},
        'anomaly_detection': {'val_auc': 0.7},
        'image':             {'val_f1_macro': 0.6},
        'nlp':               {'val_f1': 0.6},
    }
    ```
  - **1차 룰 기반 판정 로직:**
    - `forecasting`의 `val_mape`: `mode='max_below'` → 값이 0.3 이하여야 통과
    - 그 외: 설정값 이상이어야 통과
    - 임계치 미달 시 즉시 1차 실패 판정
  - **2차 LLM 심층 평가 (1차 통과 시):**
    - 메트릭 품질 (절대적 수치 vs 도메인 기준)
    - 안정성 (train/val 격차, 분산)
    - 커버리지 (클래스 불균형, 예외 케이스)
    - 해석력 (SHAP 연동 가능 여부)
  - 최종 실패 시: `audit_failure(failure_info)` 호출, `state.retry_count += 1`
  - 최종 통과 시: `state.next_agent = 'insight'`
  - 실패 시: `route_after_eval(state)` 라우팅 함수 호출

- [ ] `route_after_eval(state)` 라우팅 함수 구현
  - `retry_count < max_retries (기본 3)` → `'training_executor'` 재루프
  - `retry_count >= max_retries` → `'error_recovery'`

### 2. RulesManager 구현

- [ ] `harness/rules_manager.py` 파일 생성
  - `RulesManager` 클래스 정의
  - **`add_rule(rule: dict)` 메서드:**
    - `rule['confidence'] >= 0.8` → AGENTS.md 자동 머지 (즉시 적용)
    - `rule['confidence'] < 0.8` → PR 큐 저장 (`pending_rules` 테이블)
    - 중복 규칙 체크: `rule['category'] + rule['root_cause']` 조합으로 기존 규칙 검색
    - 중복 시 `confidence` 값만 업데이트 (누적 학습)
  - **`load_active_rules() -> list[dict]` 메서드:**
    - PostgreSQL `rules` 테이블에서 `is_active=True` 조건 조회
    - 카테고리별 필터링 지원: `load_active_rules(category='classification')`
    - 최근 30일 이내 규칙 우선 정렬
  - **`_generate_rule_code() -> str` 메서드:**
    - 형식: `'R-A{순번:03d}'` (예: R-A001, R-A002, ...)
    - DB `rules` 테이블 `max(rule_code)` 기반 순번 자동 증가
  - **`_format_rule_for_agents_md(rule: dict) -> str` 메서드:**
    - AGENTS.md 마크다운 형식으로 변환
    - 예시 출력:
      ```markdown
      ### R-A001 — 클래스 불균형 탐지 규칙
      - **카테고리**: classification
      - **근본 원인**: class_imbalance
      - **적용 에이전트**: preprocessing_strategist, feature_engineer
      - **신뢰도**: 0.92
      - **생성일**: 2026-05-15
      ```
  - **`_merge_to_agents_md(formatted_rule: str)` 메서드:**
    - `AGENTS.md` 파일의 `## 자동 생성 규칙` 섹션에 append

### 3. HarnessAuditor 구현

- [ ] `harness/auditor.py` 파일 생성
  - `HarnessAuditor` 클래스 정의
  - LLM 사용: Claude Opus 4.7
  - **AUDITOR_PROMPT 정의:**
    ```
    당신은 AI 파이프라인 실패를 분석하여 새로운 규칙을 도출하는 전문가입니다.
    실패 정보를 분석하고 반드시 아래 JSON 형식으로만 응답하세요:
    {
      "category": "실패가 발생한 데이터 카테고리",
      "root_cause": "실패의 근본 원인 (구체적으로)",
      "proposed_rule": "향후 동일 실패를 방지하기 위한 구체적 규칙",
      "confidence": 0.0~1.0 사이의 신뢰도 점수,
      "applies_to_agents": ["적용 대상 에이전트 이름 리스트"]
    }
    ```
  - **`audit_failure(failure_info: dict) -> dict` 메서드:**
    - 입력: `{job_id, category, agent_name, error_type, metrics, retry_count, error_detail}`
    - LLM 호출로 proposed_rule JSON 생성
    - `rules_manager.add_rule(proposed_rule)` 호출
    - 반환: LLM 응답 dict
  - **신뢰도 기준 해석:**
    - `confidence >= 0.9`: 결정론적 패턴 (즉시 자동 적용)
    - `0.6 <= confidence < 0.9`: 확률적 패턴 (confidence >= 0.8 이면 자동, 미만은 PR 큐)
    - `confidence < 0.6`: 불확실 → 인간 검토 필요 (`pending_review` 테이블)
  - **감사 이력 저장:** PostgreSQL `audit_history` 테이블에 모든 감사 결과 저장

### 4. SkillsLoader 구현

- [ ] `harness/skills_loader.py` 파일 생성
  - `SkillsLoader` 클래스 정의
  - **`load_skill(category: str, topic: str) -> str` 메서드:**
    - 파일 경로: `harness/skills/{category}/{topic}.md`
    - 파일 없으면 `FileNotFoundError` 대신 빈 문자열 반환 (에이전트 중단 방지)
    - 캐싱: `functools.lru_cache(maxsize=128)` 적용으로 반복 I/O 방지
  - **`save_success_pattern(category: str, config: dict, metrics: dict)` 메서드:**
    - PostgreSQL `success_patterns` 테이블에 저장
    - 컬럼: `category`, `model_name`, `hyperparams`, `metrics`, `data_size`, `created_at`
    - 성공 패턴 누적으로 향후 탐색 공간 좁히기에 활용
  - **`get_best_practices(category: str) -> list[dict]` 메서드:**
    - `success_patterns` 테이블에서 상위 10개 성공 패턴 반환
    - 프롬프트 컨텍스트 주입용

### 5. Telemetry 구현

- [ ] `harness/telemetry.py` 파일 생성
  - **`@contextmanager langsmith_tracer(agent_name: str, job_id: str)` 구현:**
    - `langsmith.Client()` 연결
    - run 시작/종료 시각 측정
    - 예외 발생 시 LangSmith에 에러 기록
  - **`log_agent_run(job_id, agent_name, status, input_tokens, output_tokens, duration_ms)` 구현:**
    - PostgreSQL `agent_runs` 테이블 INSERT
    - 컬럼: `job_id`, `agent_name`, `status` (success/failure/skip), `input_tokens`, `output_tokens`, `duration_ms`, `created_at`
    - LangSmith `client.create_run(...)` 동시 전송
  - **`get_agent_stats(agent_name: str) -> dict` 구현:**
    - `agent_runs` 테이블 집계: 성공률, 평균 토큰, 평균 실행시간 반환

### 6. Skills 파일 6종 작성

- [ ] `harness/skills/tabular_ml/main.md` 작성
  - 행 수별 모델 선택 가이드:
    - `~1,000행`: RandomForest (과적합 방지 우선)
    - `~10,000행`: XGBoost, LightGBM
    - `10만 행 이상`: LightGBM, CatBoost (속도 우선)
  - 결측값 비율별 전처리:
    - `5% 이하`: KNN Imputer (정확도 우선)
    - `20% 이하`: Median/Most Frequent Imputer
    - `50% 이상`: 컬럼 드롭 권장
  - 흔한 실패 패턴:
    - 타겟 누설 (target leakage): 분리 시점 이후 정보 포함 컬럼 제거
    - 클래스 불균형: SMOTE, class_weight='balanced', 임계값 조정

- [ ] `harness/skills/timeseries/main.md` 작성
  - 데이터 길이별 모델 선택:
    - `100 미만`: Prophet (빠른 수렴), ARIMA (해석 가능)
    - `100 이상`: LSTM (복잡 패턴 포착)
  - 계절성 패턴 처리: `Prophet seasonality_mode='multiplicative'`
  - 외부 변수 포함: Prophet `add_regressor()` 활용

- [ ] `harness/skills/image/main.md` 작성
  - 데이터 수별 전략:
    - `500 미만`: freeze backbone (ImageNet 가중치 유지), FC layer만 학습
    - `500 이상`: full fine-tuning (learning_rate=1e-5 권장)
  - 이미지 증강: `RandomHorizontalFlip`, `ColorJitter`, `RandomRotation(15)`
  - 클래스 불균형: `WeightedRandomSampler` 활용

- [ ] `harness/skills/nlp/main.md` 작성
  - 한국어 특화 전처리: 특수문자 제거, 이모지 처리, 띄어쓰기 정규화
  - 모델: `klue/bert-base` (한국어 사전학습)
  - 파인튜닝: `AutoModelForSequenceClassification.from_pretrained('klue/bert-base')`
  - 토큰 길이: `max_length=128` (리뷰), `max_length=512` (장문)

- [ ] `harness/skills/anomaly/main.md` 작성
  - 이상치 비율별 알고리즘:
    - `1% 미만`: One-Class SVM (희귀 이상)
    - `1~5%`: Isolation Forest (범용)
    - `5% 이상`: LOF (밀도 기반)
  - AutoEncoder: 재구성 오차 기반 threshold 설정 (`mean + 3*std`)
  - threshold 설정: ROC 곡선 기반 최적 임계값 탐색

- [ ] `harness/skills/tabular_dl/main.md` 작성
  - TabNet vs MLP 선택:
    - 특성 선택이 중요한 경우: TabNet (Attention 기반 feature selection)
    - 범용 회귀/분류: MLP (빠른 학습)
  - 배치 크기: 256~2048 (GPU VRAM 기준)
  - 학습률: `1e-3 ~ 1e-4`, `CosineAnnealingLR` 스케줄러 권장

---

## 🏗️ 구현 명세

### EvalAgent 핵심 구조

```python
class EvalAgent(BaseAgent):
    llm_model = "claude-opus-4-7"

    THRESHOLDS = {
        'classification':    {'val_f1': 0.6},
        'regression':        {'val_r2': 0.5},
        'forecasting':       {'val_mape': 0.3, 'mode': 'max_below'},
        'anomaly_detection': {'val_auc': 0.7},
        'image':             {'val_f1_macro': 0.6},
        'nlp':               {'val_f1': 0.6},
    }

    def run(self, state: PipelineState) -> PipelineState:
        metrics = state.best_model['metrics']
        threshold = self.THRESHOLDS[state.category]

        # 1차 룰 기반 판정
        if not self._rule_based_check(metrics, threshold, state.category):
            state.eval_result = 'fail_rule'
            state.retry_count += 1
            auditor.audit_failure({
                'job_id': state.job_id,
                'category': state.category,
                'agent_name': 'eval_agent',
                'error_type': 'threshold_not_met',
                'metrics': metrics,
                'retry_count': state.retry_count,
            })
            return state

        # 2차 LLM 심층 평가
        llm_result = self._llm_deep_eval(state)
        if llm_result['verdict'] == 'pass':
            state.eval_result = 'pass'
            state.next_agent = 'insight'
        else:
            state.eval_result = 'fail_llm'
            state.retry_count += 1
            auditor.audit_failure({**llm_result, 'job_id': state.job_id})
        return state

    def _rule_based_check(self, metrics: dict, threshold: dict, category: str) -> bool:
        for key, value in threshold.items():
            if key == 'mode':
                continue
            mode = threshold.get('mode', 'min_above')
            actual = metrics.get(key, 0)
            if mode == 'max_below' and actual > value:
                return False
            elif mode == 'min_above' and actual < value:
                return False
        return True
```

### RulesManager 핵심 구조

```python
class RulesManager:
    def add_rule(self, rule: dict) -> str:
        rule_code = self._generate_rule_code()
        rule['rule_code'] = rule_code
        # 중복 체크
        existing = db.query(
            "SELECT id FROM rules WHERE category=%s AND root_cause=%s",
            (rule['category'], rule['root_cause'])
        )
        if existing:
            db.execute(
                "UPDATE rules SET confidence=%s WHERE id=%s",
                (rule['confidence'], existing[0]['id'])
            )
            return existing[0]['id']
        # 신뢰도 기반 분기
        if rule['confidence'] >= 0.8:
            formatted = self._format_rule_for_agents_md(rule)
            self._merge_to_agents_md(formatted)
            rule['is_active'] = True
        else:
            rule['is_active'] = False  # pending_rules 상태
        db.execute("INSERT INTO rules ...", rule)
        return rule_code

    def _generate_rule_code(self) -> str:
        max_code = db.query("SELECT MAX(rule_code) FROM rules")[0]['max']
        next_num = int(max_code.split('A')[1]) + 1 if max_code else 1
        return f"R-A{next_num:03d}"
```

### HarnessAuditor 핵심 구조

```python
class HarnessAuditor:
    llm_model = "claude-opus-4-7"

    AUDITOR_PROMPT = """
당신은 AI 파이프라인 실패를 분석하여 새로운 규칙을 도출하는 전문가입니다.
실패 정보를 분석하고 반드시 아래 JSON 형식으로만 응답하세요:
{
  "category": "실패가 발생한 데이터 카테고리",
  "root_cause": "실패의 근본 원인 (구체적으로)",
  "proposed_rule": "향후 동일 실패를 방지하기 위한 구체적 규칙",
  "confidence": 0.0~1.0 사이의 신뢰도 점수,
  "applies_to_agents": ["적용 대상 에이전트 이름 리스트"]
}
"""

    def audit_failure(self, failure_info: dict) -> dict:
        prompt = self.AUDITOR_PROMPT + f"\n실패 정보:\n{json.dumps(failure_info, ensure_ascii=False, indent=2)}"
        response = llm_client.invoke(prompt, model=self.llm_model)
        proposed_rule = json.loads(response.content)
        self.rules_manager.add_rule(proposed_rule)
        db.execute("INSERT INTO audit_history ...", {**failure_info, 'proposed_rule': proposed_rule})
        return proposed_rule
```

### Telemetry 핵심 구조

```python
from contextlib import contextmanager
import time

@contextmanager
def langsmith_tracer(agent_name: str, job_id: str):
    start_time = time.time()
    run_id = None
    try:
        run_id = ls_client.create_run(name=agent_name, run_type='chain',
                                       inputs={'job_id': job_id})
        yield run_id
        duration_ms = int((time.time() - start_time) * 1000)
        ls_client.update_run(run_id, end_time=datetime.utcnow(), status='success')
    except Exception as e:
        ls_client.update_run(run_id, end_time=datetime.utcnow(),
                             status='error', error=str(e))
        raise

def log_agent_run(job_id: str, agent_name: str, status: str,
                  input_tokens: int, output_tokens: int, duration_ms: int):
    db.execute("""
        INSERT INTO agent_runs (job_id, agent_name, status, input_tokens, output_tokens, duration_ms, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
    """, (job_id, agent_name, status, input_tokens, output_tokens, duration_ms))
```

---

## 📁 생성/수정 파일 목록

| 경로 | 작업 | 설명 |
|------|------|------|
| `agents/eval_agent.py` | 신규 생성 | 1차 룰 + 2차 LLM 평가 에이전트 |
| `harness/rules_manager.py` | 신규 생성 | 규칙 추가/조회/AGENTS.md 머지 |
| `harness/auditor.py` | 신규 생성 | 실패 분석 → proposed_rule 생성 |
| `harness/skills_loader.py` | 신규 생성 | 카테고리별 스킬 파일 로드 |
| `harness/telemetry.py` | 신규 생성 | LangSmith + DB 텔레메트리 |
| `harness/skills/tabular_ml/main.md` | 신규 생성 | 표형 ML 도메인 지식 |
| `harness/skills/timeseries/main.md` | 신규 생성 | 시계열 도메인 지식 |
| `harness/skills/image/main.md` | 신규 생성 | 이미지 도메인 지식 |
| `harness/skills/nlp/main.md` | 신규 생성 | NLP 한국어 도메인 지식 |
| `harness/skills/anomaly/main.md` | 신규 생성 | 이상탐지 도메인 지식 |
| `harness/skills/tabular_dl/main.md` | 신규 생성 | 딥러닝 표형 도메인 지식 |
| `harness/__init__.py` | 신규 생성 | 패키지 초기화 |
| `AGENTS.md` | 수정 | `## 자동 생성 규칙` 섹션 추가 |
| `db/migrations/003_harness_tables.sql` | 신규 생성 | rules, audit_history, agent_runs, success_patterns 테이블 |

---

## 🔗 의존성 & 선행 조건

### Day 8까지 완료되어야 하는 항목

- `BaseAgent` 클래스 (LLM 호출 지원)
- `PipelineState.best_model`, `retry_count`, `eval_result` 필드
- PostgreSQL 연결 유틸리티 (`shared/db.py`)
- LangSmith API 키 환경변수 설정
- `AGENTS.md` 파일 존재 (기본 구조 포함)

### Python 패키지 의존성

```
langsmith>=0.1.77
anthropic>=0.28.0
psycopg2-binary>=2.9.9
```

### 환경 변수

```
LANGCHAIN_API_KEY=ls__...
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=ada-pipeline
ANTHROPIC_API_KEY=sk-ant-...
AGENTS_MD_PATH=/app/AGENTS.md
```

### DB 스키마 (Day 9 신규)

```sql
CREATE TABLE rules (
    id SERIAL PRIMARY KEY,
    rule_code VARCHAR(20) UNIQUE,
    category VARCHAR(50),
    root_cause TEXT,
    proposed_rule TEXT,
    confidence FLOAT,
    applies_to_agents JSONB,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE audit_history (
    id SERIAL PRIMARY KEY,
    job_id VARCHAR(100),
    failure_info JSONB,
    proposed_rule JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE agent_runs (
    id SERIAL PRIMARY KEY,
    job_id VARCHAR(100),
    agent_name VARCHAR(100),
    status VARCHAR(20),
    input_tokens INTEGER,
    output_tokens INTEGER,
    duration_ms INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## ✔️ 완료 기준 (Done Criteria)

- [ ] `HarnessAuditor.audit_failure()` 호출 시 `proposed_rule` JSON 정상 반환 (모든 필드 포함)
- [ ] `RulesManager.add_rule()` 신뢰도 0.8 이상 → AGENTS.md 자동 업데이트, 미만 → DB pending 저장 확인
- [ ] AGENTS.md 자동 업데이트: `R-A001` 형식 규칙 코드 포함 여부 확인
- [ ] `EvalAgent` 1차 룰 판정: `val_f1=0.5` 입력 → 즉시 실패 판정 (LLM 호출 없음) 확인
- [ ] `EvalAgent` 2차 LLM 판정: 1차 통과 시 LLM 호출 발생 로그 확인
- [ ] `SkillsLoader.load_skill('tabular_ml', 'main')` → 비어있지 않은 문자열 반환 확인
- [ ] `log_agent_run()` 호출 후 `agent_runs` 테이블 INSERT 확인
- [ ] LangSmith 대시보드에서 에이전트 run 추적 확인

---

## ⚠️ 주의사항 & 제약

1. **LLM JSON 파싱 실패 대응**: `HarnessAuditor`의 LLM 응답이 JSON이 아닐 경우 `with_backoff` 재시도, 2회 실패 시 `confidence=0.5` 기본값으로 수동 처리.
2. **AGENTS.md 동시 쓰기 방지**: 여러 job이 동시에 룰을 추가할 경우 파일 락(`fcntl.flock`) 사용.
3. **신뢰도 인플레이션**: 동일 실패 패턴이 반복될수록 신뢰도가 누적 상승하는 메커니즘이 의도치 않게 낮은 품질 규칙을 자동 적용할 수 있음. 최대 자동 적용 신뢰도 상한(0.95)을 두어 인간 검토 우회 방지.
4. **LangSmith Rate Limit**: 고부하 시 LangSmith 전송 실패 가능. PostgreSQL 저장을 항상 우선 수행하고 LangSmith는 비동기 전송.
5. **Skills 파일 인코딩**: 한국어 포함 `.md` 파일은 UTF-8 인코딩 명시 (`open(..., encoding='utf-8')`).
6. **Opus 비용 관리**: EvalAgent는 1차 룰 판정 통과 모델에 대해서만 LLM 호출. 불필요한 Opus 호출 최소화.
7. **규칙 코드 순번 레이스 컨디션**: `_generate_rule_code()`는 DB 트랜잭션 내 `SELECT FOR UPDATE`로 중복 방지.

---

## 🆕 v2 확장 작업 (마스터 설계서 §5 · §6)

> Day9 의 v2 핵심: Harness가 단순히 실패를 분석하는 데 그치지 않고, **SelfLearningAgent / AutoErrorHandlerAgent** 와 명확히 연동되도록 인터페이스를 정의한다. Day14, Day16에서 본격 구현되며 여기서는 베이스 + 정책 룰만 깔아둔다.

### 1. SelfLearning ↔ Harness 분리 원칙

- Harness(RulesManager + Auditor): **실패 패턴 → 규칙 텍스트** 생성에 집중 (사람이 읽는 룰)
- SelfLearning: **성공/실패 → 임베딩 + 레시피 + 워밍** 에 집중 (기계가 쓰는 KB)
- 두 시스템은 동일한 `failure_logs` 를 읽지만 출력 채널이 다름

### 2. EvalAgent v2 — SelfLearning 호출 훅

- [ ] EvalAgent 가 통과/실패 모두 `SelfLearningClient.enqueue_distill(job_id)` 호출
- [ ] 통과: success_pattern + recipe 후보로 적재
- [ ] 실패: failure_lesson 후보로 적재
- [ ] 단, 게이트 인터럽트(awaiting) 상태에서는 enqueue 보류 (잡 종료 시점에 한 번만)

### 3. HarnessAuditor v2 — 룰 임베딩 추가

- [ ] proposed_rule 생성 후 룰 텍스트(`category + root_cause + proposed_rule`)를 임베딩
- [ ] `rules.pgvector_embedding` 컬럼에 저장 → 향후 유사 룰 충돌 탐지에 사용
- [ ] 동일 임베딩 유사도 0.92 이상 룰 존재 시 신규 INSERT 대신 confidence 증분만 (R-501 변형)

### 4. RulesManager v2 — superseded_by 체인

- [ ] 동일 카테고리·root_cause 의 신규 룰이 더 높은 confidence 로 추가될 때:
  - 기존 룰 `is_active=false`, `superseded_by=새 룰 ID` 설정
  - AGENTS.md에는 마지막 활성 버전만 노출

### 5. AutoErrorHandler 인터페이스 정의 (Day16 구현)

- [ ] `agents/auto_error_handler.py` 스텁 작성:
  ```python
  class AutoErrorHandlerAgent:
      def handle(self, state, exc, agent_name) -> PipelineStateV2: ...
      def _hash_error(self, ...) -> str: ...
      def _lookup_kb(self, error_hash) -> Optional[dict]: ...
      def _apply_patch(self, patch, state) -> bool: ...
      def _call_claude_cli(self, ctx) -> dict: ...
  ```
- [ ] Day16에서 본격 구현. 여기서는 인터페이스 + Day3 BaseAgent의 try/except 훅이 호출하도록 연결만.

### 6. Telemetry v2 — agent_registry heartbeat

- [ ] BaseAgent의 `log_agent_run` 에서 매 호출 종료 시 `agent_registry.last_heartbeat = NOW(), avg_duration_ms (이동평균), success_rate (최근 100회)` 업데이트
- [ ] 대시보드 §9에서 실시간 표시

### 7. AGENTS.md 자동 룰 — 보안 룰도 자동 누적

- [ ] SecurityGuardAgent 가 차단한 프롬프트 인젝션 시도가 N회 반복되면 Auditor가 R-7xx 자동 룰 생성

### 8. 완료 기준 (v2 추가)

- [ ] `SELECT count(*) FROM rules WHERE pgvector_embedding IS NOT NULL;` ≥ 0 (스프린트 동안 누적)
- [ ] AutoErrorHandlerAgent 스텁 import 성공
- [ ] agent_registry.last_heartbeat 업데이트 동작 확인

### 9. 주의사항 (v2)

- 동일 잡에서 EvalAgent가 재루프로 여러번 호출되어도 distill 큐 발행은 잡 종료(END) 시점에만
- Auditor와 SelfLearning이 동시에 동일 failure_logs 읽을 때 락 충돌 주의 — Auditor가 우선, SelfLearning은 5초 후 폴링
