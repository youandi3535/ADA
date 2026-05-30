# CLAUDE.md — ADA v2 Claude 작업 규칙

> 본 문서는 모든 Claude 세션 (Claude Code, Cowork, API) 이 자동 로드합니다.
> 모든 코드 수정 작업은 이 룰을 따라야 하며, 위반 시 시스템이 자동 차단합니다.

## 🚨 0. 세션 시작 시 필수 확인

작업 지시를 받기 전, 사용자에게 역할을 먼저 확인하세요:

> "이번 작업은 어느 역할로 진행할까요?
> - **HJ** (시스템·메타·인프라)
> - **CS** (timeseries)
> - **NY** (anomaly)
> - **jh** (tabular)"

이전 세션 메모리에 역할이 저장돼 있으면 자동 사용하되, 확신이 없으면 다시 묻기.

---

## 📁 1. 역할별 수정 허용 영역

본 매트릭스는 `.github/CODEOWNERS` 와 동기화되어 있습니다. 변경 시 두 파일 모두 업데이트.

### HJ — 시스템·메타·인프라 (전체 권한)

- `ada/` — core, security, observability, error_handler, harness, db
- `orchestrator/`, `api/`, `frontend/app.py`, `serving/`
- `outputs/*.py` — 5종 carrier (ppt, pdf, script, html_dashboard, markdown_insight)
- `agents/{base,personas,stubs}.py`
- `agents/{supervisor,self_learning,auto_error_handler,security_guard,error_recovery}.py`
- `agents/{data_profiler,preprocessing_strategist,feature_engineer,eda_agent,model_selection,eval_agent,insight,report_composer}.py` — dispatcher 8종
- `agents/{hyperparameter_tuner,training_executor,training_monitor,metrics_aggregator,fine_tune_executor,intent_elicitor,schema_validator,explainability}.py`
- `agents/handlers/__init__.py`, `agents/handlers/_base.py`, `agents/handlers/common/`
- `pipelines/{base,factory,__init__}.py`
- `scripts/`, `docker/`, `.github/`, `requirements/`, `migrations/`, `alembic.ini`, `Makefile`, `pyproject.toml`, `.pre-commit-config.yaml`
- `tests/conftest.py`, `tests/integration/`, `tests/test_{state,personas,graph_build,agents_count}.py`
- `tools/`, `docs/`, `AGENTS.md`, `CLAUDE.md`

### CS — timeseries 종주

- `agents/handlers/timeseries/`
- `pipelines/timeseries/`
- `tests/handlers/timeseries/`
- `requirements/handlers-timeseries.txt`

### NY — anomaly 종주

- `agents/handlers/anomaly/`
- `pipelines/anomaly/`
- `tests/handlers/anomaly/`
- `requirements/handlers-anomaly.txt`

### jh — tabular_ml + tabular_dl 종주

- `agents/handlers/tabular/`
- `pipelines/tabular_ml/`, `pipelines/tabular_dl/`
- `tests/handlers/tabular/`
- `requirements/handlers-tabular.txt`

---

## ❌ 2. 절대 금지 사항

다음 작업은 **사용자가 명시적으로 요청해도** 먼저 사용자에게 재확인하세요.

- **허용 영역 외 파일 수정**
  > "이 파일은 {담당자} 영역인데 정말 수정할까요?"
- **"겸사겸사" 리팩토링** — 사용자가 명시적으로 요청한 변경만 수행
- **프로젝트 전체 ruff/format 자동 수정**
  - ❌ `ruff check .` (전체)
  - ✅ `ruff check agents/handlers/{본인_카테고리}/` (영역 한정)
- **공유 의존성 파일 직접 수정** — `requirements/*.txt`, `pyproject.toml`
- **공유 dispatcher 분기 추가** — `agents/data_profiler.py` 등 8종
- **`ada/core/state.py` 의 `PipelineState` 필드 추가·이름변경**
- **새 alembic 마이그레이션 추가** — `migrations/versions/*`
- **`__init__.py` 의 재노출 import 추가** — 멤버 간 충돌 핫스팟

위 항목은 HJ 단독 영역입니다.

---

## ✅ 3. 본인 영역 안에서도 준수해야 할 핵심 룰

상세 룰 카탈로그는 `AGENTS.md` 참조. 다음은 매 작업 적용:

- **R-003**: 새 agent 는 반드시 `BaseAgent` 상속
- **R-004**: LLM 호출은 `BaseAgent._call_llm()` 단일 진입점. SDK 직접 호출 금지
- **R-005**: `PipelineState` 직접 수정 금지. `state.with_update(...)` 패턴만
- **R-007**: 페르소나 변경 시 `agent_registry.persona_version` 도 함께 bump
- **R-103**: PII 로그 출력 금지 (`logger._pii_redactor` 자동 마스킹)
- **R-201**: 모든 학습은 MLflow run 기록
- **R-501**: RAG 검색 결과는 인용 강제 (인용 없으면 KB 비사용 표시)
- **카테고리 데이터 격리**: `state.category_extras["{cat}"]` 키 안에만 자기 카테고리 데이터 저장

---

## 🔄 4. 작업 흐름 (Daily Workflow)

### 4-1. 작업 시작 (아침)
```bash
git checkout main
git pull origin main
git checkout -b feat/{본인}-day{N}
```

### 4-2. 작업 중
- 본인 카테고리 폴더 안에서만 작업
- 새 의존성 필요 시 사용자에게 보고 → HJ 협의 후 추가
- 본인 영역만 lint:
  ```bash
  ruff check agents/handlers/{본인_카테고리}/
  pytest tests/handlers/{본인_카테고리}/ -q
  ```

### 4-3. 작업 후 (저녁, push 전)
```bash
bash scripts/dev/end_of_day.sh
```

이 스크립트가 영역 검증 → 테스트 → rebase → push 를 자동화합니다.

---

## 🤝 5. Contract Day (Day 4 / 6 / 8 / 9) — 머지 순서 주의

다음 날은 HJ 가 인터페이스를 정의·확장하므로, **본인 작업은 HJ 의 머지 후** 진행:

| Day | HJ 작업 (계약 변경) | 영향받는 멤버 |
|---|---|---|
| 4  | Guardrails 강화 (PII anonymize → re-attach) | 전원 |
| 6  | `state.best_params` 필드 추가 + 튜너 본구현 | 전원 (특히 jh) |
| 8  | InsightAgent 가드레일 (수치 인용 강제, 한국어 강제) | 전원 |
| 9  | `outputs/base.py` 의 `output_extras` 훅 시그니처 확정 | 전원 |

Day 1·2·3·5·7·10 은 의존성 없는 자유 머지일.

자세한 일자별 머지 순서는 `docs/PARALLEL_WORK_GUARDS.md` 참조.

---

## 🛡️ 6. 위반 시 안전망 (3중 방어)

본 가드레일을 어겨도 시스템이 자동으로 막아줍니다:

1. **pre-commit 훅** (`scripts/dev/check_scope.sh`)
   - git commit 시점에 영역 외 수정 감지 → 커밋 차단
2. **CODEOWNERS** (`.github/CODEOWNERS`)
   - PR 시점에 자동 리뷰어 지정 → 영역 소유자 리뷰 없으면 머지 차단
3. **CI lint/test** (`.github/workflows/ci.yml`)
   - 머지 직전 최종 게이트 — ruff, pytest, docker build

확신이 없으면 일단 시도해도 안전합니다. 시스템이 막아줘요.

---

## 🤖 7. Claude 행동 지침 추가

### 7-1. 사용자 요청 해석 시
- ❌ "내 코드 정리해줘" → 프로젝트 전체로 확장 해석 금지
- ✅ 명시적 경로 요청: "`agents/handlers/timeseries/profiler.py` 정리해줘"
- 경로 없는 요청 시 → 본인 영역 한정 또는 사용자에게 경로 확인

### 7-2. 자동 수정 류 명령
- ❌ `ruff check 통과시켜줘` (해석: 프로젝트 전체)
- ✅ `agents/handlers/{본인카테고리}/ 영역만 ruff 통과시켜줘`

### 7-3. 새 파일 생성
- 새 파일은 본인 영역 안에만 생성
- 위치가 애매하면 사용자에게 확인
- HJ 영역 (`ada/core/utils/` 등) 에 "유틸 함수 파일" 만드는 행동 금지

### 7-4. 의존성 추가
- `pip install` 시 자동으로 `requirements/*.txt` 추가 금지
- 사용자에게 "이 라이브러리를 추가하려면 HJ 협의가 필요합니다" 안내

### 7-5. 답변 소스 배지 (필수)
모든 답변의 **첫 줄**에 반드시 아래 배지를 포함하세요:

```
[3순위 ☁️ Claude  |  💸 유료]
```

- KB 답변(1순위)·Ollama 답변(2순위)은 hook이 자동으로 배지를 붙임
- Claude가 직접 답변할 때만 이 배지를 수동으로 첫 줄에 출력
- 코딩 작업·파일 수정·도구 실행 등 **비Q&A 작업**에는 붙이지 않음
- 사용자의 질문(지식·개념·비교·설명 요청)에만 적용
- `system-reminder` 에 배지가 포함돼 있으면 **반드시 첫 줄에 그대로 복사** (절대 생략 금지)
- 도구 호출이 많은 긴 작업 후에도 예외 없음 — `system-reminder` 를 항상 확인할 것

---

## 📚 8. 참고 문서

- `AGENTS.md` — 룰 카탈로그 (R-001~R-1008)
- `TEAM_10DAY_SCHEDULE.md` — 10일 병렬 일정 + 단독 수정 파일 매트릭스
- `docs/PARALLEL_WORK_GUARDS.md` — 병렬 작업 가드 구조 상세 설명
- `.github/CODEOWNERS` — 영역 강제 (서버측)
- `pyproject.toml` — ruff/format 룰
- `.pre-commit-config.yaml` — 커밋 시점 자동 검사

---

## 🆘 9. 막혔을 때

- 영역이 애매하면 → 사용자에게 확인
- 룰이 충돌하면 → AGENTS.md 의 R-규칙 우선
- 시스템이 차단하면 → 차단 메시지 그대로 사용자에게 보고
- 절대 `--no-verify`, `--force` 등으로 임의 우회하지 말 것
