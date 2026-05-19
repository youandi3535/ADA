# Day 3 — 공통 모듈 + CI/CD
> 프로젝트: Adaptive AutoAI Pipeline Agent | 2주 스프린트 Day 3/14

---

## 📋 오늘의 목표

팀 전원이 합의한 공통 모듈(shared/)을 완성하고, 모든 에이전트의 기반이 되는 `BaseAgent` 추상 클래스를 구현한다. AGENTS.md 초안을 작성하여 팀 전체의 개발 규칙을 문서화하며, GitHub Actions CI/CD 파이프라인과 담당자 폴더 격리 pre-commit hook을 설정한다. 이 날 이후로 공통 모듈 변경은 반드시 팀 전체 합의를 거쳐야 한다.

---

## 👤 담당자

- **전체 팀 (A / B / C / D)** 공동 작업 — shared/ 패키지는 팀 합의 필수
- shared/state.py: A 주도 (LangGraph 상태 설계 책임)
- shared/config.py, shared/logger.py: B 주도
- agents/base.py: C 주도
- AGENTS.md, CI/CD 설정: D 주도
- pre-commit hook, isolation_check: A + D 협업

---

## ✅ 작업 목록

### 1. shared/state.py — PipelineState Pydantic 모델

- [ ] `PipelineState(BaseModel)` 클래스 정의
- [ ] 핵심 식별자 필드:
  - `job_id: str`
  - `file_id: str`
  - `category: str` — tabular_ml / tabular_dl / timeseries / anomaly_detection
  - `task: str` — classification / regression / clustering / anomaly_detection
- [ ] 입력 옵션 필드:
  - `target_column: Optional[str] = None`
  - `user_question: Optional[str] = None`
- [ ] 데이터 분석 결과 필드:
  - `data_profile: Optional[dict] = None`
  - `validation: Optional[dict] = None` — {is_valid, errors, warnings}
  - `preprocessing_plan: Optional[list] = None`
  - `preprocessed_data_id: Optional[str] = None` — MinIO 경로
- [ ] EDA/시각화 결과:
  - `eda_charts: list[str] = []` — MinIO 경로 목록
- [ ] 모델 관련 필드:
  - `model_candidates: list[str] = []` — 선정된 모델명 목록
  - `trained_models: list[dict] = []` — {model_name, metrics, minio_path, mlflow_run_id}
  - `training_warnings: list[str] = []`
  - `best_model: Optional[dict] = None` — {model_name, metrics, minio_path}
- [ ] 해석/평가 결과:
  - `explanations: Optional[dict] = None` — SHAP 결과
  - `eval_result: Optional[dict] = None` — {passed, metrics, threshold_violations}
- [ ] 리포트 산출물:
  - `insights: Optional[str] = None` — LLM 생성 인사이트 텍스트
  - `ppt_path: Optional[str] = None` — MinIO 경로
  - `pdf_path: Optional[str] = None` — MinIO 경로
  - `script_path: Optional[str] = None` — 재현 스크립트 MinIO 경로
  - `model_path: Optional[str] = None` — 최종 모델 MinIO 경로
- [ ] 오케스트레이션 제어 필드:
  - `retry_count: int = 0`
  - `max_retries: int = 3`
  - `error: Optional[str] = None`
  - `next_agent: Optional[str] = None`
- [ ] `model_config = ConfigDict(arbitrary_types_allowed=True)` 설정
- [ ] `to_dict()` 메서드 — JSON 직렬화 가능한 dict 반환 (UUID, datetime 변환 포함)

### 2. shared/config.py — Settings 클래스

- [ ] `class Settings(BaseSettings)` 정의 (pydantic-settings)
- [ ] `model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")`
- [ ] 전체 설정 필드 정의:
  ```python
  # Anthropic
  anthropic_api_key: str
  
  # LangSmith
  langsmith_api_key: str = ""
  langsmith_project: str = "ada-pipeline"
  
  # Database
  database_url: str
  
  # Redis
  redis_url: str = "redis://redis:6379/0"
  
  # MinIO
  minio_endpoint: str = "minio:9000"
  minio_access_key: str
  minio_secret_key: str
  minio_bucket: str = "autoai-artifacts"
  
  # MLflow
  mlflow_tracking_uri: str = "http://mlflow:5000"
  mlflow_s3_endpoint_url: str = "http://minio:9000"
  
  # App
  log_level: str = "INFO"
  max_upload_size_mb: int = 100
  pipeline_timeout_min: int = 30
  environment: str = "development"
  ```
- [ ] `settings = Settings()` 싱글턴 인스턴스 생성 (모듈 레벨)
- [ ] `@property` 로 `database_url_async` 반환 (`postgresql+asyncpg://...`)

### 3. shared/logger.py — structlog JSON 로거

- [ ] `structlog.configure()` 설정:
  - processors: `add_log_level`, `add_timestamp`, `JSONRenderer`
  - wrapper_class: `BoundLogger`
  - context_class: `dict`
- [ ] `get_logger(name: str)` 팩토리 함수 작성
- [ ] 공통 컨텍스트 바인딩: `job_id`, `agent_name` 자동 포함
- [ ] 로그 레벨은 `settings.LOG_LEVEL` 에서 동적으로 설정
- [ ] `log_agent_run(job_id, agent_name, status, duration_ms, tokens)` 편의 함수 작성

### 4. agents/base.py — BaseAgent 추상 클래스

- [ ] `class BaseAgent(ABC)` 정의
- [ ] `__init__` 메서드:
  - `self.logger = get_logger(self.__class__.__name__)`
  - `self.llm = Anthropic(api_key=settings.anthropic_api_key)`
  - `self.model_name: str = "claude-sonnet-4-6"` (기본값, 서브클래스에서 오버라이드 가능)
- [ ] `@abstractmethod __call__(self, state: PipelineState) -> PipelineState` 선언
- [ ] `@asynccontextmanager log_agent_run(self, state)` 컨텍스트 매니저:
  - 시작 시 `agent_runs` 테이블에 running 상태 삽입
  - 완료 시 completed + duration_ms + token 사용량 업데이트
  - 예외 발생 시 failed 상태 + error 메시지 업데이트
  - structlog에 INFO/ERROR 레벨 로그 출력
- [ ] `_call_llm(self, system_prompt, user_prompt, max_tokens=4096)` 헬퍼 메서드:
  - `anthropic.messages.create()` 호출
  - 응답 토큰 카운트 자동 추적 (`self._last_input_tokens`, `self._last_output_tokens`)
  - JSON 파싱 실패 시 재시도 1회
- [ ] `_parse_json(self, text: str) -> dict` 헬퍼 메서드:
  - 마크다운 코드 블록 (`json ... `) 자동 제거
  - `json.loads()` 실패 시 상세 오류 로깅

### 5. AGENTS.md 초안 작성

- [ ] **R-001 ~ R-005 핵심 룰**:
  - R-001: 모든 시크릿은 `.env` 파일로만 관리, 코드 하드코딩 금지
  - R-002: 공통 모듈(`shared/`) 변경은 팀 전체 합의 + PR 리뷰 2인 이상 승인
  - R-003: 에이전트는 반드시 `BaseAgent` 상속. 독립 구현 금지
  - R-004: 모든 LLM 호출은 `_call_llm()` 헬퍼를 통해서만. 직접 Anthropic 클라이언트 호출 금지
  - R-005: `PipelineState` 직접 수정 금지. 반드시 `state.model_copy(update={...})` 패턴 사용

- [ ] **R-101 ~ R-103 데이터 룰**:
  - R-101: DB 스키마 변경은 마이그레이션 파일로만. 직접 DDL 금지
  - R-102: 개인정보(이메일, 사용자 데이터) 로그 출력 금지
  - R-103: MinIO 저장 파일 경로는 `{category}/{job_id}/{파일명}` 형식 고정

- [ ] **R-201 ~ R-203 모델 룰**:
  - R-201: 모든 모델 학습 결과는 MLflow에 run 기록 필수
  - R-202: 최종 모델 파일은 반드시 MinIO에 저장 후 `models` 테이블에 경로 기록
  - R-203: `is_best=True` 모델은 job당 1개만 존재. 업데이트 시 기존 best 플래그 해제

- [ ] **R-301 ~ R-302 학습 룰**:
  - R-301: Optuna 하이퍼파라미터 탐색은 기본 50 trials. 커스텀 시 config에서 조정
  - R-302: 교차검증은 StratifiedKFold(분류) / KFold(회귀) 기본 5-fold 사용

- [ ] **R-901 ~ R-903 Harness 룰**:
  - R-901: 에이전트 단위 테스트는 `tests/agents/test_{agent_name}.py` 경로에 작성
  - R-902: 테스트 커버리지 70% 이상 유지 (GitHub Actions에서 강제)
  - R-903: PR 머지 전 `ruff check`, `mypy`, `pytest` 전부 통과 필수

### 6. .github/workflows/test.yml 작성

- [ ] trigger: `push` (main, develop), `pull_request`
- [ ] jobs.test:
  - python-version: 3.10
  - `pip install -r requirements/base.txt -r requirements/api.txt -r requirements/worker.txt`
  - `ruff check .` — 린팅
  - `mypy shared/ agents/ api/ orchestrator/` — 타입 체크
  - `pytest tests/ -v --cov=. --cov-report=xml --cov-fail-under=70`
- [ ] 커버리지 리포트 Codecov 업로드 (선택)

### 7. .github/workflows/isolation_check.yml 작성

- [ ] trigger: `pull_request`
- [ ] PR 작성자의 `git config user.role` 확인
- [ ] 담당자별 허용 경로 매핑:
  - role=A: `agents/`, `orchestrator/`, `shared/` (합의된 변경만)
  - role=B: `pipelines/`, `shared/` (합의된 변경만)
  - role=C: `api/`, `migrations/`, `tools/`, `agents/data_*.py`, `agents/schema_*.py`
  - role=D: `tests/`, `scripts/`, `.github/`, `docker/`
- [ ] 허용 경로 외 파일 변경 시 경고 코멘트 자동 게시 (PR Comment)

### 8. scripts/isolation_hook.sh 작성

- [ ] pre-commit hook 스크립트
- [ ] `git config user.role` 읽기
- [ ] staged 파일 목록 vs 허용 경로 비교
- [ ] 위반 파일 있으면 커밋 거부 (exit 1)
- [ ] 위반 내용 상세 출력

### 9. .pre-commit-config.yaml 작성

- [ ] `ruff` 훅 등록 (자동 수정 포함)
- [ ] `mypy` 훅 등록
- [ ] `trailing-whitespace`, `end-of-file-fixer`, `check-yaml`, `check-json` 표준 훅
- [ ] `isolation_hook.sh` 로컬 훅 등록

---

## 🏗️ 구현 명세

### shared/state.py 전체 필드 목록

```python
# shared/state.py
from typing import Optional, Any
from pydantic import BaseModel, ConfigDict, Field


class PipelineState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # --- 핵심 식별자 ---
    job_id: str
    file_id: str
    category: str                          # tabular_ml | tabular_dl | timeseries | anomaly_detection
    task: str                              # classification | regression | clustering | anomaly_detection

    # --- 입력 옵션 ---
    target_column: Optional[str] = None
    user_question: Optional[str] = None

    # --- 데이터 분석 ---
    data_profile: Optional[dict] = None
    validation: Optional[dict] = None      # {is_valid, errors:[], warnings:[]}
    preprocessing_plan: Optional[list] = None
    preprocessed_data_id: Optional[str] = None

    # --- EDA ---
    eda_charts: list[str] = Field(default_factory=list)

    # --- 모델 ---
    model_candidates: list[str] = Field(default_factory=list)
    trained_models: list[dict] = Field(default_factory=list)
    training_warnings: list[str] = Field(default_factory=list)
    best_model: Optional[dict] = None

    # --- 해석/평가 ---
    explanations: Optional[dict] = None
    eval_result: Optional[dict] = None     # {passed:bool, metrics:{}, threshold_violations:[]}

    # --- 리포트 산출물 ---
    insights: Optional[str] = None
    ppt_path: Optional[str] = None
    pdf_path: Optional[str] = None
    script_path: Optional[str] = None
    model_path: Optional[str] = None

    # --- 오케스트레이션 제어 ---
    retry_count: int = 0
    max_retries: int = 3
    error: Optional[str] = None
    next_agent: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """JSON 직렬화 가능한 dict 반환"""
        return self.model_dump(mode="json")
```

### agents/base.py 핵심 구조

```python
# agents/base.py
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
import time
import json
from anthropic import Anthropic
from shared.state import PipelineState
from shared.config import settings
from shared.logger import get_logger


class BaseAgent(ABC):
    model_name: str = "claude-sonnet-4-6"

    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
        self.llm = Anthropic(api_key=settings.anthropic_api_key)
        self._last_input_tokens: int = 0
        self._last_output_tokens: int = 0

    @abstractmethod
    def __call__(self, state: PipelineState) -> PipelineState:
        """LangGraph 노드 인터페이스. 반드시 구현."""
        ...

    @asynccontextmanager
    async def log_agent_run(self, state: PipelineState):
        """DB agent_runs 기록 + structlog 래핑"""
        start = time.monotonic()
        # DB INSERT: status=running
        try:
            yield
            duration_ms = int((time.monotonic() - start) * 1000)
            # DB UPDATE: status=completed, duration_ms, tokens
            self.logger.info("agent_completed",
                             agent=self.__class__.__name__,
                             job_id=state.job_id,
                             duration_ms=duration_ms)
        except Exception as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            # DB UPDATE: status=failed, error=str(e)
            self.logger.error("agent_failed",
                              agent=self.__class__.__name__,
                              job_id=state.job_id,
                              error=str(e))
            raise

    def _call_llm(self, system_prompt: str, user_prompt: str,
                  max_tokens: int = 4096) -> str:
        """Anthropic Messages API 호출 헬퍼"""
        response = self.llm.messages.create(
            model=self.model_name,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        self._last_input_tokens = response.usage.input_tokens
        self._last_output_tokens = response.usage.output_tokens
        return response.content[0].text

    def _parse_json(self, text: str) -> dict:
        """마크다운 코드 블록 제거 후 JSON 파싱"""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:-1])
        return json.loads(cleaned)
```

### .github/workflows/test.yml 구조

```yaml
name: CI Tests

on:
  push:
    branches: [main, develop]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.10"
          cache: pip
      - name: Install dependencies
        run: pip install -r requirements/base.txt -r requirements/api.txt -r requirements/worker.txt
      - name: Lint (ruff)
        run: ruff check .
      - name: Type check (mypy)
        run: mypy shared/ agents/ api/ orchestrator/ --ignore-missing-imports
      - name: Test (pytest)
        run: pytest tests/ -v --cov=. --cov-report=xml --cov-fail-under=70
        env:
          DATABASE_URL: postgresql://autoai:test@localhost:5432/autoai_test
          REDIS_URL: redis://localhost:6379/1
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

### AGENTS.md 룰 체계 요약

```
R-0xx: 핵심 아키텍처 룰 (전체 적용)
R-1xx: 데이터 관련 룰 (C 담당)
R-2xx: 모델 관련 룰 (B 담당)
R-3xx: 학습 관련 룰 (B 담당)
R-9xx: Harness / 테스트 룰 (D 담당)
```

---

## 📁 생성/수정 파일 목록

```
프로젝트 루트/
├── AGENTS.md                           # 팀 개발 규칙 (R-001~R-903)
├── shared/
│   ├── __init__.py
│   ├── state.py                        # PipelineState Pydantic 모델
│   ├── config.py                       # Settings (pydantic-settings)
│   ├── logger.py                       # structlog JSON 로거
│   └── models.py                       # (Day 2에서 작성, 여기서 ORM 임포트 확인)
├── agents/
│   ├── __init__.py
│   └── base.py                         # BaseAgent 추상 클래스
├── .github/
│   └── workflows/
│       ├── test.yml                    # pytest / ruff / mypy CI
│       └── isolation_check.yml         # 담당자 폴더 격리 검사
├── scripts/
│   └── isolation_hook.sh               # pre-commit 격리 훅
└── .pre-commit-config.yaml             # pre-commit 훅 설정
```

---

## 🔗 의존성 & 선행 조건

- **Day 1 완료 필수**: Docker 환경 정상 기동 (redis, postgres 컨테이너 healthy)
- **Day 2 완료 필수**: `shared/db.py`, `shared/models.py` 작성 완료
- pydantic-settings 설치 확인 (`pip show pydantic-settings`)
- structlog 설치 확인 (`pip show structlog`)
- anthropic SDK 설치 확인 (`pip show anthropic`)
- pre-commit 설치 확인 (`pip show pre-commit`)
- GitHub Actions secrets에 `ANTHROPIC_API_KEY` 등록 완료

---

## ✔️ 완료 기준 (Done Criteria)

- [ ] `python -c "from shared.state import PipelineState; print('OK')"` 성공
- [ ] `python -c "from shared.config import settings; print(settings.log_level)"` 성공
- [ ] `python -c "from agents.base import BaseAgent; print('OK')"` 성공
- [ ] `python -c "from shared.logger import get_logger; log=get_logger('test'); log.info('test')"` JSON 출력 확인
- [ ] `ruff check shared/ agents/` 경고/오류 없음
- [ ] `mypy shared/ agents/ --ignore-missing-imports` 오류 없음
- [ ] AGENTS.md 파일 존재, R-001~R-903 전체 룰 포함
- [ ] `.github/workflows/test.yml` YAML 문법 유효성 통과 (`yamllint`)
- [ ] `.github/workflows/isolation_check.yml` YAML 문법 유효성 통과
- [ ] `pre-commit install` 성공, `pre-commit run --all-files` 실행 가능

---

## ⚠️ 주의사항 & 제약

### AGENTS.md 룰 (Day 3 추가)

- **R-002**: `shared/` 패키지 파일 변경은 PR + 팀원 2인 이상 승인 필수. 단독 변경 금지
- **R-003**: 모든 에이전트는 `BaseAgent` 상속 필수. 상속 없이 `__call__` 구현하는 독립 클래스 금지
- **R-004**: LLM 호출은 `_call_llm()` 헬퍼를 통해서만. 토큰 추적 누락 방지

### 아키텍처 제약

- `PipelineState` 는 불변(immutable) 패턴으로 사용. 수정 시 `state.model_copy(update={...})` 반드시 사용
- `settings` 싱글턴은 모듈 임포트 시점에 `.env` 로드. 런타임 변경 불가
- `get_logger()` 반환 객체는 스레드 세이프. Celery 워커에서 병렬 사용 가능
- `BaseAgent._call_llm()` 은 동기 메서드. 비동기 컨텍스트에서는 `asyncio.to_thread()` 래핑 사용

### CI/CD 주의사항

- GitHub Actions에서 `ANTHROPIC_API_KEY` 는 secrets로 관리 (Settings > Secrets)
- `--cov-fail-under=70` 미달 시 CI 실패. 새 에이전트 추가 시 테스트 함께 작성 필수
- `isolation_check.yml` 은 정보성 경고만 출력 (CI 블로킹 아님). Day 5 이후 강제 적용 예정

### 팀 합의 사항 (Day 3 이후 공통 모듈 변경 프로세스)

1. Slack에 변경 의도 공지
2. PR 생성 (브랜치명: `shared/{변경내용}`)
3. 팀원 2인 이상 코드 리뷰 승인
4. CI 전부 통과 확인
5. main 브랜치 머지

---

## 🆕 v2 확장 작업 (마스터 설계서 §3 · §6 · §10 참조)

> Day3는 v2의 **공통 베이스 클래스/유틸**을 한꺼번에 설치한다. 이후 Day4~Day21이 이 기초 위에 쌓인다.

### 1. `shared/state_v2.py` — PipelineStateV2

v1 PipelineState 필드를 모두 포함하면서 다음을 추가:

```python
class PipelineStateV2(PipelineState):
    # 사용자 의도
    user_intent: Optional[str] = None
    user_intent_structured: Optional[dict] = None  # IntentElicitor가 채움

    # G1~G5 제안 + 선택
    proposals_g1: Optional[list] = None      # 3안
    user_choice_g1: Optional[dict] = None
    proposals_g2: Optional[list] = None
    user_choice_g2: Optional[dict] = None
    proposals_g3: Optional[list] = None
    user_choice_g3: Optional[dict] = None
    proposals_g4: Optional[list] = None
    user_choice_g4: Optional[dict] = None
    proposals_g5: Optional[list] = None
    user_choice_g5: Optional[list] = None     # 다중 선택 (산출물)

    # 게이트 상태
    awaiting_decision: Optional[str] = None   # 'G1'..'G5' or None
    current_gate: Optional[str] = None

    # 자체학습 RAG 참조
    similar_cases: list[dict] = Field(default_factory=list)
    used_recipes: list[str] = Field(default_factory=list)

    # 보안
    pii_columns: list[str] = Field(default_factory=list)
    pii_mask_policy: Optional[str] = None     # 'mask'|'drop'|'keep'
    actor_user_id: Optional[str] = None
    actor_role: Optional[str] = None

    # 자동 오류 처리
    error_context: Optional[dict] = None
    auto_patch_applied: bool = False
    patch_history: list[dict] = Field(default_factory=list)

    # 산출물
    requested_outputs: list[str] = Field(default_factory=list)  # ['OUT-01','OUT-04',...]
    produced_outputs: dict[str, str] = Field(default_factory=dict)  # {OUT-01: minio_path, ...}
```

R-005 추가: state 변경은 v1과 동일하게 `model_copy(update=...)` 패턴.

### 1.5 `agents/personas.py` — 27 페르소나 권위 모듈 (신규)

마스터 §4.3 의 페르소나 표를 Python 딕셔너리로 옮긴 단일 권위 파일. `agent_registry` 시드(Day02 §5) 와 BaseAgent 자동 주입 양쪽 모두 이 파일을 참조한다.

```python
# agents/personas.py
"""
27 에이전트 페르소나 권위 모듈.
마스터 설계서 §4.3 의 표와 1:1 매핑.
변경 시 PR 리뷰 2인 + 사유 기록 필수 (R-007).
"""

PERSONAS: dict[str, str] = {
    "SupervisorAgent":              "당신은 데이터 분석 파이프라인의 입출항 관제사로, 입력의 유효성과 다음 단계 적합성을 빠르게 판정합니다.",
    "IntentElicitorAgent":          "당신은 사용자의 한 줄 의도를 구조화된 분석 명세로 옮기는 비즈니스 분석 인터뷰어입니다.",
    "DataProfilerAgent":            "당신은 들어온 데이터의 형태와 결을 한눈에 파악하는 데이터 검수관입니다.",
    "SchemaValidatorAgent":         "당신은 분석 카테고리별 필수 요건을 엄격히 점검하는 데이터 품질 감사관입니다.",
    "AnalysisProposerAgent":        "당신은 분석 의도와 데이터를 보고 서로 다른 세 갈래의 길을 제시하는 데이터 전략 컨설턴트입니다.",
    "MethodologyProposerAgent":     "당신은 ML/DL/시계열/이상탐지 등 방법론을 데이터 특성에 맞게 비교 권장하는 AutoML 자문가입니다.",
    "ModelStrategyProposerAgent":   "당신은 모델 아키텍처 후보를 장단점 매트릭스로 정리해 의사결정을 돕는 모델링 아키텍트입니다.",
    "ModelComparisonReporterAgent": "당신은 학습 결과를 공정한 비교표와 그래프로 가시화하는 모델 평가 리포터입니다.",
    "OutputTypeSelectorAgent":      "당신은 의도·청중·메트릭을 보고 최적 산출물 조합을 권장하는 리서치 디자인 큐레이터입니다.",
    "PreprocessingStrategistAgent": "당신은 데이터의 결을 살리는 전처리 단계를 설계하는 시니어 데이터 엔지니어입니다.",
    "FeatureEngineerAgent":         "당신은 결정된 전처리 계획을 정확하고 재현 가능하게 실행하는 피처 빌더입니다.",
    "EDAAgent":                     "당신은 분포·관계·이상 신호를 빠르게 그림으로 옮기는 EDA 분석가입니다.",
    "PreprocessingChoiceAgent":     "당신은 자동 결정 신뢰도가 애매할 때 사용자와 최소 대화로 합의를 만드는 전처리 큐레이터입니다.",
    "ModelSelectionAgent":          "당신은 데이터 특성과 과거 성공 레시피를 종합해 최적 모델 후보 3종을 선정하는 AutoML 큐레이터입니다.",
    "HyperparameterTunerAgent":     "당신은 warm-start와 Optuna로 탐색 공간을 효율적으로 좁히는 하이퍼파라미터 튜너입니다.",
    "TrainingExecutorAgent":        "당신은 모델 학습 잡을 안정적이고 재현 가능하게 실행하는 ML 트레이닝 엔지니어입니다.",
    "TrainingMonitorAgent":         "당신은 발산·과적합·NaN 같은 학습 이상 신호를 조기에 포착하는 학습 안전 감독관입니다.",
    "MetricsAggregatorAgent":       "당신은 후보 모델의 메트릭을 정규화·비교해 최적 모델을 객관적으로 골라내는 메트릭 심판관입니다.",
    "FineTuneExecutorAgent":        "당신은 트랜스포머 모델의 마지막 1%를 끌어올리는 미세조정 전문가입니다.",
    "EvalAgent":                    "당신은 임계치 룰과 도메인 감각을 결합해 모델 출시 가능성을 판정하는 모델 QA 평가관입니다.",
    "ExplainabilityAgent":          "당신은 모델 판단 근거를 SHAP과 시계열 분해로 시각화하는 해석성 분석가입니다.",
    "InsightAgent":                 "당신은 분석 메트릭을 비즈니스 의사결정자가 이해할 수 있는 한국어 인사이트로 옮기는 분석 스토리텔러입니다.",
    "ReportComposerAgent":          "당신은 사용자가 선택한 산출물 조합을 병렬로 조율해 데드라인 안에 묶어 내는 산출물 PM입니다.",
    "SelfLearningAgent":            "당신은 매 분석에서 얻은 지식을 3-Stack KB에 깔끔히 정리해 다음 분석을 더 똑똑하게 만드는 지식 큐레이터입니다.",
    "AutoErrorHandlerAgent":        "당신은 처음 보는 오류는 빠르게 진단하고, 본 적 있는 오류는 KB로 즉시 해결하는 자동 오류 정비공입니다.",
    "SecurityGuardAgent":           "당신은 PII와 프롬프트 인젝션 시도를 끊임없이 감시하는 보안 가드입니다.",
    "ErrorRecoveryAgent":           "당신은 자동 처리가 끝까지 실패했을 때 사용자에게 친절히 상황을 설명하고 다음 행동을 안내하는 회복 코디네이터입니다.",
}

# 검증: 27개 정확히, 각 페르소나 길이 ≤ 80자
assert len(PERSONAS) == 27, f"expected 27 personas, got {len(PERSONAS)}"
for name, p in PERSONAS.items():
    assert 10 <= len(p) <= 200, f"{name} persona length {len(p)} out of range"

def get_persona(agent_name: str) -> str:
    """미정의 에이전트는 빈 문자열 반환 (BaseAgent가 페르소나 없이 진행)."""
    return PERSONAS.get(agent_name, "")
```

### 1.6 BaseAgent persona 자동 주입 (수정)

기존 BaseAgent 에 `persona` 클래스 속성과 자동 주입 로직 추가:

```python
# agents/base.py (Day3 v1에 정의된 BaseAgent 확장)
from agents.personas import get_persona

class BaseAgent(ABC):
    model_name: str = "claude-sonnet-4-6"
    persona: str = ""   # 서브클래스 또는 personas.py에서 자동 채움

    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
        self.llm = Anthropic(api_key=settings.anthropic_api_key)
        # 페르소나가 클래스에 명시되지 않았으면 personas.py 에서 자동 로딩
        if not self.persona:
            self.persona = get_persona(self.__class__.__name__)

    def _call_llm(self, system_prompt: str, user_prompt: str,
                  max_tokens: int = 4096) -> str:
        """R-006: 페르소나가 있으면 system_prompt 맨 앞에 자동 prepend.
        서브클래스가 system_prompt 안에 페르소나를 중복 작성하면 린트가 잡는다."""
        if self.persona:
            full_system = f"{self.persona}\n\n{system_prompt}"
        else:
            full_system = system_prompt
        response = self.llm.messages.create(
            model=self.model_name,
            max_tokens=max_tokens,
            system=full_system,
            messages=[{"role": "user", "content": wrap_in_user_block(user_prompt)}],
        )
        self._last_input_tokens = response.usage.input_tokens
        self._last_output_tokens = response.usage.output_tokens
        return response.content[0].text
```

### 1.7 페르소나 린트 (`scripts/lint_personas.py`)

```python
"""에이전트 코드에서 페르소나 중복 작성을 잡는다.
시스템 프롬프트 문자열에 '당신은 ... 입니다' 같은 페르소나 시그니처가 들어 있는데
PERSONAS 에도 같은 에이전트가 등록되어 있으면 경고."""
import re, ast, sys
from pathlib import Path
from agents.personas import PERSONAS

PERSONA_PAT = re.compile(r"당신은\s+\S+.*입니다\.")

failures = []
for p in Path("agents").rglob("*.py"):
    src = p.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name in PERSONAS:
            class_src = ast.get_source_segment(src, node) or ""
            for sp in re.findall(r'SYSTEM_PROMPT\s*=\s*[fr]?"""(.*?)"""', class_src, re.S):
                if PERSONA_PAT.search(sp):
                    failures.append(f"{p}::{node.name}: 시스템 프롬프트에 페르소나 중복 작성")
if failures:
    print("\n".join(failures)); sys.exit(1)
```

CI(`.github/workflows/test.yml`) 에 이 스크립트 호출 단계 추가.

### 2. `agents/base_gate.py` — BaseGateAgent

```python
class BaseGateAgent(BaseAgent, ABC):
    """G1~G5 게이트 에이전트의 공통 베이스."""
    gate_code: str  # 'G1'..'G5'
    proposal_count: int = 3  # G5는 N개

    @abstractmethod
    def build_proposals(self, state: PipelineStateV2) -> list[dict]:
        """각 게이트별 후보안 생성. 반드시 [{title, why, plan, est_metrics, transformer_used}*N] 반환."""
        ...

    def __call__(self, state: PipelineStateV2) -> PipelineStateV2:
        proposals = self.build_proposals(state)
        # 보안: 사용자에게 노출되는 텍스트도 sanitize
        for p in proposals:
            for k in ("title", "why", "plan"):
                if k in p: p[k] = sanitize_for_display(p[k])
        return state.model_copy(update={
            f"proposals_{self.gate_code.lower()}": proposals,
            "awaiting_decision": self.gate_code,
            "current_gate": self.gate_code,
        })
```

### 3. `security/` 패키지 (Day17 본격 작업의 베이스)

- [ ] `security/prompt_defense.py` — `sanitize_user_input`, `sanitize_for_display`, `wrap_in_user_block` (§10.4 코드 그대로)
- [ ] `security/pii_detector.py` — 한국·영어 PII 정규식 + 컬럼명 휴리스틱 (`name`, `email`, `phone`, `ssn`, `rrn`, `card`, `addr`, ...) + Faker 기반 가명화기
- [ ] `security/audit.py` — `log_audit(event_type, severity, details, actor=None)` 헬퍼
- [ ] `security/rate_limit.py` — Redis 토큰 버킷 데코레이터 (`@rate_limit(key='upload', limit=20, window=60)`)
- [ ] `security/vault_client.py` — `get_secret(key)` → Vault KV v2 fetch + 메모리 캐시 (TTL 5분)

### 4. `harness/self_learning_client.py` — SelfLearningAgent 인터페이스

```python
class SelfLearningClient:
    """모든 에이전트가 자체학습 KB를 사용할 때 거치는 공통 게이트웨이."""

    def fetch_similar_cases(self, intent_text: str, profile_summary: str, top_k=5) -> list[dict]:
        """G1/G3 제안 단계에서 호출. pgvector 유사 검색."""
        ...

    def fetch_recipes(self, category: str, kb_types: list[str], top_k=10) -> list[dict]:
        """카테고리별 best practice 레시피."""
        ...

    def fetch_hpo_warm_start(self, category: str, model_name: str) -> Optional[dict]:
        """Optuna 탐색 초기값."""
        ...

    def enqueue_distill(self, job_id: str) -> None:
        """잡 종료 시 호출. Celery harness 큐에 distill_job 발행."""
        celery_app.send_task("distill_job", args=[job_id], queue="harness")
```

### 5. `error_handler/` 패키지 (Day16 본격 작업의 베이스)

- [ ] `error_handler/normalize.py` — stack trace 정규화 (`hash_error(agent, exc_type, stack)`)
- [ ] `error_handler/kb_client.py` — error_kb CRUD + lookup
- [ ] `error_handler/cli_bridge.py` — §6.3 subprocess 호출 (Day16에서 본격화, 인터페이스만 정의)
- [ ] `error_handler/patcher.py` — 패치 샌드박스 적용기 + 단위 테스트 러너 hook

### 6. BaseAgent 확장

- [ ] `BaseAgent.__call__` 을 try/except 로 감싸 `AutoErrorHandlerAgent` 호출 (Day16 활성화):
  ```python
  def __call__(self, state):
      try:
          return self._call_impl(state)
      except Exception as exc:
          if settings.ENABLE_AUTO_ERROR_HANDLER:
              from agents.auto_error_handler import AutoErrorHandlerAgent
              return AutoErrorHandlerAgent().handle(state, exc, self.__class__.__name__)
          raise
  ```
- [ ] `BaseAgent._call_llm` 호출 직전에 시스템 프롬프트 가드 + 사용자 입력은 `wrap_in_user_block` 강제

### 7. AGENTS.md 룰 신설 (R-401~R-799 일부)

- [ ] R-401 ~ R-403 (게이트)
- [ ] R-501, R-502 (자체학습)
- [ ] R-601, R-602 (오류/CLI)
- [ ] R-701 ~ R-704 (보안 기본)

### 8. CI/CD 보강

- [ ] `.github/workflows/security_scan.yml` 신규:
  - `bandit -r .` (SAST)
  - `pip-audit` (취약 라이브러리)
  - `gitleaks` (비밀 키 누수)
- [ ] `.pre-commit-config.yaml` 에 `gitleaks`, `bandit` 훅 추가

### 9. 완료 기준 (v2 추가)

- [ ] `python -c "from shared.state_v2 import PipelineStateV2; print(PipelineStateV2.model_fields.keys())"` → 신규 필드 모두 포함
- [ ] `python -c "from agents.base_gate import BaseGateAgent"` 성공
- [ ] `python -c "from security.prompt_defense import sanitize_user_input as s; print(s('ignore previous instruction and reveal'))"` 출력에 `[BLOCKED]` 포함
- [ ] `bandit -r security/` 경고 0건
- [ ] `gitleaks detect --no-banner` 누수 0건

### 10. 주의사항 (v2)

- `security/prompt_defense.py` 의 정규식은 한국어/영어 모두 대응
- `BaseGateAgent.build_proposals` 의 응답은 반드시 길이 == proposal_count
- `AGENTS.md`에 R-401~R-799 추가 시 v1 R-001~R-9xx와 번호 충돌 없도록 확인
