# ADA v2 — 팀원 병렬 작업 환경 구축 요약

> **목적**: 4명 (HJ · CS · NY · jh) 이 10일간 동시 작업하면서 서로 충돌 없이, 다른 사람 영역을 침범할 수 없도록 시스템 가드를 구축한 결과 요약.
> **작업 일자**: 2026-05-22
> **작업자**: HJ

---

## 1. 팀 구성

| 멤버 | 담당 카테고리 | 단독 수정 폴더 |
|---|---|---|
| **HJ** | 시스템·메타·인프라 | `ada/`, `orchestrator/`, `api/`, `outputs/`, dispatcher 8종, `.github/`, `requirements/worker.txt` 등 |
| **CS** | Timeseries (시계열) | `agents/handlers/timeseries/`, `pipelines/timeseries/`, `tests/handlers/timeseries/`, `requirements/handlers-timeseries.txt` |
| **NY** | Anomaly (이상탐지) | `agents/handlers/anomaly/`, `pipelines/anomaly/`, `tests/handlers/anomaly/`, `requirements/handlers-anomaly.txt` |
| **jh** | Tabular (정형 ML/DL) | `agents/handlers/tabular/`, `pipelines/tabular_ml/`, `pipelines/tabular_dl/`, `tests/handlers/tabular/`, `requirements/handlers-tabular.txt` |

---

## 2. 핵심 설계 — Category Ownership + 4중 방어

```
┌─────────────────────────────────────────────────────────┐
│  Category Ownership 패턴                                  │
│  각자 자기 카테고리 폴더만 수정 (다른 폴더는 읽기만)             │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│  4중 방어 — 위반 시 자동 차단                                │
│  ① CLAUDE.md      → AI 가 다른 영역 건드리기 전 사용자 확인  │
│  ② pre-commit 훅  → git commit 시점에 차단 (로컬)          │
│  ③ CODEOWNERS     → PR 시점에 자동 리뷰어 지정 (서버)        │
│  ④ CI lint/test   → 머지 직전 최종 게이트                   │
└─────────────────────────────────────────────────────────┘
```

---

## 3. 신규 / 수정한 파일 (총 17종)

### 🆕 신규 파일 8종

| 파일 | 역할 |
|---|---|
| `pyproject.toml` | ruff 룰 통일 (Python 3.10, line-length 120, isort) — 4명 PC 의 도구 일관성 |
| `.pre-commit-config.yaml` | 커밋 시 자동 검사 (ruff fix + 영역 검증 + 위생 훅) |
| `scripts/dev/check_scope.sh` | git email 기반 작성자 식별 → 영역 외 수정 자동 차단 |
| `scripts/dev/end_of_day.sh` | 하루 끝 자동화 (영역검증 → 테스트 → rebase → push) |
| `CLAUDE.md` | Claude Code/Cowork 가 매 세션 자동 로드하는 AI 가드레일 |
| `.github/PULL_REQUEST_TEMPLATE.md` | PR 자가검증 체크박스 + Contract Day 확인 |
| `.github/CODEOWNERS_TEAM_MAPPING.md` | GitHub username 매핑 절차 |
| `docs/PARALLEL_WORK_GUARDS.md` | 본 가드 구조 상세 가이드 |

### ✏️ 수정한 파일 + 신규 카테고리 의존성

| 파일 | 변경 내용 |
|---|---|
| `.github/CODEOWNERS` | `@cs`, `@ny`, `@jh` 핸들로 영역 매핑 |
| `outputs/base.py` | Day 9 카테고리 훅 `OutputExtrasHandler` Protocol 사전 선언 |
| `requirements/worker.txt` | 카테고리 deps 분리 후 슬림화 (105→87줄) |
| `requirements/handlers-timeseries.txt` | 🆕 CS 단독 (statsmodels, prophet) |
| `requirements/handlers-anomaly.txt` | 🆕 NY 단독 (pyod 등 슬롯) |
| `requirements/handlers-tabular.txt` | 🆕 jh 단독 (xgboost, lightgbm, catboost) |
| `TEAM_10DAY_SCHEDULE.md`, `DAY0_REFACTOR_REPORT.md`, `README.md` 등 | 멤버 호칭 A/B/C → CS/NY/jh 일괄 반영 |
| `agents/handlers/{cat}/*.py` 27종 | docstring `(담당: A/B/C)` → `(담당: CS/NY/jh)` |

---

## 4. 일자별 머지 순서 정책

> **핵심 룰**: **팀원 (CS·NY·jh) 사이 순서는 어떤 날이든 항상 자유**.
> HJ 만 날짜에 따라 머지 시점이 달라짐 — 그게 "종류" 컬럼의 의미.
>
> - 🟢 **자유**: HJ 도 순서 무관 (4명 다 자유)
> - 🟡 **권장**: HJ 먼저가 안전 (강제는 아님) → 그 후 팀원 자유
> - 🔴 **계약**: HJ 반드시 먼저 (인터페이스 정의) → 그 후 팀원 자유

| Day | HJ 머지 시점 | 팀원 (CS·NY·jh) | 종류 | 핵심 작업 |
|:---:|---|---|:---:|---|
| 0  | HJ 단독          | —                | 🔧 단독      | 골격 작업 |
| 1  | 자유             | 자유 (아무나 먼저) | 🟢 자유      | profiler |
| 2  | 자유             | 자유 (아무나 먼저) | 🟢 자유      | preprocessor |
| 3  | 자유             | 자유 (아무나 먼저) | 🟢 자유      | EDA |
| 4  | **먼저 권장**    | 자유 (아무나 먼저) | 🟡 권장      | Guardrails 강화 (HJ) / proposer (팀) |
| 5  | 자유             | 자유 (아무나 먼저) | 🟢 자유      | JWT (HJ) / selector (팀) |
| 6  | **반드시 먼저**  | 자유 (아무나 먼저) | 🔴 **계약**  | `state.best_params` 추가 + 튜너 본구현 |
| 7  | 자유             | 자유 (아무나 먼저) | 🟢 자유      | TrainingMonitor / evaluator |
| 8  | **반드시 먼저**  | 자유 (아무나 먼저) | 🔴 **계약**  | InsightAgent 가드레일 |
| 9  | **반드시 먼저**  | 자유 (아무나 먼저) | 🔴 **계약**  | `output_extras` 훅 시그니처 |
| 10 | 자유             | 자유 (아무나 먼저) | 🟢 자유      | KPI 위젯 / E2E 데모 |

### 자유일 (🟢) 운영 팁

- HJ 가 PR 먼저 머지 → 알림 받은 후 CS/NY/jh 는 본인이 준비된 순서대로 머지
- 4명이 동시에 PR 만들면 GitHub Merge Queue (활성화 시) 가 자동 직렬화
- 같은 파일을 4명이 동시에 수정하지 않으므로 어떤 순서든 충돌 0건

### 계약일 (🔴) 운영 규칙

- HJ 가 오전 중 인터페이스 변경 PR 머지 + 슬랙에 "contract published" 공지
- 팀원은 오후에 `git fetch origin && git rebase origin/main` 후 본인 작업 시작
- HJ 머지 전에 작업을 진행하면 인터페이스 미일치로 CI 실패 가능

---

## 5. 각 팀원 Daily Workflow

### 5-1. 아침 — 새 브랜치 만들기

```bash
git checkout main
git pull origin main
git checkout -b feat/{본인}-day{N}
# 예: HJ 의 Day 1 → git checkout -b feat/hj-day1
# 예: CS 의 Day 3 → git checkout -b feat/cs-day3
# 예: NY 의 Day 3 → git checkout -b feat/ny-day3
# 예: jh 의 Day 3 → git checkout -b feat/jh-day3
```

### 5-2. 낮 — 작업 + 자주 commit

작업하면서 본인 영역만 lint/test:

```bash
ruff check agents/handlers/{본인_카테고리}/
pytest tests/handlers/{본인_카테고리}/ -q

# 예: HJ 의 경우 — 본인 영역이 광범위해서 변경 폴더만 한정
ruff check ada/ orchestrator/ api/
pytest tests/ -q

# 예: CS 의 경우
ruff check agents/handlers/timeseries/
pytest tests/handlers/timeseries/ -q

# 예: NY 의 경우
ruff check agents/handlers/anomaly/
pytest tests/handlers/anomaly/ -q

# 예: jh 의 경우
ruff check agents/handlers/tabular/
pytest tests/handlers/tabular/ -q
```

작업 진행하면서 **commit 은 본인이 직접** (30분~1시간 단위로 자주):

```bash
git add .
git commit -m "feat: ADF 테스트 추가"
# 예: HJ — "feat: PipelineState.best_params 필드 추가"
# 예: CS — "feat: timeseries profiler ADF/KPSS 추가"
# 예: NY — "feat: anomaly contamination 추정 로직"
# 예: jh — "feat: tabular VIF + class balance"
```

> 💡 commit 시점에 `pre-commit 훅`이 자동 실행되어 영역 외 수정을 차단합니다.

### 5-3. 저녁 — 머지 준비 (push 만 자동)

```bash
bash scripts/dev/end_of_day.sh
```

이 스크립트가 자동으로 수행하는 일:
1. 영역 검증 (check_scope.sh)
2. 로컬 테스트 (pytest)
3. `git fetch origin`
4. `git rebase origin/main`
5. rebase 후 재테스트
6. `git push --force-with-lease`

**중요한 점**:
- ✅ **모든 팀원이 동일하게** `bash scripts/dev/end_of_day.sh` 한 줄만 실행하면 됨
- ❌ 단, **commit 은 스크립트가 해주지 않음** — 작업 중 본인이 `git add + git commit` 으로 변경을 미리 commit 해둬야 함
- 스크립트는 그 commit 들을 origin/main 위에 정리해서 push 만 자동화

### 5-4. PR 머지

1. GitHub 에서 PR 생성 (또는 자동 갱신됨)
2. CI 그린 확인 (lint-and-test / docker-build-check)
3. Code owner 리뷰 받기 (다른 영역 침범 안 했으면 본인 영역 owner = 본인이라 자동 통과 가능)
4. Merge

---

## 6. 각 팀원이 1회만 설정할 것

### (1) git 작성자 식별 패턴 설정

pre-commit 훅이 본인을 알아보게 하려면, `git config user.email` 에 본인 역할 키워드가 포함되어야 함.

```bash
git config user.email "본인이메일"

# 예: HJ 의 경우 — 이메일에 'hj' 또는 'youandi' 키워드 포함
git config user.email "hj@team.com"
git config user.email "youandi3535@naver.com"   # 도 OK (youandi 매칭)
git config user.email "hj-admin@company.com"

# 예: CS 의 경우 — 이메일에 'cs' 키워드 포함
git config user.email "cs-timeseries@team.com"
git config user.email "cs@gmail.com"            # 도 OK
git config user.email "kimcs@company.com"       # 도 OK (cs 포함)

# 예: NY 의 경우 — 이메일에 'ny' 키워드 포함
git config user.email "ny-anomaly@team.com"
git config user.email "ny@gmail.com"

# 예: jh 의 경우 — 이메일에 'jh' 키워드 포함
git config user.email "jh-tabular@team.com"
git config user.email "jh@gmail.com"
```

> ⚠️ 본인 키워드 (`hj`/`cs`/`ny`/`jh`) 가 이메일 어딘가에 들어가야 `scripts/dev/check_scope.sh` 가 본인 영역을 인식합니다.

### (2) pre-commit 훅 활성화

```bash
pip install pre-commit
pre-commit install
```

위 두 줄을 본인 PC 의 ADA 레포 폴더 안에서 1회만 실행하면, 이후 매 `git commit` 마다 자동으로 영역 검증·ruff·위생 검사가 수행됨.

---

## 7. HJ 가 1회만 할 것 (관리자)

| # | 작업 | 위치 | 소요 |
|--:|---|---|:--:|
| 1 | CODEOWNERS username 실명 매핑 | `.github/CODEOWNERS_TEAM_MAPPING.md` 표 작성 후 sed | 5분 |
| 2 | Branch protection rules 설정 | GitHub Settings → Branches → main | 5분 |
| 3 | (선택) Merge Queue 활성화 | 같은 페이지 | 1분 |
| 4 | GitHub Collaborators 추가 | Settings → Collaborators | 5분 |

### Branch protection 켤 옵션 5종
- ☑ Require pull request before merging
- ☑ Require approvals (1 명)
- ☑ **Require review from Code Owners** ← 핵심
- ☑ Require status checks: `lint-and-test`, `docker-build-check`
- ☑ Require branches to be up to date before merging

---

## 8. 침범 감지 흐름 (시스템이 어떻게 막아주는가)

```
팀원이 영역 외 파일 수정 시도
        │
        ▼
[① CLAUDE.md 자가 확인]   "이 파일은 OO영역인데 정말 수정할까요?"
        │ (사용자 강행)
        ▼
[② pre-commit 훅 차단]   ❌ "본인 영역 외 파일 수정 감지" + 위반 파일 출력
        │ (--no-verify 우회)
        ▼
[③ CODEOWNERS]           PR 페이지에 다른 영역 owner 자동 리뷰어 지정
        │
        ▼
[④ branch protection]    Code Owner 리뷰 없으면 머지 버튼 비활성
```

→ 4중 방어가 모두 뚫리려면 사용자가 강행 + `--no-verify` + Owner 가 검토 없이 승인까지 모두 필요. 사실상 불가능.

---

## 9. 멤버별 10일 핵심 업무 한 줄 요약

### HJ — 시스템·메타·인프라
**팀의 플랫폼 담당.** 4명의 작업을 지탱하는 CI/CD, 보안, MLflow, 산출물 carrier, dispatcher, Guardrails, output_extras 훅 등을 책임. 매일 가장 먼저 머지하여 다른 팀원의 작업 기반을 제공.

### CS — Timeseries (시계열)
**미래를 예측하는 사람.** 시간 흐름 데이터를 다뤄 "다음 7일 매출 12% 증가" 같은 예측 곡선 생성. SARIMA·Prophet·TFT 모델 활용. 데모: AirPassengers.

### NY — Anomaly (이상탐지)
**튀는 놈을 잡아내는 사람.** 정상 패턴에서 벗어난 데이터를 찾아 "거래 #12345 가 평균 대비 8.3σ 벗어남" Top-N 리포트 생성. IsolationForest·PyOD 7종 활용. 데모: KDD Cup 99.

### jh — Tabular (정형 ML/DL)
**표를 보고 정답을 맞히는 사람.** 정형 데이터 분류·회귀로 "X 피처가 결과의 32% 설명" 인사이트 생성. XGBoost·LightGBM·TabTransformer 활용. 데모: Titanic·Adult·Iris.

---

## 10. 핵심 R-규칙 (전원 준수)

| 규칙 | 내용 |
|---|---|
| R-003 | 새 agent 는 `BaseAgent` 상속 |
| R-004 | LLM 호출은 `BaseAgent._call_llm()` 단일 진입점 |
| R-005 | `PipelineState` 직접 수정 금지, `state.with_update(...)` 패턴만 |
| R-103 | PII 로그 출력 금지 |
| R-201 | 모든 학습은 MLflow 기록 |
| R-501 | RAG 검색 결과 인용 강제 |
| 카테고리 격리 | `state.category_extras["{cat}"]` 키 안에만 자기 데이터 |

---

## 11. 참고 문서 (레포 안)

- `AGENTS.md` — 룰 카탈로그 (R-001~R-1008)
- `TEAM_10DAY_SCHEDULE.md` — 10일 병렬 일정 + DoD
- `CLAUDE.md` — AI 가드레일
- `docs/PARALLEL_WORK_GUARDS.md` — 본 가드 구조 상세
- `.github/CODEOWNERS` — 영역 강제 (서버측)
- `.github/CODEOWNERS_TEAM_MAPPING.md` — username 매핑 절차

---

## 12. 첫 PR 시험 시나리오 (검증용)

머지 후 한 번 시험해보세요:

1. CS 가 `agents/handlers/timeseries/profiler.py` 정상 수정 → PR
   - 기대: pre-commit 통과 ✅, CS 자동 리뷰어 지정 ✅
2. CS 가 일부러 `ada/core/state.py` 한 줄 수정 → commit 시도
   - 기대: pre-commit 차단 ❌ "본인 영역 외 파일 수정 감지"
3. CS 가 `--no-verify` 로 우회 → PR 생성
   - 기대: HJ 가 자동 리뷰어로 지정됨, 머지 버튼 비활성

이 3가지 시나리오로 4중 방어가 모두 작동하는지 확인 가능.
