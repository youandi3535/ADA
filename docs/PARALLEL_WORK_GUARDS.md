# ADA v2 — 병렬 작업 가드 구조 (Parallel Work Guards)

> 4명 (HJ + CS + NY + jh) 의 동시 작업이 충돌 없이 진행되도록 설계된
> 3중 방어 + Category Ownership 패턴의 운영 가이드.

## 1. 전체 구조 한눈에

```
┌─────────────────────────────────────────────────────────────┐
│  Category Ownership 패턴                                     │
│  └─ 4명이 서로 겹치지 않는 폴더만 수정                          │
│                                                              │
│  ┌─ HJ:  ada/, orchestrator/, api/, outputs/, dispatcher 8종  │
│  ├─ CS:  agents/handlers/timeseries/, pipelines/timeseries/  │
│  ├─ NY:  agents/handlers/anomaly/,    pipelines/anomaly/     │
│  └─ jh:  agents/handlers/tabular/,    pipelines/tabular_*/   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  3중 방어 — 위반 시 자동 차단                                   │
│                                                              │
│  ① pre-commit 훅      → git commit 시점 (로컬)                │
│  ② CODEOWNERS         → PR 시점 (서버)                        │
│  ③ CI lint/test       → 머지 직전 (서버)                       │
└─────────────────────────────────────────────────────────────┘
```

## 2. Category Ownership — 단독 수정 파일 매트릭스

`.github/CODEOWNERS` 와 `CLAUDE.md` 가 동일한 매트릭스를 강제합니다.

| 폴더/파일 | 단독 수정자 | 다른 멤버 |
|---|---|---|
| `agents/handlers/timeseries/*` | **CS** | 읽기만 |
| `agents/handlers/anomaly/*` | **NY** | 읽기만 |
| `agents/handlers/tabular/*` | **jh** | 읽기만 |
| `pipelines/timeseries/*` | **CS** | 읽기만 |
| `pipelines/anomaly/*` | **NY** | 읽기만 |
| `pipelines/tabular_ml/*` · `pipelines/tabular_dl/*` | **jh** | 읽기만 |
| `tests/handlers/{cat}/*` | **각 카테고리 종주** | 읽기만 |
| `requirements/handlers-{cat}.txt` | **각 카테고리 종주** | 읽기만 |
| `ada/`, `orchestrator/`, `api/`, `outputs/*.py` | **HJ** | 변경 요청만 |
| 공유 dispatcher 8종 + 메타 5종 | **HJ** | 변경 요청만 |
| `requirements/worker.txt` 등 공통 deps | **HJ** | 변경 요청만 |
| `.github/`, `pyproject.toml`, `.pre-commit-config.yaml` | **HJ** | 변경 요청만 |

### 카테고리 데이터 격리 규약

각 카테고리는 자기 데이터를 `state.category_extras["{cat}"]` 키 안에만 저장.
타 카테고리 키 접근 금지.

```python
# ✅ CS 가 사용 (timeseries)
state.category_extras["timeseries"]["forecast"] = {}

# ❌ CS 가 사용 — 다른 카테고리 키 접근
state.category_extras["tabular"]["anything"] = {}
```

## 3. 3중 방어 — 위반 자동 차단

### 방어 ① — pre-commit 훅 (로컬, 커밋 시점)

**파일**: `.pre-commit-config.yaml`, `scripts/dev/check_scope.sh`

**작동 방식**:
1. 팀원이 `git commit` 실행
2. pre-commit 훅이 자동 발동
3. `check_scope.sh` 가 `git config user.email` 기반으로 작성자 식별
4. 변경 파일이 본인 허용 영역 밖이면 → **커밋 차단**

**설치** (각 팀원 1회):
```bash
pip install pre-commit
pre-commit install
```

**우회** (긴급시만):
```bash
git commit --no-verify -m "..."
```
→ 우회해도 방어 ②, ③ 가 막아줍니다.

### 방어 ② — CODEOWNERS (서버, PR 시점)

**파일**: `.github/CODEOWNERS`

**작동 방식**:
1. 팀원이 PR 생성
2. GitHub 이 변경 파일 기준으로 자동 리뷰어 지정
3. branch protection 의 "Require review from Code Owners" 가 켜져 있으면
4. → 해당 영역 소유자 리뷰 없으면 **머지 버튼 비활성**

**설정**: GitHub 레포 Settings → Branches → main protection rule

### 방어 ③ — CI lint/test (서버, 머지 직전)

**파일**: `.github/workflows/ci.yml`

**작동 방식**:
1. PR push 시 자동 실행
2. `ruff check .` 통과 의무
3. `pytest -q --cov` 통과 의무
4. `docker build` 통과 의무
5. → 하나라도 실패하면 머지 차단

## 4. 일자별 머지 순서 정책

자세한 일정은 `TEAM_10DAY_SCHEDULE.md` 참조.

| Day | 1번째 | 2번째 | 3번째 | 4번째 | 종류 | 사유 |
|:---:|:---:|:---:|:---:|:---:|:---:|---|
| 0  | HJ | — | — | — | 🔧 단독 | HJ 골격 작업 |
| 1  | HJ | CS | NY | jh | 🟢 자유 | leaf 작업, 의존성 0 |
| 2  | HJ | CS | NY | jh | 🟢 자유 | preprocessor 신규 |
| 3  | HJ | CS | NY | jh | 🟢 자유 | EDA, 의존성 없음 |
| 4  | HJ | CS | NY | jh | 🟡 권장 | Guardrails 강화 |
| 5  | HJ | CS | NY | jh | 🟢 자유 | JWT, selector |
| 6  | **HJ 필수** | CS | NY | jh | 🔴 **계약** | `state.best_params` 추가 |
| 7  | HJ | CS | NY | jh | 🟢 자유 | TrainingMonitor, evaluator |
| 8  | **HJ 필수** | CS | NY | jh | 🔴 **계약** | InsightAgent 가드레일 |
| 9  | **HJ 필수** | CS | NY | jh | 🔴 **계약** | `output_extras` 훅 시그니처 |
| 10 | HJ | CS | NY | jh | 🟢 자유 | KPI 위젯, E2E 데모 |

### 범례

- 🟢 **자유**: 어느 순서로 머지해도 충돌 없음. HJ 우선은 컨벤션 일관성용
- 🟡 **권장**: HJ 먼저가 안전하지만 강제는 아님
- 🔴 **계약**: HJ 가 인터페이스를 정의하므로 반드시 먼저 머지

## 5. Daily Workflow (각 팀원)

### 5-1. 아침 — 새 브랜치 시작
```bash
git checkout main
git pull origin main
git checkout -b feat/{본인}-day{N}
```

### 5-2. 낮 — 작업
- 본인 카테고리 폴더 안에서만 작업
- 커밋은 자주, push 는 하루 끝에
- 필요 시 본인 영역만 lint:
  ```bash
  ruff check agents/handlers/{본인_카테고리}/
  pytest tests/handlers/{본인_카테고리}/ -q
  ```

### 5-3. 저녁 — 머지 준비
```bash
bash scripts/dev/end_of_day.sh
```

스크립트가 6단계 자동 실행:
1. 영역 검증
2. 로컬 테스트
3. `git fetch origin`
4. `git rebase origin/main`
5. rebase 후 재테스트
6. `git push --force-with-lease`

### 5-4. PR 머지
1. GitHub 에서 PR 생성 (또는 자동 갱신)
2. CI 그린 확인
3. Code owner 리뷰 받기
4. Merge

## 6. 도구 일관성 — pyproject.toml

4명 PC 의 도구 버전 차이로 인한 diff 노이즈를 방지:

- **Python**: 3.10 핀 (Dockerfile, CI, 로컬 venv 모두)
- **Ruff**: `>=0.15.0` 핀 (`required-version`)
- **Line length**: 120
- **Target**: py310
- 카테고리별 per-file-ignores 설정

자세히: `pyproject.toml` 참조.

## 7. Claude AI 가드레일

4명이 Claude Code / Cowork 를 동시에 써도 충돌하지 않도록:

**파일**: `CLAUDE.md` (레포 루트)

**핵심 규칙**:
1. 세션 시작 시 역할 (HJ/CS/NY/jh) 확인
2. 본인 영역 외 수정 금지
3. "겸사겸사" 리팩토링 금지
4. 프로젝트 전체 ruff/format 자동 수정 금지
5. 새 의존성은 사용자 보고 후 HJ 협의

Claude 가 매 세션 자동 로드하므로 별도 설정 불필요.

## 8. 트러블슈팅

### Q1. pre-commit 훅이 본인을 못 알아봄
```
❌ 알 수 없는 작성자: alice@gmail.com
```
→ `git config user.email` 에 본인 역할 패턴 포함되어야 함:
```bash
git config user.email "cs-timeseries@team.com"
```
또는 `scripts/dev/check_scope.sh` 의 case 문에 본인 패턴 추가.

### Q2. rebase 충돌이 발생함
파일이 겹치지 않으니 진짜 충돌은 드물지만:
- 공유 파일 (`pyproject.toml`, `state.py` 등) 동시 수정이 원인
- 해결: 충돌 파일 열어서 수동 정리 → `git rebase --continue`
- 어려우면 HJ 에게 도움 요청

### Q3. PR 에 머지 버튼이 비활성됨
다음 중 하나가 안 됨:
- CI 그린 안 됨 → Actions 탭 확인
- Code owner 리뷰 없음 → Reviewers 섹션 확인
- Branch out-of-date → `end_of_day.sh` 다시 실행

### Q4. CODEOWNERS 가 작동 안 함
- `.github/CODEOWNERS_TEAM_MAPPING.md` 절차로 username 매핑 완료했는지 확인
- 레포 Settings → Branches → "Require review from Code Owners" 체크 확인

## 9. 파일 인벤토리

본 가드 구조를 구성하는 파일:

| 파일 | 역할 | 수정 권한 |
|---|---|---|
| `.github/CODEOWNERS` | 영역 강제 (서버측) | HJ |
| `.github/CODEOWNERS_TEAM_MAPPING.md` | username 매핑 절차 | HJ |
| `.github/PULL_REQUEST_TEMPLATE.md` | PR 자가검증 | HJ |
| `.github/workflows/ci.yml` | CI lint/test | HJ |
| `.pre-commit-config.yaml` | 커밋 시점 가드 | HJ |
| `pyproject.toml` | 도구 일관성 (ruff) | HJ |
| `scripts/dev/check_scope.sh` | 영역 검증 스크립트 | HJ |
| `scripts/dev/end_of_day.sh` | 머지 자동화 스크립트 | HJ |
| `CLAUDE.md` | AI 가드레일 | HJ |
| `AGENTS.md` | 룰 카탈로그 (R-001~) | HJ |
| `TEAM_10DAY_SCHEDULE.md` | 10일 일정 | HJ |
| `docs/PARALLEL_WORK_GUARDS.md` | 본 문서 | HJ |
| `requirements/worker.txt` | 4 카테고리 공통 의존성 | HJ |
| `requirements/handlers-timeseries.txt` | 시계열 카테고리 의존성 | CS |
| `requirements/handlers-anomaly.txt` | 이상탐지 카테고리 의존성 | NY |
| `requirements/handlers-tabular.txt` | 정형 ML/DL 카테고리 의존성 | jh |
| `outputs/base.py` | carrier 베이스 + `OutputExtrasHandler` Protocol | HJ |

## 10. P2 보강 완료 사항

### 10-1. requirements/handlers-{cat}.txt 분리 (완료)

기존 `worker.txt` 105줄에 4 카테고리 의존성이 몰려 있어, CS 가 darts 추가하고
jh 가 pytorch-tabular 추가하면 같은 파일 충돌 발생하던 구조를 분리:

| 파일 | 단독 수정자 | 현재 포함 패키지 |
|---|---|---|
| `requirements/handlers-timeseries.txt` | CS | statsmodels, prophet |
| `requirements/handlers-anomaly.txt` | NY | (현재 비어있음, pyod 활성화 슬롯) |
| `requirements/handlers-tabular.txt` | jh | xgboost, lightgbm, catboost, imbalanced-learn |
| `requirements/worker.txt` | HJ | 4 카테고리 공통 (`-r` 로 위 3 파일 자동 포함) |

`.github/CODEOWNERS` · `scripts/dev/check_scope.sh` · `CLAUDE.md` 의 멤버 영역에
이 신규 파일들이 자동 포함됨. 카테고리 의존성 추가 시 충돌 원천 차단.

### 10-2. outputs/base.py OutputExtrasHandler Protocol (완료)

Day 9 carrier 본구현 전에 시그니처만 미리 박아둠. 팀원이 Day 1~8 동안
자기 `handlers/{cat}/output_extras.py` 를 이 시그니처로 작성 가능:

```python
# outputs/base.py
@runtime_checkable
class OutputExtrasHandler(Protocol):
    def __call__(self, state, ctx): ...

OUTPUT_EXTRAS_KEYS = ("charts", "tables", "text_blocks")
```

Day 9 에 HJ 는 `OutputGenerator._call_extras()` 메서드를 본구현으로 채우기만
하면 됨 (현재는 stub). 팀원 작업과 머지 순서 의존성 제거.

#### 🚨 Day 9 HJ PR 머지 후 — CS / NY / jh **반드시** 액션 (자기 Day 9 차례 오면)

현재 각 카테고리 `output_extras.py` 의 `assets()` 는 **stub** 상태로,
HJ 가 정한 Protocol 시그니처와 어긋나 있음:

| 위치 | 현재 (잘못) | 요구 (Day 9 HJ PR 후) |
|---|---|---|
| `agents/handlers/timeseries/output_extras.py` | `def assets(state):` | `def assets(state, ctx):` |
| `agents/handlers/tabular/output_extras.py` | `def assets(state):` | `def assets(state, ctx):` |
| `agents/handlers/anomaly/output_extras.py` | `def assets(state):` | `def assets(state, ctx):` |
| 반환 키 | `{category_label, category_color, extra_charts, extra_tables}` | `{charts, tables, text_blocks}` |

**증상 (안 고치면)**: carrier 가 호출 시 `TypeError` → `_call_extras` 의 try/except 가 silent 로 흡수 → **카테고리 extras 가 PPT/PDF 에 영원히 안 들어감** (오류는 안 나지만 dead code).

**자기 Day 9 작업 시 해야 할 것 (CS/NY/jh 각자)**:

```python
# agents/handlers/{cat}/output_extras.py
from typing import Any

def assets(state: Any, ctx: dict[str, Any]) -> dict[str, Any]:
    """ctx 키:
       - output_code: "OUT-01" (PPT) | "OUT-02" (PDF) | ...
       - category:    state.category 복사
    """
    return {
        "charts":      [...],   # list[str]   — MinIO 경로 (PNG)
        "tables":      [...],   # list[dict]  — {title, columns, rows}
        "text_blocks": [...],   # list[str]   — 한국어 문단
    }
```

- 화이트리스트 밖 키 (`category_label`, `extra_*` 등) 는 자동 drop
- `ctx["output_code"]` 로 carrier 별 분기 가능 (PPT vs PDF 다른 차트 등)
- `build()` 라는 이름으로도 등록 가능 — `assets()` 보다 우선 호출됨

## 11. 향후 보강 (선택)

다음은 운영해보다 필요시 보강:

- **GitHub Merge Queue 활성화** — Settings → Branches → main 룰의 "Require merge queue"
  - 4명 동시 PR 머지 시 자동 직렬화 (현재는 수동 rebase 체인)
- **scripts/dev/morning_start.sh** — 아침 새 브랜치 시작 자동화
- **GitHub Actions ruff cache** — CI 속도 개선

---

## 변경 이력

- 2026-05-22: 초안 작성 (HJ, P0+P1+P2 가드 구조 설계 완료)
  - P0 4종: `pyproject.toml`, `.pre-commit-config.yaml`, `scripts/dev/check_scope.sh`, `CLAUDE.md`
  - P1 3종: PR 템플릿, CODEOWNERS 매핑 가이드, `scripts/dev/end_of_day.sh`
  - P2 2종: 카테고리별 `requirements/handlers-{cat}.txt` 분리, `OutputExtrasHandler` Protocol 사전 선언
- 2026-05-22: 멤버 이름 확정 (CS=Timeseries, NY=Anomaly, jh=Tabular). 전 문서 일괄 반영.
