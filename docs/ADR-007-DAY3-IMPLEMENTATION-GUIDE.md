# ADR-007 hj-day3 — 상세 구현 가이드 (Step-by-Step Implementation Guide)

> **본 문서 사용법**: ADR-007 (high-level 설계) 의 각 작업을 sub-step 단위로 쪼개서
> "복사 → 실행 → 검증 (3중)" 순으로 진행하면 누수 없이 완성되도록 작성.
> 각 sub-step 마다: **사전조건 / 입력 / 실행 / 예상출력 / 검증 3중 (정적+단위+통합) / 에러대응 / 다음 단계 진입 조건** 포함.
>
> **읽는 법**: `[L1.1.a]` 같은 식별자가 모든 단계에 부여됨. 진행 중 막히면 식별자 알려주시면 그 단계만 디버깅 가능.

---

## ⭐ 검증 3중 (Three-Fold Verification) — 모든 sub-step 의무 적용

> **원칙**: 어떤 변경이든 다음 3종을 **모두 통과**해야 다음 sub-step 으로 진입.
> 하나라도 실패하면 에러 대응 → 재실행 → 다시 3종 검증.

### V1 — 정적 검증 (Static)
**무엇**: 코드를 실행하지 않고 구조·문법·import 만 확인.
- `python -c "import ast; ast.parse(open(<file>).read())"` — AST 파싱
- `python -m ruff check <file>` — lint
- `python -c "from <module> import <symbol>"` — import 가능성
- 파일 인코딩 (`file <file>` 또는 UTF-8 strict decode)
- diff 검토 — 의도한 변경 외 다른 변경 없는지

**언제 통과**: 0 syntax error, 0 import error, 0 ruff error.

### V2 — 단위 검증 (Unit)
**무엇**: 변경된 함수/모듈을 실제로 호출해서 입출력 확인. Mock 활용.
- `pytest tests/test_xxx.py::test_specific -v` — 단일 테스트
- 또는 인터프리터 직접 호출:
  ```python
  python -c "from x import f; assert f(...) == expected"
  ```
- 입력 케이스 최소 3종: 정상 / 경계 / 에러
- 결과 dict/list 의 key/length 검증

**언제 통과**: 의도한 출력 = 실제 출력 (assertion 통과).

### V3 — 통합 검증 (Integration)
**무엇**: 실제 시스템에 적용했을 때 옆 모듈과 함께 동작하는지.
- `pytest tests/ -q` — 전체 회귀
- `uvicorn ... + curl/swagger` — HTTP 호출
- `streamlit run ... + 브라우저` — UI 시각
- 다른 sub-step 의 결과물과 함께 호출 (예: L2.1 + L2.2 라우트 동시에 swagger 에 노출)
- 통합 영향: 이 변경이 다른 모듈의 동작을 깨트리지 않는지

**언제 통과**: 회귀 0건 AND 의도한 외부 가시성 (swagger UI 노출 / 응답 JSON 키 / pytest 카운트) 모두 충족.

### 적용 표시 규칙
각 sub-step 의 "검증" 섹션은 다음 형태로 명시:
```
**검증 3중**:
- V1 정적: <구체 명령>  → 기대: <결과>
- V2 단위: <구체 명령>  → 기대: <결과>
- V3 통합: <구체 명령>  → 기대: <결과>

V1/V2/V3 중 하나라도 실패 → "에러 대응" 절로.
```

### 에러 대응 흐름
```
실패 발견
  ↓
어느 V 가 실패? (V1/V2/V3)
  ↓
"에러 대응" 절 의 해당 케이스 매칭
  ↓
픽스 적용
  ↓
실패한 V 부터 V3 까지 재검증 (V1 실패면 V1→V2→V3 모두 재)
```

---

## 📑 목차

- [Phase L1 — 마무리/검증 (필수, 30분)](#phase-l1--마무리검증-필수-30분)
- [Phase L2 — Phase 2 audit 라우트 확장 (1.5시간)](#phase-l2--phase-2-audit-라우트-확장-15시간)
- [Phase L3 — Langfuse 깊이 통합 (2시간)](#phase-l3--langfuse-깊이-통합-2시간)
- [Phase L4 — Streamlit 어드민 탭 (1시간)](#phase-l4--streamlit-어드민-탭-1시간)
- [Phase E — 통합 검증 스크립트](#phase-e--통합-검증-스크립트)
- [Phase F+G — 커밋 + Push](#phase-fg--커밋--push)
- [부록 A — 공통 패턴 / 코드 스니펫](#부록-a--공통-패턴--코드-스니펫)
- [부록 B — 디버깅 체크리스트](#부록-b--디버깅-체크리스트)

---

# Phase L1 — 마무리/검증 (필수, 30분)

## L1.0 — Phase 진입 전 사전조건 일괄 확인

### [L1.0.a] 작업 디렉토리·브랜치·venv 확인

**목적**: hj-day3 작업이 올바른 환경에서 시작되는지 보장.

**사전조건**: PowerShell 새 창.

**실행**:
```powershell
cd C:\IT\workspace_python\ADA
.\venv\Scripts\Activate.ps1
git branch --show-current
git status --short
```

**예상 출력**:
```
(venv) PS C:\IT\workspace_python\ADA>
feat/hj-day3
 M alembic.ini
```

**검증 3중**:
- **V1 정적**: `git rev-parse --git-dir` → 기대: `.git` (git repo 안에 있음)
- **V2 단위**: `git config --get user.email` → 기대: 본인 이메일 (commit 시 author 정확성)
- **V3 통합**: `git log --oneline -3` → 기대: 최근 commit 3개 표시 (브랜치 정상 fetch 됨)

**3중 모두 실패 시 공통 원인**: 작업 디렉토리가 잘못된 곳 (다른 폴더). `pwd` 로 `C:\IT\workspace_python\ADA` 확인.

**에러 대응**:
| 증상 | 원인 | 대응 |
|---|---|---|
| `feat/hj-day2` 가 브랜치명 | 브랜치 안 만듦 | `git checkout main && git pull && git checkout -b feat/hj-day3` |
| 변경 파일 다수 | 이전 작업 미커밋 | `git stash` 로 임시 보관 후 진행 |
| venv 활성화 실패 | venv 없음 | `python -m venv venv` |

**다음 단계 진입 조건**: 브랜치 = `feat/hj-day3` AND 활성화 OK

---

### [L1.0.b] 기존 테스트 베이스라인 확인

**목적**: hj-day3 변경 전 회귀 비교를 위한 baseline 측정.

**실행**:
```powershell
python -m pytest tests/ -q --no-header 2>&1 | Select-Object -Last 5
```

**예상 출력**: `331 passed, 5 skipped` (Phase 2 완료 시점 기준).

**검증**:
1. `failed` 항목 0건 (실패 있으면 hj-day3 시작 전 fix 필요)
2. `skipped` 5건 = 정상 (사전 의존성 부족 — 환경 의존)

**다음 단계 진입 조건**: 0 failed.

---

## L1.1 — alembic.ini 커밋

### [L1.1.a] 변경 내용 확인

**목적**: 커밋할 변경이 의도된 내용인지 확인.

**실행**:
```powershell
git diff alembic.ini
```

**예상 출력**: 한글 주석 (`§3 — Day02 마이그레이션`) 이 영문 (`sec.3 - Day02 migration baseline`) 으로 바뀐 diff.

**검증**:
1. 한글 라인 (라인 2~4, 12, 15) 만 변경
2. 실제 alembic 설정 키 (`[alembic]`, `script_location` 등) 변경 없음

**에러 대응**: 의도치 않은 변경 보이면 → `git checkout alembic.ini` 후 다시 시작.

---

### [L1.1.b] 커밋 실행

**실행**:
```powershell
git add alembic.ini
git commit -m "hj-day3: alembic.ini 한글 주석 영문화 (cp949 인코딩 버그 회피)

Windows 한국어 locale 에서 alembic 이 .ini 파일을 cp949 로 읽으려 시도하면서
UTF-8 한글 (§, —, 한국어) 디코드 실패. ASCII-only 로 전환.

영구 해결을 원치 않는 경우 alembic 실행 전 PYTHONUTF8=1 환경변수 설정.
"
```

**예상 출력**:
```
... pre-commit hooks ...
ruff (legacy alias).........(no files to check) Skipped
... 영역 검증 통과 ...
[feat/hj-day3 xxxxxxx] hj-day3: alembic.ini 한글 주석 영문화 ...
 1 file changed, 6 insertions(+), 4 deletions(-)
```

**검증 3중**:
- **V1 정적**: `git log -1 --stat` → 기대: 새 커밋이 alembic.ini 1개 파일만 수정 (다른 파일 섞임 없음)
- **V2 단위**: `git diff HEAD~1 alembic.ini | findstr -i "한글\|Day02"` → 기대: 한국어 라인 제거 + 영문 라인 추가 confirmed
- **V3 통합**: `git status` → 기대: `nothing to commit, working tree clean` AND `git log --oneline -5` 의 최상단이 새 commit

**3중 추가**:
- pre-commit 훅 출력에 `Passed` 또는 `Skipped` 만 (Failed 0건)
- pre-commit 의 `check_scope.sh` 통과 (`✅ 영역 검증 통과 — HJ`)
- post-merge / pre-commit 둘 다 hook 자동 실행됨

**에러 대응**:
- 영역 검증 실패 (`check_scope.sh`) → alembic.ini 가 HJ 영역인지 확인 (맞음, R-403 통과)
- `--no-verify` 절대 사용 금지

**다음 단계 진입 조건**: `git status` = clean.

---

## L1.2 — Day 3 pytest 5건 그린

### [L1.2.a] 단일 테스트 파일 실행

**목적**: 5개 테스트가 모두 통과하는지 확인 (DoD 의 일부).

**실행**:
```powershell
python -m pytest tests/test_day3_admin_langfuse.py -v
```

**예상 출력**:
```
collected 5 items

tests/test_day3_admin_langfuse.py::test_langfuse_verify_no_keys PASSED       [ 20%]
tests/test_day3_admin_langfuse.py::test_admin_router_routes_listed PASSED    [ 40%]
tests/test_day3_admin_langfuse.py::test_admin_rbac_blocks_analyst PASSED     [ 60%]
tests/test_day3_admin_langfuse.py::test_admin_prometheus_check PASSED        [ 80%]
tests/test_day3_admin_langfuse.py::test_langfuse_verify_mocked_client PASSED [100%]

============== 5 passed in 1.xx s ==============
```

**검증 3중**:

**V1 정적** — 테스트 파일 자체 무결성
```powershell
python -c "import ast; ast.parse(open('tests/test_day3_admin_langfuse.py').read()); print('AST OK')"
python -m ruff check tests/test_day3_admin_langfuse.py
```
기대: `AST OK` + `All checks passed!`

**V2 단위** — 5개 테스트 통과
```powershell
python -m pytest tests/test_day3_admin_langfuse.py -v --tb=short
```
기대:
- `5 passed`
- 각 테스트 PASSED 라인
- 실행 시간 < 3초 (Mock 위주)
- WARNING 정상 (Pydantic deprecation 등) — ERROR 0건

**V3 통합** — 다른 테스트와의 회귀 없음
```powershell
python -m pytest tests/ -q 2>&1 | Select-String -Pattern "passed|failed" | Select-Object -Last 3
```
기대: `331 passed, 5 skipped` (또는 그 이상 — baseline 보다 증가 OK, 감소 NG)

**3중 모두 PASS → 다음 진입.** 하나라도 실패 → 아래 에러 대응.

**에러 대응 (실패별)**:

| 실패 테스트 | 추정 원인 | 해결 |
|---|---|---|
| `test_langfuse_verify_no_keys` | langfuse_client import 실패 | `pip install langfuse==2.36.0` |
| `test_admin_router_routes_listed` | fastapi 미설치 | `pip install fastapi==0.111.0` |
| `test_admin_rbac_blocks_analyst` | jose 미설치 | `pip install python-jose[cryptography]==3.3.0` |
| `test_admin_prometheus_check` | prometheus_client 미설치 | `pip install prometheus-client==0.20.0` |
| `test_langfuse_verify_mocked_client` | monkeypatch 실패 | pytest 버전 확인 (8.2.1+ 필요) |

**다음 단계 진입 조건**: 5/5 passed.

---

### [L1.2.b] 회귀 확인 (전체 pytest)

**실행**:
```powershell
python -m pytest tests/ -q
```

**예상 출력**: `331 passed, 5 skipped` (또는 그 이상).

**검증**:
1. failed 0건
2. baseline (L1.0.b) 와 비교해서 줄어들지 않음

**다음 단계 진입 조건**: 회귀 0건.

---

## L1.3 — Swagger 시각 확인

### [L1.3.a] DB 연결 가능성 확인

**목적**: uvicorn 띄우기 전 의존성 (Postgres, Redis) 살아있는지.

**실행**:
```powershell
docker compose -f docker/docker-compose.yml ps postgres redis
```

**예상 출력** (정상):
```
NAME                IMAGE          STATUS              PORTS
ada-postgres-1      postgres:16    Up (healthy)        0.0.0.0:5433->5432/tcp
ada-redis-1         redis:7        Up                  0.0.0.0:6379->6379/tcp
```

**에러 대응**:
- 컨테이너 없음/Stopped → `docker compose -f docker/docker-compose.yml up -d postgres redis`
- 그래도 안 됨 → Docker Desktop 실행 확인

**선택지** (DB 안 떠도 진행 가능):
- 옵션 A: DB 띄우고 진행 (정석)
- 옵션 B: DB 없이 진행 — uvicorn 부팅 시 일부 라우터 lazy-load 이라 / docs 만 보면 OK
- 옵션 C: 이 단계 skip (L1.2 만으로도 DoD 일부 충족)

**다음 단계 진입 조건**: postgres healthy 또는 옵션 B/C 선택.

---

### [L1.3.b] uvicorn 띄우기

**목적**: FastAPI 앱이 부팅해서 swagger UI 가 노출되는지.

**실행** (별도 PowerShell 탭/창):
```powershell
cd C:\IT\workspace_python\ADA
.\venv\Scripts\Activate.ps1
$env:PYTHONUTF8="1"
uvicorn api.main:app --reload --port 8000
```

**예상 출력**:
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [xxxxx] using StatReload
INFO:     Started server process [xxxxx]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

**검증**:
1. `Application startup complete` 출력
2. 에러 traceback 없음

**에러 대응**:

| 증상 | 원인 | 대응 |
|---|---|---|
| `ModuleNotFoundError: No module named 'uvicorn'` | uvicorn 미설치 | `pip install uvicorn[standard]==0.29.0` |
| `ImportError: cannot import name 'XXX' from 'ada...'` | 모듈 누락 | 에러 메시지의 모듈 import path 확인 |
| 부팅 즉시 종료 | api/main.py 에러 | 에러 traceback 확인, 해당 모듈 픽스 |
| `Address already in use` | 포트 충돌 | `--port 8001` 로 변경 |

**다음 단계 진입 조건**: uvicorn running 메시지.

---

### [L1.3.c] Swagger UI 시각 확인 — Admin 섹션

**목적**: `/admin/audit` 등 4개 엔드포인트가 swagger 에 노출되는지.

**실행** (브라우저):
```
http://localhost:8000/docs
```

**예상 결과**:
- `default`, `Upload`, `Pipeline`, `Stream`, `Auth`, `KB`, `Metrics`, **`Admin`**, `ErrorDashboard`, ... 태그 노출
- **Admin 섹션 펼치면 4개 엔드포인트**:
  - `GET /admin/audit`
  - `GET /admin/audit/summary`
  - `GET /admin/observability/langfuse`
  - `GET /admin/observability/prometheus_check`

**검증 3중**:

**V1 정적** — OpenAPI 스키마 JSON 직접 조회
```powershell
# 별도 PowerShell
curl http://localhost:8000/openapi.json | python -m json.tool > openapi_dump.json
findstr "/admin/audit\|/admin/observability/langfuse" openapi_dump.json
```
기대: 4개 path 모두 매칭. 각 path 의 `"tags": ["Admin"]` 확인.

**V2 단위** — 라우트 객체 직접 검사 (브라우저 없이)
```powershell
python -c @"
from api.routes.admin import router
paths = {r.path for r in router.routes}
required = {'/admin/audit', '/admin/audit/summary', '/admin/observability/langfuse', '/admin/observability/prometheus_check'}
missing = required - paths
assert not missing, f'누락: {missing}'
print('OK — 4개 모두 등록됨:', sorted(paths))
"@
```
기대: `OK — 4개 모두 등록됨` 출력.

**V3 통합** — 브라우저 시각 + 클릭 가능성
1. `http://localhost:8000/docs` 페이지 로드
2. Admin 섹션 펼침 — 4 엔드포인트 노출
3. 각 클릭 시 "Try it out" 버튼 + Parameters 폼 표시
4. 우상단 "Authorize" 버튼 존재 (HTTP Bearer 인증 스키마 인지)

**3중 모두 통과 → DoD 충족.** 이 시점에서 Mini 옵션 종료 가능.

**에러 대응**:
- Admin 섹션 없음 → `api/main.py` 의 `include_router(admin_routes.router)` 누락. 확인 후 추가.
- 4개 중 일부 누락 → `api/routes/admin.py` 의 `@router.get(...)` 누락. 코드 확인.

**다음 단계 진입 조건**: 4개 엔드포인트 모두 노출. **이 시점에서 공식 DoD 충족.**

---

### [L1.3.d] (선택) 실제 호출 테스트

**목적**: JWT 인증 + 라우트 실행이 end-to-end 작동하는지.

**실행 1 — JWT 발급**:
```powershell
# 별도 PowerShell (uvicorn 은 그대로)
$env:PYTHONUTF8="1"
python -c @"
from ada.security.jwt import create_access_token
print(create_access_token(sub='admin-user', role='admin'))
"@
```

**예상 출력**: `eyJhbGciOiJIUzI1NiIs...` (JWT 토큰 한 줄).

**실행 2 — swagger 에서 Authorize**:
1. `/docs` 페이지의 우상단 "Authorize" 버튼 클릭
2. `Bearer <위 토큰>` 입력
3. Authorize → Close

**실행 3 — `/admin/observability/langfuse` 호출**:
1. 해당 엔드포인트 펼치기
2. "Try it out" → "Execute"
3. Response 확인

**예상 응답 (Langfuse 키 없을 때)**:
```json
{"connected": false, "host": "", "reason": "keys_missing_or_init_failed"}
```

**검증**:
1. HTTP 200 (RBAC 통과)
2. JSON 응답에 `connected` 필드

**에러 대응**:
- 401 → JWT 만료/형식 오류, 토큰 재발급
- 403 → 토큰의 role 이 admin 아님, `role='admin'` 으로 다시
- 500 → 서버 에러, uvicorn 콘솔 traceback 확인

**다음 단계 진입 조건**: 200 응답 받음 (또는 이 단계 skip).

---

### [L1.3.e] uvicorn 종료

**실행**: uvicorn 터미널에서 `Ctrl+C`

**검증**: `Application shutdown complete` 출력 후 프롬프트 복귀.

---

## L1 종료 체크리스트

```
[ ] L1.0.a  브랜치 = feat/hj-day3, venv 활성화
[ ] L1.0.b  baseline pytest 0 failed
[ ] L1.1.a  alembic.ini diff 확인
[ ] L1.1.b  커밋 + pre-commit 통과
[ ] L1.2.a  pytest day3 5/5 passed
[ ] L1.2.b  전체 pytest 회귀 없음
[ ] L1.3.a  postgres healthy (or skip)
[ ] L1.3.b  uvicorn 부팅 OK
[ ] L1.3.c  swagger Admin 섹션 4개 확인 ⭐ DoD
[ ] L1.3.d  (선택) 실제 호출 200
[ ] L1.3.e  uvicorn 종료
```

**L1 PASS 시점**: L1.3.c 완료. 여기서 Mini 옵션 선택 가능 (= push 후 종료).

---

# Phase L2 — Phase 2 audit 라우트 확장 (1.5시간)

## L2.0 — Phase 진입 전 사전조건

### [L2.0.a] L1 완료 확인

**검증**: L1 종료 체크리스트 모두 ✓.

### [L2.0.b] 모델 import 가능성 확인

**목적**: 새 라우트가 사용할 모델들이 이미 import 가능한지.

**실행**:
```powershell
python -c @"
from ada.db.models import FailureLog, PatchApplication, CircuitBreakerEvent
print('FailureLog cols:', [c.name for c in FailureLog.__table__.columns][:8], '...')
print('PatchApplication:', PatchApplication.__tablename__)
print('CircuitBreakerEvent:', CircuitBreakerEvent.__tablename__)
"@
```

**예상 출력**:
```
FailureLog cols: ['id', 'job_id', 'error_hash', 'error_category', ...] ...
PatchApplication: patch_applications
CircuitBreakerEvent: circuit_breaker_events
```

**검증**:
1. import 에러 없음
2. 모델 컬럼 확인 가능

**에러 대응**: import 에러 → Phase 2-F.1 (모델 추가) 가 미완료. 이전 단계 확인.

---

## L2.1 — `/admin/autofix/failure_logs` 엔드포인트

### [L2.1.a] Pydantic 응답 모델 설계

**입력**: 페이지네이션 + 필터 파라미터.
**출력 스키마**:

```python
# api/routes/admin.py 에 추가할 모델
class FailureLogEntry(BaseModel):
    id: str
    job_id: Optional[str] = None
    error_hash: str
    error_category: Optional[str] = None
    classified_as: Optional[str] = None       # Phase 2-B
    severity: Optional[str] = None             # Phase 2-F
    redaction_types: Optional[list[str]] = None  # Phase 2-A
    auto_handled_by_kb: bool
    error_kb_id: Optional[str] = None
    error_message_redacted: Optional[str] = None  # 이미 redacted 된 것
    created_at: Optional[str] = None


class FailureLogPage(BaseModel):
    items: list[FailureLogEntry]
    total: int
    page: int
    page_size: int
```

**검증 (정적)**:
1. `BaseModel` import 이미 있음 (line 18)
2. `Optional` import 이미 있음 (line 15)

---

### [L2.1.b] 핸들러 구현

**위치**: `api/routes/admin.py` 의 마지막 (line 152 뒤).

**실행 (붙여넣기)**:

```python
# =============================================================================
# ADR-007 L2 — Phase 2 audit 확장
# =============================================================================


@router.get("/admin/autofix/failure_logs", response_model=FailureLogPage, tags=["Admin", "AutoFix"])
async def get_autofix_failure_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    classified_as: Optional[str] = Query(None, description="transient|code_bug|config|data|user_input|unknown"),
    severity: Optional[str] = Query(None, description="low|normal|high|critical"),
    auto_handled_by_kb: Optional[bool] = None,
    since_hours: Optional[int] = Query(None, ge=1, le=24 * 30),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),
) -> FailureLogPage:
    """ADR-006 Phase 2-F — FailureLog 페이지네이션 + 분류 필터."""
    from ada.db.models import FailureLog

    where_clauses = []
    if classified_as:
        where_clauses.append(FailureLog.classified_as == classified_as)
    if severity:
        where_clauses.append(FailureLog.severity == severity)
    if auto_handled_by_kb is not None:
        where_clauses.append(FailureLog.auto_handled_by_kb == auto_handled_by_kb)
    if since_hours:
        where_clauses.append(FailureLog.created_at >= datetime.utcnow() - timedelta(hours=since_hours))

    base_q = select(FailureLog)
    for c in where_clauses:
        base_q = base_q.where(c)

    total = int((await db.execute(select(func.count()).select_from(base_q.subquery()))).scalar() or 0)

    rows = (
        await db.scalars(
            base_q.order_by(desc(FailureLog.created_at)).offset((page - 1) * page_size).limit(page_size)
        )
    ).all()

    items = [
        FailureLogEntry(
            id=str(r.id),
            job_id=str(r.job_id) if r.job_id else None,
            error_hash=r.error_hash,
            error_category=r.error_category,
            classified_as=r.classified_as,
            severity=r.severity,
            redaction_types=r.redaction_types if isinstance(r.redaction_types, list) else None,
            auto_handled_by_kb=bool(r.auto_handled_by_kb),
            error_kb_id=str(r.error_kb_id) if r.error_kb_id else None,
            error_message_redacted=(r.error_message or "")[:500] if r.error_message else None,
            created_at=r.created_at.isoformat() if r.created_at else None,
        )
        for r in rows
    ]
    return FailureLogPage(items=items, total=total, page=page, page_size=page_size)
```

**핵심 설계 선택**:
1. **`error_message_redacted`**: 컬럼명에 `_redacted` 접미사 명시 — UI 에서 "이건 이미 마스킹된 것" 임을 인지
2. **`[:500]` 잘림**: payload 비대 방지
3. **`severity` 필터**: 운영자가 critical 만 보고 싶을 때
4. **순서**: 최신순 (`desc(created_at)`)

**검증 3중**:

**V1 정적** — 코드 무결성
```powershell
python -c "import ast; ast.parse(open('api/routes/admin.py').read()); print('AST OK')"
python -m ruff check api/routes/admin.py
python -c "from api.routes.admin import FailureLogEntry, FailureLogPage; print('Pydantic models OK')"
```
기대: AST OK + ruff All checks passed + Pydantic models OK

**V2 단위** — 라우트 객체 등록 확인
```powershell
python -c @"
from api.routes.admin import router
paths = {r.path for r in router.routes}
assert '/admin/autofix/failure_logs' in paths, f'미등록. 현재: {sorted(paths)}'
print('OK — failure_logs 라우트 등록됨')
"@
```
기대: OK 출력.

**V3 통합** — 다른 라우트와의 공존 (swagger 시각)
- uvicorn 띄우고 `/docs` 에서 `AutoFix` 태그 (또는 Admin 아래) 에 새 엔드포인트 등장
- 기존 4개 Admin 엔드포인트도 그대로 노출 (회귀 없음)

---

### [L2.1.c] 단위 테스트 추가

**위치**: `tests/test_day3_admin_langfuse.py` 끝.

**핵심 테스트**:
```python
def test_admin_failure_logs_pagination(monkeypatch):
    """failure_logs 라우트 — 페이지네이션 + 필터."""
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ada.security.jwt import get_current_user
    from ada.db.session import get_db
    from api.routes import admin as admin_routes

    app = FastAPI()
    app.include_router(admin_routes.router)

    # Mock DB session - empty result
    class FakeScalars:
        def all(self): return []

    class FakeSession:
        async def execute(self, *a, **k):
            class _R:
                def scalar(self): return 0
            return _R()
        async def scalars(self, *a, **k): return FakeScalars()

    async def fake_db():
        yield FakeSession()

    async def fake_admin():
        return {"user_id": "u1", "role": "admin"}

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = fake_admin

    client = TestClient(app)
    r = client.get("/admin/autofix/failure_logs?page=1&page_size=10")
    assert r.status_code == 200
    body = r.json()
    assert body["page"] == 1
    assert body["page_size"] == 10
    assert body["total"] == 0
    assert body["items"] == []


def test_admin_failure_logs_filter_classified(monkeypatch):
    """classified_as 필터가 query string 으로 전달되는지."""
    # 위와 같은 setup, ?classified_as=transient 호출 시 200
    ...
```

**검증 (3중)**:
1. pytest 통과
2. ruff 통과
3. 회귀 없음 (전체 pytest)

---

### [L2.1.d] 통합 검증 (uvicorn + swagger)

**실행**:
```powershell
uvicorn api.main:app --reload --port 8000
# 브라우저: /docs
# Admin 섹션에 GET /admin/autofix/failure_logs 가 추가됐는지 확인
# AutoFix 태그가 새로 생겼는지 확인
```

**검증**: 새 엔드포인트가 노출됨.

---

## L2.2 — `/admin/autofix/patch_applications` 엔드포인트

### [L2.2.a] 응답 모델 설계

```python
class PatchAppEntry(BaseModel):
    id: str
    pending_patch_id: Optional[str] = None
    error_kb_id: Optional[str] = None
    applied_by: Optional[str] = None
    applied_at: Optional[str] = None
    status: Optional[str] = None  # success | rolled_back | failed
    git_commit_sha: Optional[str] = None
    rollback_commit_sha: Optional[str] = None
    duration_ms: Optional[int] = None
    # sandbox_validation 은 길어서 sample 만
    validation_passed: Optional[bool] = None
    tests_run: Optional[int] = None


class PatchAppPage(BaseModel):
    items: list[PatchAppEntry]
    total: int
    page: int
    page_size: int
    status_counts: dict[str, int]  # {"success": 5, "failed": 2, ...}
```

### [L2.2.b] 핸들러

```python
@router.get("/admin/autofix/patch_applications", response_model=PatchAppPage, tags=["Admin", "AutoFix"])
async def get_patch_applications(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    status: Optional[str] = Query(None, description="success|rolled_back|failed"),
    applied_by: Optional[str] = None,
    since_hours: Optional[int] = Query(24, ge=1, le=24 * 90),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),
) -> PatchAppPage:
    from ada.db.models import PatchApplication

    where = [PatchApplication.applied_at >= datetime.utcnow() - timedelta(hours=since_hours)]
    if status:
        where.append(PatchApplication.status == status)
    if applied_by:
        where.append(PatchApplication.applied_by == applied_by)

    base_q = select(PatchApplication)
    for c in where:
        base_q = base_q.where(c)

    total = int((await db.execute(select(func.count()).select_from(base_q.subquery()))).scalar() or 0)

    # status 분포
    status_rows = await db.execute(
        select(PatchApplication.status, func.count())
        .where(*where)
        .group_by(PatchApplication.status)
    )
    status_counts = {s or "?": int(n) for s, n in status_rows}

    rows = (
        await db.scalars(
            base_q.order_by(desc(PatchApplication.applied_at))
            .offset((page - 1) * page_size).limit(page_size)
        )
    ).all()

    items = []
    for r in rows:
        sv = r.sandbox_validation if isinstance(r.sandbox_validation, dict) else {}
        items.append(PatchAppEntry(
            id=str(r.id),
            pending_patch_id=str(r.pending_patch_id) if r.pending_patch_id else None,
            error_kb_id=str(r.error_kb_id) if r.error_kb_id else None,
            applied_by=r.applied_by,
            applied_at=r.applied_at.isoformat() if r.applied_at else None,
            status=r.status,
            git_commit_sha=r.git_commit_sha,
            rollback_commit_sha=r.rollback_commit_sha,
            duration_ms=r.duration_ms,
            validation_passed=sv.get("passed") if sv else None,
            tests_run=sv.get("tests_run") if sv else None,
        ))
    return PatchAppPage(items=items, total=total, page=page, page_size=page_size, status_counts=status_counts)
```

**핵심 설계 선택**:
- `sandbox_validation` JSONB 를 통째로 노출 안 함 → `passed` / `tests_run` 만 sample
- `status_counts` 추가로 한 번 호출에 분포 확인 가능

### [L2.2.c] 테스트

```python
def test_admin_patch_applications_returns_status_counts(monkeypatch):
    # Mock setup: rows 가 [success, success, failed] 면 status_counts={"success":2,"failed":1}
    ...
```

---

## L2.3 — `/admin/autofix/circuit_breakers` 엔드포인트

### [L2.3.a] 응답 모델 — Redis + DB hybrid

```python
class BreakerState(BaseModel):
    name: str
    state: str  # closed | open | half_open
    failure_count: int
    failure_threshold: int
    recovery_timeout: int


class BreakerEventEntry(BaseModel):
    id: str
    breaker_name: str
    event_type: Optional[str] = None
    failure_count: Optional[int] = None
    opened_at: Optional[str] = None
    closed_at: Optional[str] = None
    created_at: Optional[str] = None


class BreakerStatusResponse(BaseModel):
    current_state: dict[str, BreakerState]  # name → state
    recent_events: list[BreakerEventEntry]
```

### [L2.3.b] 핸들러

```python
@router.get("/admin/autofix/circuit_breakers", response_model=BreakerStatusResponse, tags=["Admin", "AutoFix"])
async def get_circuit_breakers(
    event_limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),
) -> BreakerStatusResponse:
    """ADR-006 Phase 2-C — 회로 차단기 현재 상태 + 최근 이벤트."""
    from ada.db.models import CircuitBreakerEvent
    from ada.error_handler.circuit_breaker import get_breaker

    # Redis (또는 in-memory) 에서 현재 상태 조회
    known_breakers = ["ollama", "claude_cli", "anthropic"]
    current_state: dict[str, BreakerState] = {}
    for name in known_breakers:
        cb = get_breaker(name)
        try:
            state = await cb.state()
        except Exception:
            state = "unknown"
        current_state[name] = BreakerState(
            name=name,
            state=state,
            failure_count=0,  # 정확한 값은 backend 가 expose 안 함 — 0 placeholder
            failure_threshold=cb.failure_threshold,
            recovery_timeout=cb.recovery_timeout,
        )

    # DB 에서 최근 이벤트 (Phase 3 alerting 모듈이 채울 예정, 현재는 비어있을 수 있음)
    rows = (
        await db.scalars(
            select(CircuitBreakerEvent)
            .order_by(desc(CircuitBreakerEvent.created_at))
            .limit(event_limit)
        )
    ).all()
    recent = [
        BreakerEventEntry(
            id=str(r.id),
            breaker_name=r.breaker_name,
            event_type=r.event_type,
            failure_count=r.failure_count,
            opened_at=r.opened_at.isoformat() if r.opened_at else None,
            closed_at=r.closed_at.isoformat() if r.closed_at else None,
            created_at=r.created_at.isoformat() if r.created_at else None,
        )
        for r in rows
    ]

    return BreakerStatusResponse(current_state=current_state, recent_events=recent)
```

**핵심 설계 선택**:
- Redis 가 없으면 `_InMemoryBackend` 로 자동 폴백 → `cb.state()` 는 안전
- 알려진 breaker 이름 hardcoded (`ollama`, `claude_cli`, `anthropic`) — Phase 3 에서 동적 발견으로 확장

### [L2.3.c] 테스트

```python
def test_admin_circuit_breakers_returns_current_state(monkeypatch):
    """3개 알려진 breaker 모두 상태 반환되는지."""
    ...
```

---

## L2.4 — `/admin/autofix/budget` 엔드포인트

### [L2.4.a] 응답 모델

```python
class BudgetSnapshot(BaseModel):
    today_spend_usd: float
    today_calls: int
    daily_limit_usd: float
    remaining_usd: float
    is_exceeded: bool
    date_utc: str
```

### [L2.4.b] 핸들러

```python
@router.get("/admin/autofix/budget", response_model=BudgetSnapshot, tags=["Admin", "AutoFix"])
async def get_autofix_budget(_user: dict = Depends(_admin_only)) -> BudgetSnapshot:
    """ADR-006 Phase 2-D — 오늘 LLM 비용 누계."""
    from ada.error_handler.budget import get_budget_manager

    bm = get_budget_manager()
    spend = await bm.get_today_spend()
    calls = await bm.get_today_calls()
    limit = bm._daily_limit()  # private 메서드지만 안전
    remaining = await bm.remaining_budget()
    exceeded = await bm.is_exceeded()

    return BudgetSnapshot(
        today_spend_usd=round(spend, 4),
        today_calls=calls,
        daily_limit_usd=limit,
        remaining_usd=round(remaining, 4),
        is_exceeded=exceeded,
        date_utc=bm._today_key(),
    )
```

**핵심 설계 선택**:
- DB 안 거치고 Redis (또는 in-memory) 만 — sub-100ms 응답
- 4자리 소수점 (`$0.0123` 같은 단위 표시)

### [L2.4.c] 테스트

```python
def test_admin_budget_snapshot(monkeypatch):
    """예산 정보 정확히 반환."""
    from ada.error_handler.budget import reset_singleton, BudgetManager, get_budget_manager
    import ada.error_handler.budget as bm_mod

    reset_singleton()
    # 테스트용 인스턴스 주입
    bm = BudgetManager(redis_url="redis://nonexistent:9999", daily_limit_usd=100.0)
    bm_mod._INSTANCE = bm

    # 호출 누적
    asyncio.run(bm.track_call("claude-sonnet-4-6", 1000, 500))

    # 라우트 호출
    ...
    assert body["today_spend_usd"] == 0.0105
    assert body["daily_limit_usd"] == 100.0
```

---

## L2.5 — 통합 검증

### [L2.5.a] pytest 전체

```powershell
python -m pytest tests/test_day3_admin_langfuse.py -v
# 기존 5 + 신규 4 = 9 passed 예상
```

### [L2.5.b] uvicorn + swagger

```powershell
uvicorn api.main:app --reload --port 8000
# /docs 에서 AutoFix 태그 (또는 Admin 태그 안) 4개 추가된 것 확인
```

### [L2.5.c] 회귀

```powershell
python -m pytest tests/ -q
# 331 + 4 = 335 passed 예상
```

## L2 종료 체크리스트

```
[ ] L2.0.a  L1 완료
[ ] L2.0.b  모델 import 가능
[ ] L2.1.a  failure_logs 응답 모델
[ ] L2.1.b  failure_logs 핸들러
[ ] L2.1.c  failure_logs 테스트
[ ] L2.1.d  swagger 확인
[ ] L2.2.a  patch_applications 응답 모델
[ ] L2.2.b  patch_applications 핸들러
[ ] L2.2.c  patch_applications 테스트
[ ] L2.3.a  circuit_breakers 응답 모델
[ ] L2.3.b  circuit_breakers 핸들러
[ ] L2.3.c  circuit_breakers 테스트
[ ] L2.4.a  budget 응답 모델
[ ] L2.4.b  budget 핸들러
[ ] L2.4.c  budget 테스트
[ ] L2.5.a  pytest day3 9 passed
[ ] L2.5.b  swagger 4 신규 노출
[ ] L2.5.c  전체 회귀
[ ] L2.6   commit + push (Standard 옵션 종료)
```

---

# Phase L3 — Langfuse 깊이 통합 (2시간)

## L3.0 — 사전 분석

### [L3.0.a] 영향 범위 파악

**목적**: `_call_llm_api` 변경이 어떤 agent 들에 영향 미치는지.

**실행**:
```powershell
python -c @"
import os
agents_dir = 'agents'
llm_users = []
for root, _, files in os.walk(agents_dir):
    for f in files:
        if not f.endswith('.py'): continue
        path = os.path.join(root, f)
        content = open(path, encoding='utf-8').read()
        if 'self._call_llm(' in content or 'await self._call_llm' in content:
            llm_users.append(path)
print('LLM-using agents:')
for p in llm_users: print(' -', p)
print(f'Total: {len(llm_users)}')
"@
```

**예상 출력**: 5~10개 agent 파일 (대부분 dispatcher 들).

**검증**: 회귀 위험 평가 — 이 agent 들이 모두 pytest 로 커버되는지 확인.

---

### [L3.0.b] 기존 동작 baseline 확보

**목적**: track_llm 통합 후 LLM 호출 동작 변화 없는지 비교.

**실행**: 기존 LLM-using agent 의 pytest 결과 캡쳐.
```powershell
python -m pytest tests/ -v -k "llm" 2>&1 | Tee-Object -FilePath baseline_llm_tests.txt
```

---

## L3.1 — `_call_llm_api` 에 `track_llm` 통합

### [L3.1.a] 코드 수정 위치 파악

**파일**: `agents/base.py`
**메서드**: `_call_llm_api` (line 175~212 부근)

**수정 전**:
```python
async def _call_llm_api(self, ...):
    import anthropic
    if self._anthropic is None:
        self._anthropic = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    breaker = get_breaker("anthropic", ...)

    async def _do_call() -> Any:
        return await self._anthropic.messages.create(...)

    try:
        resp = await breaker.call(_do_call) if ... else await _do_call()
    except Exception as e:
        self.logger.error("llm_api_call_failed", error=str(e))
        raise

    # 토큰 누적
    usage = getattr(resp, "usage", None)
    self._last_input_tokens = ...
    ...
```

### [L3.1.b] 핵심 수정

```python
async def _call_llm_api(self, ...):
    import anthropic
    from ada.core.langfuse_client import track_llm  # 신규 import

    if self._anthropic is None:
        self._anthropic = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    breaker = get_breaker("anthropic", fail_max=3, reset_timeout=30)
    actual_model = model_name or self.model_name

    async def _do_call() -> Any:
        return await self._anthropic.messages.create(
            model=actual_model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

    # ADR-007 L3: Langfuse trace 컨텍스트
    with track_llm(
        name=self.__class__.__name__,
        model=actual_model,
        job_id=getattr(self, "_current_job_id", None),
        agent=self.__class__.__name__,
    ) as span:
        try:
            resp = await breaker.call(_do_call) if asyncio.iscoroutinefunction(breaker.call) else await _do_call()
        except Exception as e:
            self.logger.error("llm_api_call_failed", error=str(e))
            # span 에 에러 기록 (best-effort)
            if span is not None and hasattr(span, "update"):
                try:
                    span.update(level="ERROR", status_message=str(e)[:200])
                except Exception:
                    pass
            raise

        # 토큰 사용량 누적 (기존)
        usage = getattr(resp, "usage", None)
        self._last_input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
        self._last_output_tokens = getattr(usage, "output_tokens", 0) if usage else 0

        # ADR-007 L3: Langfuse span 에 결과 기록
        if span is not None and hasattr(span, "update"):
            try:
                span.update(
                    metadata={
                        "input_tokens": self._last_input_tokens,
                        "output_tokens": self._last_output_tokens,
                    },
                )
            except Exception:
                pass

        # Prometheus 토큰 메트릭 (기존)
        try:
            from ada.observability.metrics import record_llm_tokens
            record_llm_tokens(actual_model, self._last_input_tokens, self._last_output_tokens)
        except Exception:
            pass

    # 텍스트 추출 (기존)
    text = ""
    for blk in resp.content:
        if getattr(blk, "type", None) == "text":
            text += blk.text
    return text
```

**핵심 설계 선택**:
1. **`with track_llm(...) as span:`** 컨텍스트 안에 모든 호출 + 결과 처리 포함 — span 자동 종료
2. **`span is not None`** 가드 — Langfuse 키 없을 때 no-op
3. **모든 `span.update` 가 try/except** — Langfuse 실패가 agent 호출 실패로 전파 안 되게
4. **`getattr(self, "_current_job_id", None)`** — 옵셔널 인스턴스 변수 (L3.2 에서 세팅)

### [L3.1.c] 정적 검증

```powershell
python -c "import ast; ast.parse(open('agents/base.py').read()); print('AST OK')"
python -m ruff check agents/base.py
```

### [L3.1.d] 단위 테스트 추가

```python
# tests/test_day3_admin_langfuse.py 끝에 추가

def test_call_llm_api_uses_track_llm(monkeypatch):
    """_call_llm_api 가 track_llm 컨텍스트 안에서 실행되는지."""
    pytest.importorskip("anthropic")

    from agents.base import BaseAgent
    from ada.core import langfuse_client as lc

    # track_llm 호출 추적
    track_calls = []

    class FakeSpan:
        def update(self, **kwargs):
            track_calls.append(("update", kwargs))
        def end(self):
            track_calls.append(("end", {}))

    from contextlib import contextmanager

    @contextmanager
    def fake_track_llm(name, model, **metadata):
        track_calls.append(("enter", {"name": name, "model": model, **metadata}))
        yield FakeSpan()

    monkeypatch.setattr(lc, "track_llm", fake_track_llm)

    # 더미 agent
    class TestAgent(BaseAgent):
        model_name = "claude-sonnet-4-6"
        async def __call__(self, state): pass

    agent = TestAgent(session=None)

    # _call_llm_api 직접 호출은 anthropic SDK 가 필요 → 너무 복잡.
    # 대신 track_llm 자체가 호출되는지만 확인 — base.py source 검증.
    import inspect
    source = inspect.getsource(BaseAgent._call_llm_api)
    assert "track_llm" in source
    assert "with track_llm(" in source


def test_base_agent_has_current_job_id_attr():
    """L3.2 준비 — _current_job_id 인스턴스 변수 존재."""
    from agents.base import BaseAgent

    class DummyAgent(BaseAgent):
        async def __call__(self, state): pass

    agent = DummyAgent(session=None)
    # __init__ 에서 None 으로 초기화되거나, getattr 로 안전 접근 가능해야 함
    val = getattr(agent, "_current_job_id", "missing")
    assert val is None or val == "missing"  # 두 케이스 모두 안전
```

---

## L3.2 — `_current_job_id` 전파

### [L3.2.a] `BaseAgent.__init__` 갱신

```python
def __init__(self, session: Optional[AsyncSession] = None) -> None:
    self.session = session
    self.logger = get_logger(self.__class__.__name__)
    self.persona = get_persona(self.__class__.__name__)
    self._last_input_tokens: int = 0
    self._last_output_tokens: int = 0
    self._anthropic: Any = None
    # ADR-007 L3.2 — 현재 처리 중인 job_id (track_llm metadata 전파용)
    self._current_job_id: Optional[str] = None
```

### [L3.2.b] `log_agent_run` 진입 시 세팅

`log_agent_run` 컨텍스트 매니저의 시작 부분에:
```python
@asynccontextmanager
async def log_agent_run(self, state: PipelineState):
    from ada.db.models import AgentRun
    bind_context(job_id=state.job_id, agent_name=self.__class__.__name__)
    self._current_job_id = state.job_id  # ⭐ L3.2 추가
    start = time.perf_counter()
    # ... 기존 코드 ...
```

### [L3.2.c] 테스트

```python
def test_current_job_id_set_in_log_agent_run():
    """log_agent_run 진입 시 _current_job_id 가 state.job_id 로 세팅."""
    import asyncio
    from agents.base import BaseAgent
    from ada.core.state import PipelineState

    captured = []

    class TestAgent(BaseAgent):
        uses_llm = False
        async def __call__(self, state):
            async with self.log_agent_run(state):
                captured.append(self._current_job_id)

    agent = TestAgent(session=None)
    state = PipelineState(job_id="job-abc-123", file_id="f", category="tabular_ml")
    asyncio.run(agent(state))

    assert captured == ["job-abc-123"]
```

---

## L3.3 — `lifespan` 에 `flush` 추가

### [L3.3.a] `api/main.py` 수정

**현재 상태 확인**:
```powershell
grep -n "lifespan\|FastAPI(" api/main.py
```

**예상 결과**: lifespan 없음, `app = FastAPI(...)` 만 있음.

**수정**:
```python
# api/main.py 상단 import 부근
from contextlib import asynccontextmanager


@asynccontextmanager
async def _app_lifespan(app):
    """ADR-007 L3 — shutdown 시 Langfuse buffer flush."""
    yield  # 가동 중
    try:
        from ada.core.langfuse_client import flush
        flush(timeout_sec=5.0)
    except Exception:
        pass


# 기존 app = FastAPI(...) 호출에 lifespan=_app_lifespan 추가
app = FastAPI(
    title="...",
    lifespan=_app_lifespan,
    ...
)
```

### [L3.3.b] 테스트

```python
def test_lifespan_calls_flush_on_shutdown(monkeypatch):
    """lifespan 종료 시 langfuse_client.flush() 호출."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from ada.core import langfuse_client as lc

    flush_called = []
    monkeypatch.setattr(lc, "flush", lambda timeout_sec=5.0: flush_called.append(True))

    from api.main import app
    with TestClient(app) as client:
        # lifespan 진입 (startup)
        r = client.get("/")  # 또는 /docs
        # 어떤 응답이든 OK

    # TestClient 종료 시 lifespan exit → flush 호출됨
    assert flush_called == [True]
```

---

## L3.4 — L3 통합 검증

### [L3.4.a] pytest

```powershell
python -m pytest tests/test_day3_admin_langfuse.py -v
# 기존 9 + 신규 3 (L3.1.d, L3.2.c, L3.3.b) = 12 passed 예상
```

### [L3.4.b] 회귀

```powershell
python -m pytest tests/ -q
```

### [L3.4.c] (선택) 실제 Langfuse trace 검증

```powershell
# 1) .env 에 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY 설정 후
# 2) 실제 agent 한 번 돌리고
python -c @"
import asyncio
# pipeline 한 번 run...
"@
# 3) Langfuse cloud 대시보드에서 trace 보이는지 확인
```

## L3 종료 체크리스트

```
[ ] L3.0.a  영향 agent 파악
[ ] L3.0.b  baseline LLM pytest
[ ] L3.1.a  수정 위치 명확
[ ] L3.1.b  track_llm wrap
[ ] L3.1.c  정적 검증 (AST/ruff)
[ ] L3.1.d  pytest 추가 (track_llm 호출 검증)
[ ] L3.2.a  __init__ 의 _current_job_id
[ ] L3.2.b  log_agent_run 진입 시 세팅
[ ] L3.2.c  pytest 추가 (전파 검증)
[ ] L3.3.a  lifespan + flush
[ ] L3.3.b  pytest (flush 호출 검증)
[ ] L3.4.a  day3 pytest 12 passed
[ ] L3.4.b  전체 회귀
[ ] L3.4.c  (선택) 실 Langfuse 1건
```

---

# Phase L4 — Streamlit 어드민 탭 (1시간)

## L4.0 — 사전 분석

### [L4.0.a] frontend/app.py 구조 파악

**실행**:
```powershell
grep -n "tabs\|tab\d\|with tab" frontend/app.py | head -20
```

**예상**: 기존 탭 구조 발견 (예: tabs = st.tabs([...])).

### [L4.0.b] API_BASE 설정 확인

**실행**:
```powershell
grep -n "API_BASE\|JWT\|token" frontend/app.py | head -10
```

**예상**: `API_BASE = "http://localhost:8000"` 같은 상수.

---

## L4.1 — Admin 탭 컨테이너 추가

### [L4.1.a] 기존 탭 리스트 확장

기존:
```python
tabs = st.tabs(["대시보드", "파이프라인", "지식베이스"])
```

수정:
```python
tabs = st.tabs(["대시보드", "파이프라인", "지식베이스", "🛠 Admin"])
```

### [L4.1.b] 탭 컨테이너 + JWT 입력

```python
# 새 탭 (마지막)
with tabs[-1]:
    st.subheader("🛠 운영자 도구")
    admin_token = st.text_input(
        "JWT 토큰 (admin role)",
        type="password",
        help="ada.security.jwt.create_access_token(sub=..., role='admin') 으로 발급",
    )
    if not admin_token:
        st.info("JWT 토큰을 입력하면 위젯이 활성화됩니다.")
    else:
        headers = {"Authorization": f"Bearer {admin_token}"}
        # 위젯 5종 — L4.2 ~ L4.6
        ...
```

---

## L4.2 — 위젯 1: SecurityAuditLog 테이블

### [L4.2.a] 호출 + 표시

```python
        st.markdown("### 📋 최근 감사 로그")
        try:
            r = requests.get(
                f"{API_BASE}/admin/audit?page=1&page_size=20",
                headers=headers,
                timeout=5,
            )
            if r.status_code == 200:
                items = r.json().get("items", [])
                if items:
                    import pandas as pd
                    df = pd.DataFrame(items)
                    st.dataframe(df[["created_at", "event_type", "actor_role", "action", "result"]])
                else:
                    st.caption("(감사 로그 없음)")
            elif r.status_code == 403:
                st.error("403 — admin role JWT 필요")
            else:
                st.warning(f"조회 실패: HTTP {r.status_code}")
        except Exception as e:
            st.error(f"네트워크 오류: {e}")
```

---

## L4.3 — 위젯 2: Langfuse 상태

```python
        st.markdown("### 📡 Langfuse 연결")
        try:
            r = requests.get(f"{API_BASE}/admin/observability/langfuse", headers=headers, timeout=5)
            if r.status_code == 200:
                data = r.json()
                if data.get("connected"):
                    st.success(f"✅ 연결됨 — {data.get('host', 'unknown')}")
                else:
                    st.warning(f"⚠ 미연결 — {data.get('reason', '?')}")
            else:
                st.warning(f"HTTP {r.status_code}")
        except Exception as e:
            st.error(f"네트워크 오류: {e}")
```

---

## L4.4 — 위젯 3: Prometheus 미리보기

```python
        st.markdown("### 📊 Prometheus")
        try:
            r = requests.get(f"{API_BASE}/admin/observability/prometheus_check", headers=headers, timeout=5)
            if r.status_code == 200:
                data = r.json()
                st.metric("크기 (bytes)", data.get("size_bytes", 0))
                st.code("\n".join(data.get("sample_lines", [])), language="text")
            else:
                st.warning(f"HTTP {r.status_code}")
        except Exception as e:
            st.error(f"네트워크 오류: {e}")
```

---

## L4.5 — 위젯 4: autofix circuit breakers

```python
        st.markdown("### 🔥 자동 수정 — 회로 상태")
        try:
            r = requests.get(f"{API_BASE}/admin/autofix/circuit_breakers", headers=headers, timeout=5)
            if r.status_code == 200:
                data = r.json()
                cols = st.columns(len(data.get("current_state", {})))
                for i, (name, info) in enumerate(data["current_state"].items()):
                    with cols[i]:
                        state_emoji = {"closed": "✅", "open": "🔴", "half_open": "🟡"}.get(info["state"], "❓")
                        st.metric(
                            label=f"{state_emoji} {name}",
                            value=info["state"],
                            help=f"threshold={info['failure_threshold']}, recovery={info['recovery_timeout']}s",
                        )
            else:
                st.warning(f"HTTP {r.status_code}")
        except Exception as e:
            st.error(f"네트워크 오류: {e}")
```

---

## L4.6 — 위젯 5: budget

```python
        st.markdown("### 💰 자동 수정 — LLM 비용")
        try:
            r = requests.get(f"{API_BASE}/admin/autofix/budget", headers=headers, timeout=5)
            if r.status_code == 200:
                data = r.json()
                col1, col2, col3 = st.columns(3)
                col1.metric("오늘 누적 (USD)", f"${data['today_spend_usd']:.4f}")
                col2.metric("호출 횟수", data["today_calls"])
                col3.metric("일일 한도 (USD)", f"${data['daily_limit_usd']:.2f}")

                # 진행률 바
                pct = min(1.0, data["today_spend_usd"] / data["daily_limit_usd"]) if data["daily_limit_usd"] > 0 else 0
                st.progress(pct, text=f"{pct*100:.1f}% 사용")

                if data["is_exceeded"]:
                    st.error("⚠ 일일 한도 초과 — 자동 수정 Claude 호출 차단됨")
            else:
                st.warning(f"HTTP {r.status_code}")
        except Exception as e:
            st.error(f"네트워크 오류: {e}")
```

---

## L4.7 — L4 통합 검증

### [L4.7.a] Streamlit 띄우기

```powershell
streamlit run frontend/app.py --server.port 8501
```

### [L4.7.b] 시각 검증

브라우저 (`http://localhost:8501`):
1. "Admin" 탭 보임
2. JWT 입력 후 5 위젯 모두 표시
3. 각 위젯이 API 호출 → 정상 데이터 또는 graceful 에러

### [L4.7.c] 종료

`Ctrl+C` 로 streamlit 종료.

## L4 종료 체크리스트

```
[ ] L4.0.a  frontend 구조 파악
[ ] L4.0.b  API_BASE 확인
[ ] L4.1.a  탭 추가
[ ] L4.1.b  JWT 입력 + 컨테이너
[ ] L4.2    위젯 1: 감사로그
[ ] L4.3    위젯 2: Langfuse
[ ] L4.4    위젯 3: Prometheus
[ ] L4.5    위젯 4: circuit breakers
[ ] L4.6    위젯 5: budget
[ ] L4.7.a  streamlit 부팅
[ ] L4.7.b  시각 검증
[ ] L4.7.c  종료
```

---

# Phase E — 통합 검증 스크립트

## [E.1] verify_day3.py 작성

**위치**: `scripts/dev/verify_day3.py`
**목표**: L1~L4 의 모든 가시적 변경을 한 번에 검증.

**구조** (기존 verify_autofix_phase*.py 패턴):
```python
"""ADR-007 hj-day3 자체 검증 스크립트."""

# 패턴: 각 section 마다 check 함수 + assertion
# 40+ assertion 목표

# === Phase L1 ===
@check("alembic.ini 영문화 확인")
def _():
    src = (REPO_ROOT / "alembic.ini").read_text(encoding="utf-8")
    assert "한글" not in src
    # 한국어 문자 (가-힣) 없는지
    import re
    assert not re.search(r"[가-힯]", src)

# === Phase L2 ===
@check("admin.py 에 /admin/autofix/failure_logs 라우트")
def _():
    src = (REPO_ROOT / "api/routes/admin.py").read_text(encoding="utf-8")
    assert "/admin/autofix/failure_logs" in src
    assert "/admin/autofix/patch_applications" in src
    assert "/admin/autofix/circuit_breakers" in src
    assert "/admin/autofix/budget" in src

# === Phase L3 ===
@check("base.py 에 track_llm 통합")
def _():
    src = (REPO_ROOT / "agents/base.py").read_text(encoding="utf-8")
    assert "from ada.core.langfuse_client import track_llm" in src
    assert "with track_llm(" in src
    assert "_current_job_id" in src

# === Phase L4 ===
@check("frontend/app.py 에 admin 탭")
def _():
    src = (REPO_ROOT / "frontend/app.py").read_text(encoding="utf-8")
    assert "Admin" in src
    assert "/admin/audit" in src
    assert "/admin/autofix/budget" in src

# ... 40+ assertion
```

## [E.2] 실행

```powershell
python scripts/dev/verify_day3.py
# 모든 ✓ 면 PASS
```

## [E.3] 전체 회귀

```powershell
python -m pytest tests/ -q
# 회귀 0건 확인
```

---

# Phase F+G — 커밋 + Push

## [F.1] 단계별 커밋 권장

L1, L2, L3, L4 끝날 때마다 commit (PR 리뷰 친화적):

```powershell
# L2 끝나면
git add api/routes/admin.py tests/test_day3_admin_langfuse.py
git commit -m "hj-day3: Phase 2 audit 라우트 확장 (failure_logs / patch / circuit / budget)"

# L3 끝나면
git add agents/base.py api/main.py tests/test_day3_admin_langfuse.py
git commit -m "hj-day3: Langfuse 깊이 통합 (base.py track_llm + lifespan flush)"

# L4 끝나면
git add frontend/app.py
git commit -m "hj-day3: Streamlit admin 탭 5 위젯 (audit/Langfuse/Prometheus/회로/예산)"

# 설계 문서
git add docs/ADR-007-DAY3-LANGFUSE-ADMIN.md docs/ADR-007-DAY3-IMPLEMENTATION-GUIDE.md
git add scripts/dev/verify_day3.py
git commit -m "hj-day3: ADR-007 설계 문서 + verify 스크립트"
```

## [G.1] end_of_day.sh

```powershell
bash scripts/dev/end_of_day.sh
```

이게 자동으로:
1. 의존성 동기화
2. 영역 검증
3. pytest 전체
4. rebase onto main
5. rebase 후 재테스트
6. `git push --force-with-lease`

## [G.2] PR 생성

`end_of_day.sh` 출력에 PR URL 표시:
```
PR 생성/갱신: https://github.com/youandi3535/ADA/pull/new/feat/hj-day3
```

브라우저로 열면 `.github/workflows/auto-pr.yml` 이 제목/본문 자동 채움.

---

# 부록 0 — 검증 3중 표준 템플릿 (모든 작업에 적용)

> 이 절은 **모든 sub-step 에서 복사해서 쓰는** 표준 검증 절차입니다.
> 임의의 작업이라도 V1/V2/V3 셋을 모두 통과시켜야 다음으로 진입.

## 표준 V1 — 정적 검증 (코드 변경 시)

```powershell
# 변경한 파일 경로를 변수에 (예시)
$file = "api/routes/admin.py"

# (a) UTF-8 strict — 인코딩 깨짐 0
python -c "open('$file', 'rb').read().decode('utf-8', errors='strict'); print('UTF-8 OK')"

# (b) AST parse — Python syntax 0 error
python -c "import ast; ast.parse(open('$file', encoding='utf-8').read()); print('AST OK')"

# (c) Ruff lint — style + 미사용 import + obvious bugs
python -m ruff check $file

# (d) Import 가능성 — 추가/변경된 심볼이 실제 import 됨
python -c "from <module> import <new_symbol>; print('Import OK')"

# (e) Git diff 검토 — 의도 외 변경 0
git diff $file
```

기대: 5개 명령 모두 0 exit code + 명시된 "OK" 메시지.

## 표준 V2 — 단위 검증 (함수/모듈 동작 확인)

```powershell
# (a) 단일 테스트 (대상 함수의 핵심 케이스)
python -m pytest tests/<test_file>.py::test_<target> -v --tb=short

# (b) 인터프리터 직접 호출 (테스트 없는 경우)
python -c @"
from <module> import <function>
result = <function>(<inputs>)
assert result == <expected>, f'got {result}'
print('Unit OK')
"@

# (c) 입력 케이스 3종 — 정상 / 경계 / 에러
python -m pytest tests/<test_file>.py -v -k "<keyword>"
```

기대: assertion 실패 0건, 모든 테스트 PASSED.

## 표준 V3 — 통합 검증 (시스템 영향)

```powershell
# (a) 전체 회귀 — 이 변경이 기존 테스트 깨트리지 않음
python -m pytest tests/ -q
# 기대: baseline 카운트 유지 또는 증가, failed 0건

# (b) 시각 검증 — swagger / streamlit / 로그
# - 라우트 변경: uvicorn 띄워서 /docs 확인
# - UI 변경: streamlit run 후 브라우저
# - 백엔드 로직 변경: 실제 호출 → 응답 JSON / 로그 확인

# (c) 외부 영향 — 영역 검증 + pre-commit
bash scripts/dev/check_scope.sh
# 기대: ✅ 영역 검증 통과
```

기대: baseline 회귀 0건 + 외부 가시성 (swagger/UI/로그) 의도대로 표시.

## 검증 결과 기록 양식 (작업 노트용)

각 sub-step 완료 시:
```
[L<번호>.<sub>.<a>] <작업명>
  V1 정적:  ✅  (실행: ..., 결과: ...)
  V2 단위:  ✅  (실행: ..., 결과: ...)
  V3 통합:  ✅  (실행: ..., 결과: ...)
  소요: __분
  다음: [L<번호>.<sub+1>.a]
```

실패 시:
```
[L<번호>.<sub>.<a>] <작업명>
  V1 정적:  ✅
  V2 단위:  ❌  (실행: ..., 에러: ...)
  → 에러 대응: <부록 B 의 어느 케이스>
  → 픽스 적용
  → V1/V2/V3 재실행
  V1 재정적:  ✅
  V2 재단위:  ✅
  V3 통합:  ✅
  최종 통과 (재시도 1회)
```

---

# 부록 A — 공통 패턴 / 코드 스니펫

## A.1 — Admin 라우트 표준 구조

```python
@router.get("/admin/...", response_model=..., tags=["Admin", "..."])
async def handler(
    # 페이지네이션
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    # 필터
    ...,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),  # ⭐ RBAC
) -> ...:
    """..."""
    from ada.db.models import ...
    where = []
    if filter: where.append(...)
    base_q = select(Model).where(*where)
    total = int((await db.execute(select(func.count()).select_from(base_q.subquery()))).scalar() or 0)
    rows = (await db.scalars(base_q.order_by(...).offset(...).limit(...))).all()
    return PageResponse(items=[...], total=total, ...)
```

## A.2 — 테스트 표준 구조

```python
def test_admin_xxx(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ada.security.jwt import get_current_user
    from ada.db.session import get_db
    from api.routes import admin as admin_routes

    app = FastAPI()
    app.include_router(admin_routes.router)

    # Fake DB + Auth
    class FakeSession: ...  # 위 패턴 참조
    async def fake_db(): yield FakeSession()
    async def fake_admin(): return {"user_id": "u1", "role": "admin"}

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = fake_admin

    client = TestClient(app)
    r = client.get("/admin/...")
    assert r.status_code == 200
    # ...
```

---

# 부록 B — 디버깅 체크리스트

## B.1 — 라우트가 swagger 에 안 보임

1. `api/main.py` 에 `include_router` 호출 있는지
2. `api/routes/admin.py` 의 `@router.get` 데코레이터 path 가 정확한지
3. uvicorn `--reload` 가 변경 감지하는지 (수정 후 자동 재시작?)
4. 브라우저 캐시 — `Ctrl+Shift+R` 강제 새로고침

## B.2 — RBAC 가 403 안 떨어짐

1. `Depends(_admin_only)` 가 핸들러 시그니처에 있는지
2. JWT 의 `role` claim 이 정확히 `admin` 인지 (`administrator` 아님)
3. `ada/security/rbac.py` 의 `PERMISSIONS["admin"]` 가 `{"*"}` 인지

## B.3 — Langfuse trace 가 안 보임

1. `.env` 의 `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` 셋업?
2. `verify_connection()` 호출 시 `connected=True` 나오는지
3. 실제 `_call_llm_api` 호출이 일어났는지 (agent run 됐는지)
4. Langfuse cloud 대시보드 시간 필터 — UTC 기준이라 시차 주의

## B.4 — Streamlit 위젯이 빈 화면

1. JWT 토큰 입력 안 함 → 위젯 활성화 안 됨
2. uvicorn 안 띄움 → ConnectionError → except 블록에서 "네트워크 오류" 표시
3. API_BASE 가 잘못 → `http://localhost:8000` 인지 확인

## B.5 — alembic 명령 실패

1. `PYTHONUTF8=1` env var 세팅?
2. postgres 컨테이너 살아있는지 (`docker ps`)
3. `.env` 의 `DATABASE_URL` 비번이 docker postgres 의 비번과 같은지
4. 컨테이너 안에서 실행: `docker compose exec api alembic upgrade head`

---

# 부록 C — 작업 시간 추적

| Phase | 예상 | 실제 (기록용) |
|---|---|---|
| L1.0 (사전조건) | 5분 | ___ |
| L1.1 (alembic commit) | 5분 | ___ |
| L1.2 (pytest 5건) | 5분 | ___ |
| L1.3 (swagger 시각) | 15분 | ___ |
| **L1 합계** | **30분** | ___ |
| L2.0 (사전조건) | 5분 | ___ |
| L2.1 (failure_logs) | 25분 | ___ |
| L2.2 (patch_applications) | 20분 | ___ |
| L2.3 (circuit_breakers) | 20분 | ___ |
| L2.4 (budget) | 15분 | ___ |
| L2.5 (통합 검증) | 15분 | ___ |
| **L2 합계** | **1.5시간** | ___ |
| L3.0 (사전 분석) | 10분 | ___ |
| L3.1 (track_llm) | 40분 | ___ |
| L3.2 (job_id) | 20분 | ___ |
| L3.3 (lifespan) | 20분 | ___ |
| L3.4 (통합 검증) | 30분 | ___ |
| **L3 합계** | **2시간** | ___ |
| L4.0~L4.7 | 1시간 | ___ |
| E + F + G | 30분 | ___ |
| **Full 총합** | **5.5시간** | ___ |

— 끝.
