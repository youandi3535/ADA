# ADR-008 hj-day4 — 상세 구현 가이드 (Step-by-Step Implementation Guide)

> **본 문서 사용법**: ADR-008 (high-level 설계) 의 각 작업을 sub-step 단위로 쪼개서
> "복사 → 실행 → 검증 (3중)" 순으로 진행하면 누수 없이 완성되도록 작성.
> 각 sub-step 마다 **사전조건 / 입력 / 실행 / 예상출력 / 검증 3중 (V1 정적+V2 단위+V3 통합) / 에러 대응 / 다음 단계 진입 조건** 포함.
>
> **읽는 법**: `[L1.1.a]` 같은 식별자가 모든 단계에 부여됨. 진행 중 막히면 식별자 알려주시면 그 단계만 디버깅 가능.
>
> **Contract Day 주의**: Day 4 는 CLAUDE.md §5 의 Contract Day. 본 가이드의 모든 commit 머지 후 CS/NY/jh 가 `git rebase origin/main` 필요. Phase H 의 공지 템플릿 사용.

---

## ⭐ 검증 3중 (Three-Fold Verification) — 모든 sub-step 의무 적용

> **원칙**: 어떤 변경이든 다음 3종을 **모두 통과**해야 다음 sub-step 으로 진입.
> 하나라도 실패하면 → 에러 대응 → 픽스 → 실패한 V 부터 V3 까지 재검증.

### V1 — 정적 검증 (Static)
**무엇**: 코드를 실행하지 않고 구조·문법·import 만 확인.
- `python -c "import ast; ast.parse(open(<file>).read())"` — AST 파싱
- `python -m ruff check <file>` — lint
- `python -c "from <module> import <symbol>"` — import 가능성
- 파일 인코딩 strict UTF-8 디코드
- diff 검토 — 의도한 변경 외 다른 변경 없는지

**언제 통과**: 0 syntax error, 0 import error, 0 ruff error.

### V2 — 단위 검증 (Unit)
**무엇**: 변경된 함수/모듈을 실제로 호출해서 입출력 확인. Mock 활용.
- `pytest tests/test_xxx.py::test_specific -v` — 단일 테스트
- 또는 인터프리터 직접 호출 (`python -c`)
- 입력 케이스 최소 3종: 정상 / 경계 / 에러
- 결과 dict/list 의 key/length 검증

**언제 통과**: 의도한 출력 = 실제 출력 (assertion 통과).

### V3 — 통합 검증 (Integration)
**무엇**: 실제 시스템에 적용했을 때 옆 모듈과 함께 동작하는지.
- `pytest tests/ -q` — 전체 회귀
- carrier 가 실제 PII 가 섞인 state 받아도 결과에 raw PII 가 안 보이는지 (수동 또는 통합 테스트)
- 다른 sub-step 의 결과물과 함께 호출 (예: SecurityGuard 가 mapping 채우고, carrier 가 reattach)
- 통합 영향: 이 변경이 다른 모듈의 동작을 깨트리지 않는지

**언제 통과**: 회귀 0건 AND PII 가 final output 에 노출 0건.

### 적용 표시 규칙
각 sub-step 의 "검증" 섹션은 다음 형태로 명시:
```
**검증 3중**:
- V1 정적: <구체 명령>  → 기대: <결과>
- V2 단위: <구체 명령>  → 기대: <결과>
- V3 통합: <구체 명령>  → 기대: <결과>

V1/V2/V3 중 하나라도 실패 → "에러 대응" 절로.
```

---

## 📑 목차

- [Phase L1 — 검증/회귀 (필수, 30분)](#phase-l1--검증회귀-필수-30분)
- [Phase L2 — Output Carrier reattach (권장, 1.5시간)](#phase-l2--output-carrier-reattach-권장-15시간)
- [Phase L3 — 패턴 정리 + DataFrame 마스킹 (선택, 2시간)](#phase-l3--패턴-정리--dataframe-마스킹-선택-2시간)
- [Phase L4 — 어드민 PII 위젯 (선택, 1시간)](#phase-l4--어드민-pii-위젯-선택-1시간)
- [Phase E — 통합 검증 스크립트](#phase-e--통합-검증-스크립트)
- [Phase F+G+H — 커밋 + Push + 팀 공지](#phase-fgh--커밋--push--팀-공지)
- [부록 0 — 검증 3중 표준 템플릿](#부록-0--검증-3중-표준-템플릿)
- [부록 A — 공통 패턴 / 코드 스니펫](#부록-a--공통-패턴--코드-스니펫)
- [부록 B — 디버깅 체크리스트](#부록-b--디버깅-체크리스트)
- [부록 C — 작업 시간 추적](#부록-c--작업-시간-추적)
- [부록 D — Contract Day 팀 공지 템플릿](#부록-d--contract-day-팀-공지-템플릿)

---

# Phase L1 — 검증/회귀 (필수, 30분)

## L1.0 — Phase 진입 전 사전조건

### [L1.0.a] 작업 디렉토리·브랜치·venv 확인

**목적**: hj-day4 작업이 올바른 환경에서 시작되는지 보장.

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
feat/hj-day4
(빈 줄 또는 변경 없음)
```

**검증 3중**:
- **V1 정적**: `git rev-parse --git-dir` → 기대: `.git`
- **V2 단위**: `git config --get user.email` → 기대: 본인 이메일 (commit author 정확성)
- **V3 통합**: `git log --oneline -3` → 기대: hj-day3 의 최근 commit 3개 노출 (브랜치 정상 fetch)

**에러 대응**:
| 증상 | 원인 | 대응 |
|---|---|---|
| 브랜치명이 `feat/hj-day3` | 새 브랜치 안 만듦 | `git checkout main && git pull && git checkout -b feat/hj-day4` |
| 변경 파일 다수 | 이전 작업 미커밋 | `git stash` 로 임시 보관 후 진행 |
| venv 활성화 실패 | venv 없음 | `python -m venv venv` 후 재시도 |

**다음 단계 진입 조건**: 브랜치 = `feat/hj-day4` AND venv 활성화 OK.

---

### [L1.0.b] 기존 테스트 베이스라인 측정

**목적**: hj-day4 변경 전 회귀 비교용 baseline.

**실행**:
```powershell
$env:PYTHONUTF8="1"
python -m pytest tests/ -q --no-header 2>&1 | Select-Object -Last 5
```

**예상 출력**: `XXX passed, X skipped` (hj-day3 완료 시점 기준 약 340+).

**검증**:
1. `failed` 항목 0건 (실패 있으면 hj-day4 시작 전 fix 필요)
2. `skipped` 5건 내외 = 정상 (환경 의존)

**에러 대응**: pytest 실패 → `python -m pytest tests/<failed_test>.py -v --tb=short` 로 원인 파악 후 fix.

**다음 단계 진입 조건**: 0 failed.

---

### [L1.0.c] Day 4 변경 대상 파일 4종 존재 확인

**목적**: 본 가이드가 가정하는 파일들이 실제로 있는지.

**실행**:
```powershell
Test-Path ada\security\guardrails.py, agents\security_guard.py, tests\test_day4_pii_anonymize.py, agents\insight.py
```

**예상 출력**: 4개 모두 `True`.

**에러 대응**: 누락 시 → 이전 hj 작업 commit 누락 → `git log -- ada/security/guardrails.py` 로 마지막 변경 확인.

**다음 단계 진입 조건**: 4개 모두 존재.

---

## L1.1 — Day 4 pytest 6건 그린 확인

### [L1.1.a] 단일 파일 실행

**목적**: ADR-008 §2 의 DoD 1차 충족 — 기존 6 케이스가 회귀 없이 통과.

**실행**:
```powershell
$env:PYTHONUTF8="1"
python -m pytest tests/test_day4_pii_anonymize.py -v
```

**예상 출력**:
```
collected 6 items

tests/test_day4_pii_anonymize.py::test_detect_and_anonymize_df PASSED                   [ 16%]
tests/test_day4_pii_anonymize.py::test_anonymize_text_deterministic PASSED              [ 33%]
tests/test_day4_pii_anonymize.py::test_reattach_masks_to_stars PASSED                   [ 50%]
tests/test_day4_pii_anonymize.py::test_reattach_blocks_self_generated_pii PASSED        [ 66%]
tests/test_day4_pii_anonymize.py::test_security_guard_stores_pii_mapping PASSED         [ 83%]
tests/test_day4_pii_anonymize.py::test_injection_blocked_by_guard PASSED                [100%]

============== 6 passed in 1.xx s ==============
```

**검증 3중**:

**V1 정적** — 테스트 파일 무결성
```powershell
python -c "import ast; ast.parse(open('tests/test_day4_pii_anonymize.py').read()); print('AST OK')"
python -m ruff check tests/test_day4_pii_anonymize.py
```
기대: `AST OK` + `All checks passed!`

**V2 단위** — 6 케이스 통과
```powershell
python -m pytest tests/test_day4_pii_anonymize.py -v --tb=short
```
기대: `6 passed`, 각 PASSED 라인, 실행 시간 < 3초.

**V3 통합** — 다른 테스트와 회귀
```powershell
python -m pytest tests/ -q 2>&1 | Select-String -Pattern "passed|failed" | Select-Object -Last 3
```
기대: baseline 카운트 유지 또는 증가, failed 0건.

**3중 모두 PASS → 다음 진입.** 하나라도 실패 → 아래 에러 대응.

**에러 대응 (실패별)**:

| 실패 테스트 | 추정 원인 | 해결 |
|---|---|---|
| `test_detect_and_anonymize_df` | pandas 미설치 | `pip install pandas==2.2.2` |
| `test_anonymize_text_deterministic` | hashlib 결과 차이 (불가) | 코드 변형 의심, `git diff ada/security/guardrails.py` |
| `test_reattach_masks_to_stars` | `<PII:` 토큰 형식 변경 | `_token()` 함수 시그니처 확인 |
| `test_reattach_blocks_self_generated_pii` | 정규식 안전망 미동작 | `reattach()` 마지막 for loop 확인 |
| `test_security_guard_stores_pii_mapping` | SecurityGuardAgent.__call__ 동작 변경 | `agents/security_guard.py:65-92` 확인 |
| `test_injection_blocked_by_guard` | INJECTION_PATTERNS 변경 | `agents/security_guard.py:22-30` 확인 |

**다음 단계 진입 조건**: 6/6 passed.

---

### [L1.1.b] InsightAgent 의 Day 4 hook 회귀 확인

**목적**: `agents/insight.py:126-135` 의 reattach hook 이 Day 8 가드 테스트와 충돌 안 하는지.

**실행**:
```powershell
python -m pytest tests/test_day8_insight_guard.py -v
```

**예상 출력**: 모든 케이스 passed (현재 6~10건 정도).

**검증 3중**:
- **V1 정적**: `python -c "from agents.insight import InsightAgent; print('Import OK')"` → `Import OK`
- **V2 단위**: 위 pytest passed
- **V3 통합**: `python -m pytest tests/test_day4_pii_anonymize.py tests/test_day8_insight_guard.py -v` 동시 실행 시 회귀 0

**에러 대응**:
- import 에러 → `agents/insight.py` 의 `from agents.security_guard import SecurityGuardAgent` 순환 import 확인
- Day 8 가드 위반 → reattach 가 텍스트의 한국어를 깨트렸는지 (현재 `_token()` 은 영문 `<PII:...>` 만 생성하므로 안전)

**다음 단계 진입 조건**: Day 4 + Day 8 모두 회귀 0.

---

## L1.2 — 그래프 통합 경로 정적 검증 (3중 grep)

### [L1.2.a] V1 — SecurityGuardAgent 가 mapping 을 `_pii` 키로 저장하는지

**실행**:
```powershell
findstr /N "_pii" agents\security_guard.py
```

**예상 출력** (line 71 부근):
```
71:                extras["_pii"] = {
72:                    "mapping": mapping,
```

**검증**: line 71 의 `extras["_pii"]` 가 존재.

**에러 대응**: 없으면 `agents/security_guard.py:60~75` 가 변형됨. `git log -p agents/security_guard.py` 로 원인 추적.

---

### [L1.2.b] V2 — InsightAgent 가 동일 키로 mapping 을 읽는지

**실행**:
```powershell
findstr /N "_pii" agents\insight.py
```

**예상 출력** (line 128 부근):
```
128:                pii_meta = (state.category_extras or {}).get("_pii") or {}
```

**검증**: `_pii` 키로 mapping 조회.

---

### [L1.2.c] V3 — 그래프 노드 순서 (SecurityGuardAgent → ... → InsightAgent)

**실행**:
```powershell
findstr /N "security_guard\|SecurityGuard\|insight" orchestrator\graph.py
```

**예상 출력**: SecurityGuardAgent 가 InsightAgent 의 선행 노드여야 mapping 이 채워짐.

**검증**: grep 결과의 add_node 순서에서 security_guard 가 insight 앞에 있는지 (또는 supervisor 가 security_guard 를 먼저 호출).

**에러 대응**: 순서가 잘못이면 → mapping 이 비어있는 채로 InsightAgent 가 도착 → reattach no-op → DoD 미충족. `orchestrator/graph.py` 수정 (HJ 영역).

**다음 단계 진입 조건**: 3개 grep 모두 의도된 패턴 발견.

---

## L1.3 — Mini 옵션 종료 결정

### [L1.3.a] 진행 선택

이 시점에서 두 가지 선택:

| 옵션 | 추가 작업 | 효과 |
|---|---|---|
| **Mini 종료** | 본 ADR + ADR-008-IMPLEMENTATION-GUIDE.md commit 후 push | 공식 DoD 충족 (Insight 경로만 reattach) |
| **Standard 진행** | L2 진행 (carrier 5종 reattach) | carrier 산출물 안전성 100% |

**권장**: Standard (L2 까지) — Mini 는 carrier 단에서 토큰 잔존 위험이 남음.

---

## L1 종료 체크리스트

```
[ ] L1.0.a  브랜치 = feat/hj-day4, venv 활성화
[ ] L1.0.b  baseline pytest 0 failed
[ ] L1.0.c  Day 4 파일 4종 존재
[ ] L1.1.a  Day 4 pytest 6/6 passed ⭐ DoD 1차
[ ] L1.1.b  Day 8 회귀 없음
[ ] L1.2.a  V1: SecurityGuard 가 _pii 저장
[ ] L1.2.b  V2: Insight 가 _pii 조회
[ ] L1.2.c  V3: 그래프 노드 순서
[ ] L1.3.a  Mini vs Standard 선택
```

**L1 PASS 시점**: L1.2.c 완료. 여기서 Mini 옵션 선택 가능.

---

# Phase L2 — Output Carrier reattach (권장, 1.5시간)

## L2.0 — Phase 진입 전 사전조건

### [L2.0.a] L1 완료 확인

**검증**: L1 종료 체크리스트 모두 ✓.

### [L2.0.b] carrier 5종 현황 파악

**목적**: 어느 carrier 가 `state` 인자를 이미 받는지, 어느 carrier 가 시그니처 변경 필요한지.

**실행**:
```powershell
findstr /N "def generate" outputs\pdf.py outputs\ppt.py outputs\markdown_insight.py outputs\html_dashboard.py outputs\script.py
```

**예상 출력**:
```
outputs\pdf.py:27:    def generate(   ... state: Any = None,  ← Day 9 hook 있음
outputs\ppt.py:38:    def generate(   ... state: Any = None,  ← Day 9 hook 있음
outputs\markdown_insight.py:13:    def generate(self, *, insights: str, ...  ← state 없음
outputs\html_dashboard.py:15:    def generate(self, *, insights: str, ...    ← state 없음
outputs\script.py:13:    def generate(self, *, insights: str, ...            ← state 없음
```

**검증**: 5 carrier 중 2개 (pdf, ppt) 는 시그니처 변경 불필요, 3개 (md, html, script) 는 `state=None` 인자 추가 필요.

**다음 단계 진입 조건**: 5개 모두 식별됨.

---

### [L2.0.c] report_composer 의 carrier 호출 패턴 확인

**실행**:
```powershell
findstr /N "gen.generate\|state=state\|state.with_update" agents\report_composer.py
```

**예상 출력** (line 49-57):
```
49:                    path = await asyncio.to_thread(
50:                        gen.generate,
51:                        insights=state.insights or "",
... (state 인자 전달 안 함)
```

**검증**: 현재 `gen.generate(...)` 호출이 `state=state` 를 안 넘김 → L2 에서 추가 필요.

**다음 단계 진입 조건**: 패턴 확인.

---

## L2.1 — `outputs/base.py` 에 `reattach_pii` 헬퍼 추가

### [L2.1.a] 헬퍼 함수 설계

**위치**: `outputs/base.py` 의 마지막 (line 194 뒤). `OutputGenerator` 클래스 외부에 모듈 함수로.

**설계 결정**:
- **모듈 함수 (not 메서드)** — carrier 가 `OutputGenerator` 상속 안 해도 (테스트 fixture 등) 호출 가능
- **state=None 안전** — fixture/단위테스트에서 mapping 없이도 호출
- **`PIIAnonymizer().reattach()` 위임** — DRY, 정규식 안전망 + mapping 치환 둘 다 보장
- **모든 예외 흡수** — carrier 가 보안 모듈 부재로 죽지 않게

### [L2.1.b] 코드 작성

**위치**: `outputs/base.py` (line 194 뒤).

**작성 내용**:

```python
# ==============================================================
# ADR-008 L2 — PII Re-attach (사용자 노출 직전 마스킹)
# ==============================================================
#
# carrier 가 사용자에게 텍스트를 노출하기 직전 본 함수를 통과시킨다.
# - state.category_extras['_pii']['mapping'] 의 토큰을 *** 로 치환
# - PIIAnonymizer.reattach() 가 정규식 안전망도 적용 (LLM 자체 generate PII)
# - state=None 이거나 mapping 비어있어도 정규식 안전망은 작동
# - 보안 모듈 import 실패 시에도 carrier 가 죽지 않게 silent passthrough
#
# R-103 (PII 로그 출력 금지) 의 최종 게이트.
# ==============================================================


def reattach_pii(state: "PipelineState | None", text: str | None) -> str:
    """LLM 응답 / 사용자 인텐트 등 사용자 노출 직전 텍스트의 PII 를 ``***`` 로 치환.

    Args:
        state: 현재 파이프라인 state. None 이어도 동작.
        text: 마스킹 대상. None/빈 문자열은 빈 문자열 반환.

    Returns:
        PII 가 제거된 안전한 텍스트.
    """
    if not text:
        return text or ""
    try:
        from ada.security.guardrails import PIIAnonymizer
    except Exception:
        return text  # 보안 모듈 부재 → carrier 보존 우선

    mapping: dict[str, str] = {}
    if state is not None:
        try:
            pii_meta = (getattr(state, "category_extras", None) or {}).get("_pii") or {}
            mapping = pii_meta.get("mapping") or {}
        except Exception:
            mapping = {}

    try:
        return PIIAnonymizer().reattach(text, mapping)
    except Exception:
        return text  # reattach 자체가 죽어도 carrier 보존
```

### [L2.1.c] 검증 3중

**V1 정적**:
```powershell
python -c "import ast; ast.parse(open('outputs/base.py').read()); print('AST OK')"
python -m ruff check outputs/base.py
python -c "from outputs.base import reattach_pii; print('Import OK')"
```
기대: `AST OK` + `All checks passed` + `Import OK`.

**V2 단위** — 인터프리터 직접 호출:
```powershell
$env:PYTHONUTF8="1"
python -c @"
from outputs.base import reattach_pii

# 케이스 1 — state=None, 정규식 안전망만
out = reattach_pii(None, 'email: me@x.com')
assert 'me@x.com' not in out, f'PII 노출: {out}'
assert '***' in out, f'마스킹 없음: {out}'
print('Case 1 OK:', out)

# 케이스 2 — mapping 있음
class FakeState:
    category_extras = {'_pii': {'mapping': {'<PII:email:abc12345>': 'me@x.com'}}}
out2 = reattach_pii(FakeState(), 'contact <PII:email:abc12345>')
assert 'me@x.com' not in out2 and '<PII:' not in out2 and '***' in out2
print('Case 2 OK:', out2)

# 케이스 3 — 빈 입력
assert reattach_pii(None, '') == ''
assert reattach_pii(None, None) == ''
print('Case 3 OK')
"@
```
기대: 3개 케이스 모두 OK.

**V3 통합**: 회귀
```powershell
python -m pytest tests/ -q
```
기대: baseline 유지.

**에러 대응**:
- `ImportError: PipelineState` → string annotation 사용 — `"PipelineState | None"` 처럼 quote 가 있어야 (작성 코드에 이미 quote 사용)
- ruff `unused import` → `TYPE_CHECKING` 이미 base.py 상단에 있음 — 새로 추가하지 말 것

**다음 단계 진입 조건**: 3중 모두 PASS.

---

### [L2.1.d] 단위 테스트 신규 파일 생성

**위치**: `tests/test_day4_carrier_reattach.py` (신규).

**작성 내용** (헬퍼 검증 2건):

```python
"""Day 4 — Output Carrier reattach 통합 테스트 (ADR-008 L2)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


# ----- 1) reattach_pii 헬퍼 — state=None ---------------------------------------
def test_reattach_pii_helper_with_empty_state():
    """state 가 None 이어도 정규식 안전망이 작동."""
    from outputs.base import reattach_pii

    text = "고객 이메일: customer@example.com, 전화: 010-1234-5678"
    safe = reattach_pii(None, text)
    assert "customer@example.com" not in safe
    assert "010-1234-5678" not in safe
    assert "***" in safe


# ----- 2) reattach_pii 헬퍼 — mapping 있음 -------------------------------------
def test_reattach_pii_helper_with_mapping():
    """state.category_extras['_pii'].mapping 의 토큰이 *** 로 치환."""
    from outputs.base import reattach_pii

    state = SimpleNamespace(
        category_extras={
            "_pii": {
                "mapping": {"<PII:email:abc12345>": "real@user.com"},
                "redaction": "***",
            }
        }
    )
    text = "사용자 <PII:email:abc12345> 로 연락"
    safe = reattach_pii(state, text)
    assert "<PII:" not in safe
    assert "real@user.com" not in safe
    assert "***" in safe


# ----- 3) reattach_pii — 빈 입력 안전 처리 -------------------------------------
def test_reattach_pii_helper_handles_empty_inputs():
    from outputs.base import reattach_pii

    assert reattach_pii(None, None) == ""
    assert reattach_pii(None, "") == ""
    state = SimpleNamespace(category_extras=None)
    assert reattach_pii(state, "") == ""
```

### [L2.1.e] 단위 테스트 실행

**실행**:
```powershell
python -m pytest tests/test_day4_carrier_reattach.py -v
```

**예상 출력**:
```
collected 3 items

tests/test_day4_carrier_reattach.py::test_reattach_pii_helper_with_empty_state PASSED
tests/test_day4_carrier_reattach.py::test_reattach_pii_helper_with_mapping PASSED
tests/test_day4_carrier_reattach.py::test_reattach_pii_helper_handles_empty_inputs PASSED

============== 3 passed ==============
```

**다음 단계 진입 조건**: 3 passed.

---

## L2.2 — Carrier 5종 wiring

### [L2.2.a] `outputs/markdown_insight.py` 변경

**위치**: `outputs/markdown_insight.py` (현 38줄).

**변경 사항**:
1. `generate()` 시그니처에 `state: Any = None` 추가
2. 함수 시작부에 `insights`, `user_intent`, `eval_result.rationale` 3 필드 마스킹

**Before** (line 13-15):
```python
def generate(self, *, insights: str, best_model: dict[str, Any],
             eda_charts: list[str], category: str, user_intent: str,
             eval_result: dict[str, Any] | None) -> str:
```

**After**:
```python
def generate(self, *, insights: str, best_model: dict[str, Any],
             eda_charts: list[str], category: str, user_intent: str,
             eval_result: dict[str, Any] | None,
             state: Any = None) -> str:
    # ADR-008 L2 — 사용자 노출 직전 PII 마스킹
    from outputs.base import reattach_pii
    insights = reattach_pii(state, insights)
    user_intent = reattach_pii(state, user_intent)
    if eval_result:
        eval_result = {**eval_result, "rationale": reattach_pii(state, eval_result.get("rationale"))}
```

**검증 3중**:

**V1 정적**:
```powershell
python -c "import ast; ast.parse(open('outputs/markdown_insight.py').read()); print('AST OK')"
python -m ruff check outputs/markdown_insight.py
python -c "from outputs.markdown_insight import InsightSummaryGenerator; print('Import OK')"
```

**V2 단위**:
```powershell
python -c @"
from types import SimpleNamespace
from outputs.markdown_insight import InsightSummaryGenerator
from unittest.mock import patch

state = SimpleNamespace(
    category_extras={'_pii': {'mapping': {'<PII:email:abc12345>': 'me@x.com'}}}
)
gen = InsightSummaryGenerator('job-test')
# upload 차단
with patch.object(gen, '_upload', return_value='s3://test/path.md'), \
     patch.object(gen, '_tmp', return_value='./_test_md.tmp'):
    path = gen.generate(
        insights='연락처: me@x.com 입니다',
        best_model={'model_name': 'xgb'},
        eda_charts=[],
        category='tabular_ml',
        user_intent='내 메일 <PII:email:abc12345> 사용',
        eval_result={'passed': True, 'rationale': 'phone 010-1234-5678'},
        state=state,
    )

content = open('./_test_md.tmp', encoding='utf-8').read()
assert 'me@x.com' not in content, f'PII 노출:\n{content}'
assert '<PII:' not in content, f'토큰 잔존:\n{content}'
assert '010-1234-5678' not in content, f'phone 노출:\n{content}'
assert '***' in content
print('OK')
"@
```
기대: `OK` 출력.

**V3 통합**: `python -m pytest tests/test_day4_carrier_reattach.py -v` (다음 단계에 통합 테스트 추가 예정).

**에러 대응**:
- `state` 시그니처 변경으로 기존 호출자 깨짐 → 기본값 `None` 이라 호환됨. `report_composer.py` 의 `gen.generate(...)` 가 state 안 넘겨도 OK.

**다음 단계 진입 조건**: V1/V2 PASS.

---

### [L2.2.b] `outputs/pdf.py` 변경

**위치**: `outputs/pdf.py` line 27~37.

**현재 상태**: 이미 `state: Any = None` 인자가 있음 (Day 9 hook). 따라서 시그니처 변경 불필요. 마스킹 코드만 추가.

**변경 위치**: `def generate(...) -> str:` 진입 직후 (theme 계산 전):

```python
def generate(
    self,
    *,
    insights: str,
    best_model: dict[str, Any],
    eda_charts: list[str],
    category: str,
    user_intent: str,
    eval_result: dict[str, Any] | None,
    state: Any = None,
) -> str:
    # ADR-008 L2 — PII 마스킹 (사용자 노출 직전)
    from outputs.base import reattach_pii
    insights = reattach_pii(state, insights)
    user_intent = reattach_pii(state, user_intent)
    if eval_result:
        eval_result = {**eval_result, "rationale": reattach_pii(state, eval_result.get("rationale"))}

    from reportlab.lib import colors
    ...  # 기존 코드 유지
```

**검증 3중**:

**V1 정적**:
```powershell
python -c "import ast; ast.parse(open('outputs/pdf.py').read()); print('AST OK')"
python -m ruff check outputs/pdf.py
```

**V2 단위**: reportlab mock 어려움. 대신 `inspect.getsource` 정적 검증:
```powershell
python -c @"
import inspect
from outputs.pdf import PDFReportGenerator
src = inspect.getsource(PDFReportGenerator.generate)
assert 'reattach_pii' in src, 'reattach_pii 호출 없음'
assert 'insights = reattach_pii(state, insights)' in src
print('OK')
"@
```

**V3 통합**: 다음 carrier 들 완료 후 통합 pytest.

**에러 대응**:
- import 누락 → `from outputs.base import reattach_pii` 가 generate() 함수 안 또는 모듈 상단 둘 다 가능. 모듈 상단 권장 (반복 호출 시 import overhead 0).

**다음 단계 진입 조건**: V1/V2 PASS.

---

### [L2.2.c] `outputs/ppt.py` 변경

**위치**: `outputs/ppt.py` line 38~48.

**현재 상태**: 이미 `state: Any = None` 인자 있음. 마스킹 코드만 추가.

**변경**: pdf 와 동일한 패턴.

```python
def generate(
    self,
    *,
    insights: str,
    best_model: dict[str, Any],
    eda_charts: list[str],
    category: str,
    user_intent: str,
    eval_result: dict[str, Any] | None,
    state: Any = None,
) -> str:
    # ADR-008 L2 — PII 마스킹
    from outputs.base import reattach_pii
    insights = reattach_pii(state, insights)
    user_intent = reattach_pii(state, user_intent)
    if eval_result:
        eval_result = {**eval_result, "rationale": reattach_pii(state, eval_result.get("rationale"))}

    from pptx import Presentation
    ...  # 기존 코드
```

**검증 3중**: pdf 와 동일 패턴.

**다음 단계 진입 조건**: V1/V2 PASS.

---

### [L2.2.d] `outputs/html_dashboard.py` 변경

**위치**: `outputs/html_dashboard.py` line 15~17.

**변경 사항**: 시그니처에 `state: Any = None` 추가 + 마스킹.

**Before** (line 15-17):
```python
def generate(self, *, insights: str, best_model: dict[str, Any],
             eda_charts: list[str], category: str, user_intent: str,
             eval_result: dict[str, Any] | None) -> str:
```

**After**:
```python
def generate(self, *, insights: str, best_model: dict[str, Any],
             eda_charts: list[str], category: str, user_intent: str,
             eval_result: dict[str, Any] | None,
             state: Any = None) -> str:
    # ADR-008 L2 — PII 마스킹
    from outputs.base import reattach_pii
    insights = reattach_pii(state, insights)
    user_intent = reattach_pii(state, user_intent)
    if eval_result:
        eval_result = {**eval_result, "rationale": reattach_pii(state, eval_result.get("rationale"))}
```

**검증 3중**: markdown_insight 와 동일 패턴.

---

### [L2.2.e] `outputs/script.py` 변경

**위치**: `outputs/script.py` line 13~15.

**변경 사항**: 시그니처 + `user_intent`, `insights` 마스킹 (eval_result.rationale 사용 안 함).

```python
def generate(self, *, insights: str, best_model: dict[str, Any],
             eda_charts: list[str], category: str, user_intent: str,
             eval_result: dict[str, Any] | None,
             state: Any = None) -> str:
    # ADR-008 L2 — PII 마스킹
    from outputs.base import reattach_pii
    insights = reattach_pii(state, insights)
    user_intent = reattach_pii(state, user_intent)

    bm = best_model or {}
    ...
```

**검증 3중**:

**V1 정적**:
```powershell
python -c "import ast; ast.parse(open('outputs/script.py').read()); print('AST OK')"
python -m ruff check outputs/script.py
```

**V2 단위**: 다음 단계에 통합.

---

### [L2.2.f] `outputs/__init__.py` 변경 (선택)

`outputs` 패키지가 `reattach_pii` 를 외부 노출하면 future-proof:

```python
# outputs/__init__.py 의 __all__ 또는 re-export 에 추가
from outputs.base import reattach_pii  # noqa: F401
```

**검증**: `python -c "from outputs import reattach_pii; print('OK')"` → `OK`.

**선택 사항** — 안 해도 carrier 단에서 `from outputs.base import reattach_pii` 로 충분.

---

## L2.3 — `report_composer.py` 가 state 전달하도록 변경

### [L2.3.a] 변경 위치 파악

**파일**: `agents/report_composer.py` line 49-57.

**Before**:
```python
async def _gen(code: str) -> tuple[str, str | None]:
    try:
        gen_cls = GENERATORS.get(code)
        if gen_cls is None:
            return code, None
        gen = gen_cls(state.job_id)
        path = await asyncio.to_thread(
            gen.generate,
            insights=state.insights or "",
            best_model=state.best_model or {},
            eda_charts=state.eda_charts,
            category=state.category,
            user_intent=state.user_intent or state.user_question or "",
            eval_result=state.eval_result,
        )
        return code, path
```

### [L2.3.b] 변경 적용

**After**:
```python
async def _gen(code: str) -> tuple[str, str | None]:
    try:
        gen_cls = GENERATORS.get(code)
        if gen_cls is None:
            return code, None
        gen = gen_cls(state.job_id)
        # ADR-008 L2 — state 전달 (carrier 가 _pii mapping 으로 reattach)
        kwargs: dict[str, Any] = dict(
            insights=state.insights or "",
            best_model=state.best_model or {},
            eda_charts=state.eda_charts,
            category=state.category,
            user_intent=state.user_intent or state.user_question or "",
            eval_result=state.eval_result,
        )
        # state 인자를 받는 carrier 에만 전달 (하위 호환)
        try:
            import inspect
            if "state" in inspect.signature(gen.generate).parameters:
                kwargs["state"] = state
        except Exception:
            pass

        path = await asyncio.to_thread(gen.generate, **kwargs)
        return code, path
```

**핵심 설계 선택**:
1. **inspect 기반 호환**: 외부에서 추가될 수 있는 generator (예: 사용자 custom) 가 `state` 인자를 안 받아도 깨지지 않음
2. **try/except 흡수**: inspect 자체 실패도 carrier 호출은 진행

**더 단순한 대안** (모든 carrier 가 state 받게 통일됐다면):
```python
path = await asyncio.to_thread(
    gen.generate,
    insights=...,
    ...,
    state=state,  # 모든 carrier 가 받음
)
```

L2.2 에서 5 carrier 모두 `state: Any = None` 추가했으므로 이 단순 버전도 OK. **단순 버전 권장** — inspect 오버헤드 제거.

### [L2.3.c] 검증 3중

**V1 정적**:
```powershell
python -c "import ast; ast.parse(open('agents/report_composer.py').read()); print('AST OK')"
python -m ruff check agents/report_composer.py
```

**V2 단위**:
```powershell
python -c @"
import inspect
from agents.report_composer import ReportComposerAgent
src = inspect.getsource(ReportComposerAgent.__call__)
assert 'state=state' in src or 'kwargs[\"state\"]' in src, 'state 전달 코드 없음'
print('OK')
"@
```

**V3 통합**: 신규 pytest 추가 (다음 단계).

**다음 단계 진입 조건**: V1/V2 PASS.

---

## L2.4 — 통합 단위 테스트 (4 carrier × 1 케이스 + report_composer 1 케이스)

### [L2.4.a] `tests/test_day4_carrier_reattach.py` 확장

**추가 케이스**:

```python
# ----- 4) markdown_insight — insights/user_intent 마스킹 -----------------------
def test_markdown_insight_redacts_pii(tmp_path):
    """OUT-07 markdown 출력에 raw PII 가 노출 안 됨."""
    from types import SimpleNamespace
    from unittest.mock import patch

    from outputs.markdown_insight import InsightSummaryGenerator

    state = SimpleNamespace(
        category_extras={"_pii": {"mapping": {"<PII:email:abc12345>": "me@x.com"}}}
    )
    gen = InsightSummaryGenerator("job-md-test")
    tmp_file = str(tmp_path / "out.md")

    with patch.object(gen, "_upload", return_value="s3://test/out.md"), \
         patch.object(gen, "_tmp", return_value=tmp_file):
        gen.generate(
            insights="연락처: me@x.com",
            best_model={"model_name": "xgb"},
            eda_charts=[],
            category="tabular_ml",
            user_intent="<PII:email:abc12345> 사용자",
            eval_result={"passed": True, "rationale": "phone 010-1234-5678"},
            state=state,
        )

    content = open(tmp_file, encoding="utf-8").read()
    assert "me@x.com" not in content
    assert "<PII:" not in content
    assert "010-1234-5678" not in content
    assert "***" in content


# ----- 5) script — user_intent / insights 마스킹 -----------------------------
def test_script_redacts_pii(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import patch

    from outputs.script import ScriptGenerator

    state = SimpleNamespace(category_extras={"_pii": {"mapping": {}}})
    gen = ScriptGenerator("job-script-test")
    tmp_file = str(tmp_path / "out.txt")

    with patch.object(gen, "_upload", return_value="s3://test/out.txt"), \
         patch.object(gen, "_tmp", return_value=tmp_file):
        gen.generate(
            insights="고객 a@b.com 분석",
            best_model={"model_name": "lgb", "metrics": {"acc": 0.9}},
            eda_charts=[],
            category="tabular_ml",
            user_intent="010-9999-8888",
            eval_result={"passed": True},
            state=state,
        )

    content = open(tmp_file, encoding="utf-8").read()
    assert "a@b.com" not in content
    assert "010-9999-8888" not in content
    assert "***" in content


# ----- 6) html_dashboard — insights 마스킹 -----------------------------------
def test_html_dashboard_redacts_pii(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import patch

    pytest.importorskip("base64")
    from outputs.html_dashboard import DashboardArtifactGenerator

    state = SimpleNamespace(category_extras={"_pii": {"mapping": {}}})
    gen = DashboardArtifactGenerator("job-html-test")
    tmp_file = str(tmp_path / "out.html")

    with patch.object(gen, "_upload", return_value="s3://test/out.html"), \
         patch.object(gen, "_tmp", return_value=tmp_file):
        gen.generate(
            insights="이메일 leak@danger.com 위험",
            best_model={"model_name": "iso"},
            eda_charts=[],
            category="anomaly_detection",
            user_intent="check 010-7777-6666",
            eval_result=None,
            state=state,
        )

    content = open(tmp_file, encoding="utf-8").read()
    assert "leak@danger.com" not in content
    assert "010-7777-6666" not in content
    assert "***" in content


# ----- 7) report_composer — state 를 carrier 에 전달 --------------------------
def test_report_composer_passes_state_to_carrier():
    """state 가 carrier.generate() 에 전달되는 정적 검증."""
    import inspect
    from agents.report_composer import ReportComposerAgent
    src = inspect.getsource(ReportComposerAgent.__call__)
    assert "state=state" in src or 'kwargs["state"]' in src
```

### [L2.4.b] 신규 6 케이스 실행

**실행**:
```powershell
python -m pytest tests/test_day4_carrier_reattach.py -v
```

**예상 출력**: `7 passed` (L2.1.d 의 3건 + 위 4건).

**검증 3중**:
- **V1 정적**: 위 명령
- **V2 단위**: 7 passed
- **V3 통합**: `python -m pytest tests/ -q` 회귀 0

**에러 대응**:
- `_upload` mock 안 됨 → `unittest.mock.patch.object` 사용 확인
- `_tmp` 가 `NamedTemporaryFile` 사용해서 OS 별 차이 → `tmp_path` fixture 사용 권장 (위 코드에 적용)
- html_dashboard 의 MinIO 호출 실패 → 정상 (try/except 흡수). 빈 charts 로 진행

**다음 단계 진입 조건**: 7 passed + 회귀 0.

---

## L2.5 — Standard 옵션 종료 결정

이 시점에서 L1 + L2 완료. ADR-008 §8 의 **Standard 옵션 종료** 가능.

| 옵션 | 추가 작업 | 효과 |
|---|---|---|
| **Standard 종료** | F.1/F.2 commit → end_of_day.sh | DoD 100% — carrier 5종 모두 안전 |
| **Full 진행** | L3 진행 (패턴 정리 + df 마스킹) | 운영 완성도 ↑ |

**권장**: Full 까지 — L3 의 df 마스킹이 jh 의 tabular 학습 안정성에 영향.

---

## L2 종료 체크리스트

```
[ ] L2.0.a  L1 완료
[ ] L2.0.b  carrier 5종 시그니처 파악 (pdf/ppt 있음 / md/html/script 없음)
[ ] L2.0.c  report_composer 호출 패턴 확인
[ ] L2.1.a  reattach_pii 헬퍼 설계
[ ] L2.1.b  outputs/base.py 코드 작성
[ ] L2.1.c  V1/V2/V3 검증
[ ] L2.1.d  tests/test_day4_carrier_reattach.py 신규 (3 케이스)
[ ] L2.1.e  3 passed
[ ] L2.2.a  markdown_insight 변경
[ ] L2.2.b  pdf 변경
[ ] L2.2.c  ppt 변경
[ ] L2.2.d  html_dashboard 변경
[ ] L2.2.e  script 변경
[ ] L2.2.f  (선택) __init__ re-export
[ ] L2.3.a  report_composer 변경 위치 파악
[ ] L2.3.b  state 전달 적용
[ ] L2.3.c  V1/V2 검증
[ ] L2.4.a  pytest 4건 추가
[ ] L2.4.b  7 passed + 회귀 0 ⭐ DoD 완전 충족
[ ] L2.5    Standard vs Full 선택
```

**L2 PASS 시점**: L2.4.b 완료. DoD 의 "결과 페이지에 \*\*\*" 가 carrier 5종 모두 통과.

---

# Phase L3 — 패턴 정리 + DataFrame 마스킹 (선택, 2시간)

## L3.0 — 사전 분석

### [L3.0.a] redactor vs guardrails 패턴 diff

**목적**: 두 모듈의 PII 패턴 중복도 파악.

**실행**:
```powershell
findstr /N "EMAIL_RE\|PHONE_RE\|CARD_RE\|RRN_RE\|^EMAIL\|^PHONE\|^CARD\|^RRN" ada\security\guardrails.py ada\error_handler\redactor.py
```

**예상 출력**:
- `ada/security/guardrails.py`: 4 패턴 (EMAIL/PHONE/CARD/RRN)
- `ada/error_handler/redactor.py`: 20+ 패턴 (위 4개 + URI/JWT/Stripe/GitHub/AWS/PEM/MAC/IP/PATH 등)

**검증**: 두 모듈이 EMAIL/PHONE/CARD/RRN 의 정규식 정의를 각자 가지고 있음.

**다음 단계 진입 조건**: 패턴 차이 파악.

---

### [L3.0.b] redactor.py 호출처 파악

**실행**:
```powershell
findstr /N "from ada.error_handler.redactor\|redact(" ada agents tests
```

**예상 출력**: `auto_handler.py`, `agents/auto_error_handler.py` 등 5개 내외.

**검증**: 호출처 모두 list — L3.2 적용 시 깨지지 않을 보호 대상 확인.

---

### [L3.0.c] guardrails.PIIAnonymizer 호출처 파악

**실행**:
```powershell
findstr /N "from ada.security.guardrails\|PIIAnonymizer" ada agents outputs tests
```

**예상 출력**: `security_guard.py`, `insight.py`, `outputs/base.py` (L2 추가), `tests/test_day4_*.py`.

**검증**: 5개 내외 호출처. import 경로 통일성 확인.

---

## L3.1 — 의도 분리 docstring 추가 (15분, 가장 안전)

### [L3.1.a] `redactor.py` 상단 docstring 보강

**위치**: `ada/error_handler/redactor.py` line 1~26 (모듈 docstring).

**추가할 문구** (기존 docstring 뒤):

```python
"""... (기존 내용) ...

⚠️  의도 분리 — ada.security.guardrails.PIIAnonymizer 와의 차이:
    redact()          : **일방향**. mapping 미보존. 디버깅성 우선.
                        패턴 20+ (CARD/RRN/JWT/Stripe/AWS/PEM 등).
                        → 사용처: 에러 로그 / Ollama 프롬프트 / FailureLog 저장.
    PIIAnonymizer     : **양방향**. mapping 보존 → reattach() 가능.
                        패턴 4 (email/phone/card/rrn).
                        → 사용처: 사용자 인텐트 LLM 호출 → 응답에서 원본 위치 *** 로 복원.

    두 모듈을 통합하면 PIIAnonymizer.reattach() 가 깨진다 (mapping 키가 일반 토큰으로
    바뀌면서 결정성 손실). ADR-008 §4 의 결정 — 통합하지 않고 의도 분리 명시.

    공유 가능한 정규식 (EMAIL/PHONE/CARD/RRN) 은 ada.security._pii_patterns 에 두고
    양쪽이 import 한다 (L3.2 작업).
"""
```

### [L3.1.b] `guardrails.py` 상단 docstring 보강

**위치**: `ada/security/guardrails.py` line 1~16.

**추가할 문구**:

```python
"""... (기존 내용) ...

⚠️  의도 분리 — ada.error_handler.redactor 와의 차이:
    PIIAnonymizer     : **양방향** (본 파일). reattach 가능.
                        용도: LLM 응답을 사용자에 노출하기 전 *** 마스킹.
    ada.error_handler.redactor.redact() : **일방향**. mapping 미보존.
                        용도: 에러 로그 / 자동 패치 프롬프트.

    통합하지 말 것 — ADR-008 §4 의 결정.
    공유 정규식은 ada.security._pii_patterns 모듈 (L3.2).
"""
```

### [L3.1.c] 검증 3중

**V1 정적**:
```powershell
python -c "import ast; ast.parse(open('ada/error_handler/redactor.py').read())"
python -c "import ast; ast.parse(open('ada/security/guardrails.py').read())"
python -m ruff check ada/error_handler/redactor.py ada/security/guardrails.py
```

**V2 단위**: 문구 존재 확인
```powershell
findstr /C:"의도 분리" ada\error_handler\redactor.py ada\security\guardrails.py
```
기대: 두 파일 모두에서 매칭.

**V3 통합**:
```powershell
python -m pytest tests/test_day4_pii_anonymize.py tests/test_autofix_phase2_redactor.py -v
```
기대: 양쪽 모두 회귀 0.

**다음 단계 진입 조건**: 3중 PASS. **L3.1 만으로도 단독 적용 가능 (15분, 가장 안전)**.

---

## L3.2 — 공유 `_pii_patterns.py` 모듈 추출 (45분, 권장)

### [L3.2.a] `ada/security/_pii_patterns.py` 신규 작성

**위치**: `ada/security/_pii_patterns.py` (신규).

**핵심 설계**:
- 외부 의존성 0 (stdlib `re` 만)
- 패턴 정의만, 치환 정책 없음 (호출자가 결정)
- private 모듈 (`_` prefix) — 외부 사용자 직접 import 비권장

```python
"""ada.security._pii_patterns — 공유 PII 정규식 (LOW-LEVEL, internal).

ada.security.guardrails.PIIAnonymizer 와 ada.error_handler.redactor 양쪽이
공통으로 사용하는 4개 핵심 PII 패턴. 패턴만 정의 — 치환 정책 (mapping 유무) 은
각 호출자가 결정한다.

⚠️ 본 모듈은 외부 사용자가 직접 import 하지 말 것 (private). 진실 원천 (single
   source of truth) 통합을 위한 내부 모듈.
"""

from __future__ import annotations

import re

# ----- 4 공통 PII 패턴 (양 호출자 공유) -----
# 이메일
EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")

# 한국 휴대전화 (010-xxxx-xxxx, 010xxxxxxxx, +82-10-... 등)
PHONE_KR_RE = re.compile(r"\b01\d-?\d{3,4}-?\d{4}\b")

# 한국 주민등록번호 (6자리-7자리)
RRN_RE = re.compile(r"\b\d{6}-\d{7}\b")

# 신용카드 (4-4-4-4, 하이픈/공백 무관)
CARD_RE = re.compile(r"\b\d{4}-?\d{4}-?\d{4}-?\d{4}\b")


# 호출자 친화적 묶음 (kind, pattern) — guardrails.PII_PATTERNS 와 같은 시그니처
COMMON_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", EMAIL_RE),
    ("rrn", RRN_RE),
    ("phone", PHONE_KR_RE),
    ("card", CARD_RE),
)


__all__ = [
    "EMAIL_RE",
    "PHONE_KR_RE",
    "RRN_RE",
    "CARD_RE",
    "COMMON_PATTERNS",
]
```

### [L3.2.b] `guardrails.py` 가 `_pii_patterns` 사용하도록 변경

**위치**: `ada/security/guardrails.py` line 23~35.

**Before**:
```python
RRN_RE = re.compile(r"\b\d{6}-\d{7}\b")
PHONE_RE = re.compile(r"\b01\d-?\d{3,4}-?\d{4}\b")
EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
CARD_RE = re.compile(r"\b\d{4}-?\d{4}-?\d{4}-?\d{4}\b")

PII_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("email", EMAIL_RE),
    ("rrn", RRN_RE),
    ("phone", PHONE_RE),
    ("card", CARD_RE),
)
```

**After**:
```python
# 공유 정규식은 _pii_patterns 모듈에 위치 (ADR-008 L3.2)
from ada.security._pii_patterns import (
    CARD_RE,
    COMMON_PATTERNS as PII_PATTERNS,
    EMAIL_RE,
    PHONE_KR_RE as PHONE_RE,
    RRN_RE,
)
# 하위 호환 — 기존 호출자가 EMAIL_RE 직접 import 했어도 동작
```

**검증 3중**:

**V1 정적**:
```powershell
python -c "import ast; ast.parse(open('ada/security/guardrails.py').read())"
python -m ruff check ada/security/guardrails.py
python -c "from ada.security.guardrails import PII_PATTERNS, EMAIL_RE, PHONE_RE, RRN_RE, CARD_RE; print('OK')"
```

**V2 단위**:
```powershell
python -c @"
from ada.security.guardrails import PIIAnonymizer
a = PIIAnonymizer()
out, m = a.anonymize_text('email a@b.com phone 010-1234-5678 rrn 990101-1234567 card 1234-5678-9012-3456')
assert 'a@b.com' not in out
assert '010-1234-5678' not in out
assert '990101-1234567' not in out
assert '1234-5678-9012-3456' not in out
assert len(m) == 4, f'mapping len={len(m)}'
print('OK')
"@
```

**V3 통합**:
```powershell
python -m pytest tests/test_day4_pii_anonymize.py -v
```
기대: 6 passed (회귀 0).

---

### [L3.2.c] `redactor.py` 가 `_pii_patterns` 사용하도록 변경

**위치**: `ada/error_handler/redactor.py` line 153-171 (EMAIL/PHONE 부분).

**Before**:
```python
# 이메일
(
    re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "<EMAIL>",
    "EMAIL",
),
# 한국 휴대전화
(
    re.compile(r"\b(?:\+?82[-\s.]?|0)1[016789][-\s.]?\d{3,4}[-\s.]?\d{4}\b"),
    "<PHONE>",
    "PHONE",
),
```

**After**:
```python
# 이메일 (공유 패턴 — ada.security._pii_patterns)
(
    EMAIL_RE,
    "<EMAIL>",
    "EMAIL",
),
# 한국 휴대전화 (공유 패턴)
(
    PHONE_KR_RE,
    "<PHONE>",
    "PHONE",
),
```

**상단 import 추가**:
```python
from ada.security._pii_patterns import (
    CARD_RE,
    EMAIL_RE,
    PHONE_KR_RE,
    RRN_RE,
)
```

**주의**:
- redactor 는 `\b[\w.+-]+@[\w-]+\.[\w.-]+\b` 와 _pii_patterns 의 `[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+` 가 정확히 같지는 않음 (`\w` vs `[a-zA-Z0-9_]`, 끝 boundary 차이). **하지만 실용적 매칭 결과는 동일**. 안전을 위해 redactor 의 기존 패턴을 `_pii_patterns` 의 표준으로 통일.
- CARD/RRN 도 비슷하게 통일.
- 한국 휴대전화는 redactor 의 `\b(?:\+?82[-\s.]?|0)1[016789][-\s.]?\d{3,4}[-\s.]?\d{4}\b` 가 더 광역 (+82, .구분자). 단순 통일하면 매칭 범위 축소 → redactor 회귀 위험. **결정**: 한국 휴대전화는 `_pii_patterns` 의 패턴을 _pii_patterns 측에서 redactor 의 광역 패턴으로 교체 → guardrails 도 광역 패턴 사용.

**`_pii_patterns.py` 의 PHONE 패턴 보강** (L3.2.a 의 수정):
```python
# 광역 한국 휴대전화 — redactor 의 기존 패턴을 표준으로
PHONE_KR_RE = re.compile(r"\b(?:\+?82[-\s.]?|0)1[016789][-\s.]?\d{3,4}[-\s.]?\d{4}\b")
```

**검증 3중**:

**V1 정적**:
```powershell
python -c "import ast; ast.parse(open('ada/error_handler/redactor.py').read())"
python -m ruff check ada/error_handler/redactor.py
```

**V2 단위**:
```powershell
python -m pytest tests/test_autofix_phase2_redactor.py -v
```
기대: 회귀 0.

**V3 통합**:
```powershell
python -m pytest tests/test_day4_pii_anonymize.py tests/test_autofix_phase2_redactor.py -v
```
기대: 양쪽 모두 회귀 0.

**에러 대응**:
- 패턴 변경으로 매칭 결과 달라짐 → `_pii_patterns` 의 정규식을 더 광역 / 더 좁게 조정. 기존 테스트가 진실의 원천.
- redactor 의 다른 19 패턴은 그대로 유지 (CARD/RRN/EMAIL/PHONE 4개만 공유).

**다음 단계 진입 조건**: 양 모듈 회귀 0.

---

### [L3.2.d] L3.2 종료 commit (단독 가능)

L3.2 만 단독 적용 가능 (L3.3 안 해도 OK):

```powershell
git add ada/security/_pii_patterns.py ada/security/guardrails.py ada/error_handler/redactor.py
git commit -m "hj-day4 L3.2: 공유 PII 패턴 추출 (_pii_patterns 모듈) — 진실 원천 단일화"
```

---

## L3.3 — DataFrame 업로드 단계 마스킹 (1시간)

### [L3.3.a] `data_profiler.py` 변경 위치

**파일**: `agents/data_profiler.py` line 30~52.

**변경 지점**: line 33 (df 로드 직후) ↔ line 41 (basic profile 호출 전) 사이에 마스킹 hook 추가.

### [L3.3.b] 코드 작성

**Before** (line 30-52):
```python
async def __call__(self, state: PipelineState) -> PipelineState:
    async with self.log_agent_run(state):
        try:
            df = load_dataframe_from_state(state)
        except Exception as e:
            return state.with_update(
                error=f"파일 로딩 실패: {e}",
                validation={"is_valid": False, "errors": [str(e)], "warnings": []},
                next_agent="error_recovery",
            )

        profile = basic_dataframe_profile(df, target_column=state.target_column)

        handler = get_handler(state.category, "profile")
        if handler is not None:
            try:
                extra = handler(df, state)
                if isinstance(extra, dict):
                    profile.update(extra)
            except Exception as e:
                self.logger.warning("profiler_handler_failed", category=state.category, error=str(e))

        return state.with_update(data_profile=profile, next_agent="schema_validator")
```

**After**:
```python
async def __call__(self, state: PipelineState) -> PipelineState:
    async with self.log_agent_run(state):
        try:
            df = load_dataframe_from_state(state)
        except Exception as e:
            return state.with_update(
                error=f"파일 로딩 실패: {e}",
                validation={"is_valid": False, "errors": [str(e)], "warnings": []},
                next_agent="error_recovery",
            )

        # ADR-008 L3.3 — 업로드 DataFrame 의 PII 컬럼 자동 마스킹
        # detect_pii_columns 가 식별한 컬럼만 마스킹 + mapping 을 state.category_extras['_pii'] 에 merge
        df, pii_extras = _anonymize_uploaded_df(df, state)

        profile = basic_dataframe_profile(df, target_column=state.target_column)

        handler = get_handler(state.category, "profile")
        if handler is not None:
            try:
                extra = handler(df, state)
                if isinstance(extra, dict):
                    profile.update(extra)
            except Exception as e:
                self.logger.warning("profiler_handler_failed", category=state.category, error=str(e))

        # _pii merge — 기존 텍스트 mapping 보존 + df mapping 추가 + 감지 컬럼 노출
        merged_extras = _merge_pii_extras(state.category_extras, pii_extras)
        return state.with_update(
            data_profile=profile,
            category_extras=merged_extras,
            next_agent="schema_validator",
        )


# ==============================================================
# 헬퍼 — 모듈 레벨 (테스트 용이성)
# ==============================================================


def _anonymize_uploaded_df(df: Any, state: PipelineState) -> tuple[Any, dict[str, Any]]:
    """업로드 df 의 PII 컬럼 자동 마스킹.

    Returns:
        (마스킹된 df, extras={"mapping": {...}, "columns": [...]})
    """
    try:
        from ada.security.guardrails import PIIAnonymizer
    except Exception:
        return df, {}
    try:
        anon = PIIAnonymizer()
        cols = anon.detect_pii_columns(df)
        if not cols:
            return df, {}
        masked_df, mapping = anon.anonymize_df(df, pii_columns=cols)
        return masked_df, {"mapping": mapping, "columns": cols}
    except Exception:
        return df, {}


def _merge_pii_extras(
    current_extras: dict[str, Any] | None, new_pii: dict[str, Any]
) -> dict[str, Any]:
    """state.category_extras 에 새 PII mapping/columns 를 merge.

    기존 _pii 키 보존 (텍스트 마스킹으로 채워진 mapping) + 새 df mapping 추가.
    """
    extras = dict(current_extras or {})
    if not new_pii:
        return extras
    existing = extras.get("_pii") or {}
    merged_mapping = {**(existing.get("mapping") or {}), **(new_pii.get("mapping") or {})}
    extras["_pii"] = {
        **existing,
        "mapping": merged_mapping,
        "df_columns": new_pii.get("columns") or [],
        "redaction": existing.get("redaction") or "***",
    }
    return extras
```

**핵심 설계 선택**:
1. **헬퍼 모듈 함수 분리**: `_anonymize_uploaded_df`, `_merge_pii_extras` → 단위 테스트 용이
2. **모든 예외 흡수**: PIIAnonymizer 부재/예외 시 df 그대로 진행 (회귀 위험 최소화)
3. **`df_columns` 노출**: 핸들러 (jh) 가 PII 컬럼을 인지하고 feature 후보에서 제외 가능
4. **기존 mapping 보존**: SecurityGuardAgent 가 채운 텍스트 mapping 도 함께 사용 가능

### [L3.3.c] 단위 테스트

**위치**: `tests/test_day4_carrier_reattach.py` (이미 있는 파일) 끝.

```python
# ----- 8) data_profiler — DataFrame PII 컬럼 자동 마스킹 ---------------------
def test_data_profiler_anonymizes_df_columns():
    """업로드 df 의 email/phone 컬럼이 마스킹됨."""
    import pandas as pd
    from agents.data_profiler import _anonymize_uploaded_df

    df = pd.DataFrame({
        "email": ["a@b.com", "c@d.com"],
        "phone": ["010-1111-2222", "010-3333-4444"],
        "age": [30, 40],
    })

    class FakeState:
        category_extras: dict = {}

    masked, extras = _anonymize_uploaded_df(df, FakeState())

    # df 의 PII 컬럼 마스킹됨
    assert "a@b.com" not in masked["email"].astype(str).tolist()
    assert "010-1111-2222" not in masked["phone"].astype(str).tolist()
    # age 는 unchanged
    assert masked["age"].tolist() == [30, 40]
    # extras 에 mapping + columns
    assert "mapping" in extras
    assert "email" in extras["columns"]
    assert "phone" in extras["columns"]
    assert "age" not in extras["columns"]


# ----- 9) data_profiler — extras merge -------------------------------------
def test_data_profiler_merges_pii_extras():
    """기존 _pii (텍스트 mapping) + df mapping 이 함께 보존."""
    from agents.data_profiler import _merge_pii_extras

    current = {
        "_pii": {"mapping": {"<PII:email:abc>": "from_text@a.com"}, "redaction": "***"}
    }
    new = {
        "mapping": {"<PII:email:xyz>": "from_df@b.com"},
        "columns": ["email"],
    }

    merged = _merge_pii_extras(current, new)
    assert "<PII:email:abc>" in merged["_pii"]["mapping"]
    assert "<PII:email:xyz>" in merged["_pii"]["mapping"]
    assert merged["_pii"]["df_columns"] == ["email"]
    assert merged["_pii"]["redaction"] == "***"
```

### [L3.3.d] 검증 3중

**V1 정적**:
```powershell
python -c "import ast; ast.parse(open('agents/data_profiler.py').read())"
python -m ruff check agents/data_profiler.py
python -c "from agents.data_profiler import DataProfilerAgent, _anonymize_uploaded_df, _merge_pii_extras; print('OK')"
```

**V2 단위**:
```powershell
python -m pytest tests/test_day4_carrier_reattach.py::test_data_profiler_anonymizes_df_columns tests/test_day4_carrier_reattach.py::test_data_profiler_merges_pii_extras -v
```
기대: 2 passed.

**V3 통합**:
```powershell
python -m pytest tests/ -q
```
기대: 회귀 0. **핸들러 테스트** (`tests/handlers/`) 가 PII 컬럼을 가진 fixture 안 쓰는지 확인 — 만약 쓰면 handler 가 마스킹된 df 받아도 OK 한지 검증.

**에러 대응**:
- 핸들러 회귀 (jh 영역) → PII 컬럼이 모델 feature 였던 경우. 해결: 핸들러가 `state.category_extras['_pii']['df_columns']` 를 보고 해당 컬럼 자동 제외 (jh 협의 필요. Contract Day 안내문에 명시)
- `load_dataframe_from_state` 부재 → import 경로 확인

**다음 단계 진입 조건**: 회귀 0 + 2 신규 passed.

---

## L3 종료 체크리스트

```
[ ] L3.0.a  redactor vs guardrails 패턴 diff 파악
[ ] L3.0.b  redactor 호출처 파악
[ ] L3.0.c  guardrails 호출처 파악
[ ] L3.1.a  redactor.py docstring 의도 분리
[ ] L3.1.b  guardrails.py docstring 의도 분리
[ ] L3.1.c  V1/V2/V3 검증
[ ] L3.2.a  _pii_patterns.py 신규 작성
[ ] L3.2.b  guardrails.py import 교체
[ ] L3.2.c  redactor.py import 교체
[ ] L3.2.d  L3.2 commit (단독 가능)
[ ] L3.3.a  data_profiler.py 변경 위치
[ ] L3.3.b  _anonymize_uploaded_df + _merge_pii_extras 헬퍼
[ ] L3.3.c  pytest 2 케이스 추가
[ ] L3.3.d  V1/V2/V3 검증 (handler 회귀 0 확인)
```

**L3 PASS 시점**: L3.3.d 완료. **Full 옵션 종료** 가능.

---

# Phase L4 — 어드민 PII 위젯 (선택, 1시간)

## L4.0 — 사전 분석

### [L4.0.a] SecurityAuditLog 모델 확인

**실행**:
```powershell
findstr /N "class SecurityAuditLog\|action\|event_type\|details" ada\db\models.py | findstr -v "^[^:]*:[^:]*:.*#"
```

**예상**: `SecurityAuditLog` 클래스 + `event_type/action/details/created_at/actor_user_id` 컬럼.

### [L4.0.b] 기존 audit 라우트 패턴 확인

**실행**:
```powershell
findstr /N "@router.get.*admin/audit\|action.*pii_anonymized" api\routes\admin.py
```

**검증**: `/admin/audit` 가 이미 구현된 패턴 — 그대로 따라하기.

---

## L4.1 — `/admin/security/pii` 엔드포인트

### [L4.1.a] 응답 모델

**위치**: `api/routes/admin.py` 의 모델 영역 (기존 모델 클래스들 옆).

```python
class PIIHourlyBucket(BaseModel):
    hour: str          # "2026-05-28T14"
    events: int
    tokens: int


class PIIStatsResponse(BaseModel):
    total_tokens_masked: int
    total_events: int
    by_hour: list[PIIHourlyBucket]
    top_actors: list[dict[str, Any]]  # [{"actor_user_id": "...", "events": 12}]
    since_hours: int
```

### [L4.1.b] 핸들러 구현

**위치**: `api/routes/admin.py` 의 마지막.

```python
@router.get("/admin/security/pii", response_model=PIIStatsResponse, tags=["Admin", "Security"])
async def get_pii_stats(
    since_hours: int = Query(24, ge=1, le=24 * 30),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),
) -> PIIStatsResponse:
    """ADR-008 L4 — SecurityAuditLog 의 pii_anonymized 이벤트 집계.

    details.n_tokens 합산 + 시간별 그래프 + 상위 actor.
    """
    from ada.db.models import SecurityAuditLog

    since = datetime.utcnow() - timedelta(hours=since_hours)

    # action='pii_anonymized' 의 모든 이벤트
    rows = (
        await db.scalars(
            select(SecurityAuditLog)
            .where(SecurityAuditLog.action == "pii_anonymized")
            .where(SecurityAuditLog.created_at >= since)
            .order_by(desc(SecurityAuditLog.created_at))
        )
    ).all()

    total_tokens = 0
    total_events = 0
    by_hour: dict[str, dict[str, int]] = {}
    actor_count: dict[str, int] = {}

    for r in rows:
        total_events += 1
        n = (r.details or {}).get("n_tokens", 0) if isinstance(r.details, dict) else 0
        total_tokens += int(n)

        # 시간별 bucket (YYYY-MM-DDTHH)
        hour_key = r.created_at.strftime("%Y-%m-%dT%H") if r.created_at else "unknown"
        bucket = by_hour.setdefault(hour_key, {"events": 0, "tokens": 0})
        bucket["events"] += 1
        bucket["tokens"] += int(n)

        # actor 집계
        actor = str(r.actor_user_id) if r.actor_user_id else "anonymous"
        actor_count[actor] = actor_count.get(actor, 0) + 1

    return PIIStatsResponse(
        total_tokens_masked=total_tokens,
        total_events=total_events,
        by_hour=[PIIHourlyBucket(hour=h, events=v["events"], tokens=v["tokens"]) for h, v in sorted(by_hour.items())],
        top_actors=sorted(
            [{"actor_user_id": a, "events": c} for a, c in actor_count.items()],
            key=lambda x: x["events"],
            reverse=True,
        )[:10],
        since_hours=since_hours,
    )
```

### [L4.1.c] 단위 테스트

**위치**: `tests/test_day3_admin_langfuse.py` 끝 (admin 라우트 테스트는 day3 파일에 모음).

```python
def test_admin_pii_stats_returns_aggregate(monkeypatch):
    """ADR-008 L4 — /admin/security/pii 집계."""
    pytest.importorskip("fastapi")
    from datetime import datetime
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ada.security.jwt import get_current_user
    from ada.db.session import get_db
    from api.routes import admin as admin_routes

    app = FastAPI()
    app.include_router(admin_routes.router)

    # Fake SecurityAuditLog 행 3개 (pii_anonymized × 2 + 다른 action × 1)
    class FakeRow:
        def __init__(self, action, n_tokens, actor):
            self.action = action
            self.details = {"n_tokens": n_tokens}
            self.created_at = datetime.utcnow()
            self.actor_user_id = actor

    fake_rows = [
        FakeRow("pii_anonymized", 5, "u1"),
        FakeRow("pii_anonymized", 3, "u1"),
    ]

    class FakeScalars:
        def all(self): return fake_rows

    class FakeSession:
        async def scalars(self, *a, **k): return FakeScalars()
        async def execute(self, *a, **k): raise NotImplementedError

    async def fake_db(): yield FakeSession()
    async def fake_admin(): return {"user_id": "u-test", "role": "admin"}

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = fake_admin

    client = TestClient(app)
    r = client.get("/admin/security/pii?since_hours=24")
    assert r.status_code == 200
    body = r.json()
    assert body["total_tokens_masked"] == 8
    assert body["total_events"] == 2
    assert body["since_hours"] == 24
    assert any(a["actor_user_id"] == "u1" for a in body["top_actors"])
```

### [L4.1.d] 검증 3중

**V1 정적**:
```powershell
python -c "import ast; ast.parse(open('api/routes/admin.py').read())"
python -m ruff check api/routes/admin.py
python -c "from api.routes.admin import PIIStatsResponse, PIIHourlyBucket; print('OK')"
```

**V2 단위**:
```powershell
python -m pytest tests/test_day3_admin_langfuse.py::test_admin_pii_stats_returns_aggregate -v
```

**V3 통합**:
```powershell
python -m pytest tests/test_day3_admin_langfuse.py tests/ -q
```

**다음 단계 진입 조건**: 3중 PASS.

---

## L4.2 — Streamlit 위젯 wiring

### [L4.2.a] frontend/app.py admin 탭에 6번째 위젯 추가

**위치**: `frontend/app.py` 의 admin 탭 (ADR-007 L4 에서 추가됨). 마지막 위젯 (budget) 뒤.

```python
        # ADR-008 L4 — 6번째 위젯: PII 마스킹 통계
        st.markdown("### 🛡️ 오늘의 PII 마스킹")
        try:
            r = requests.get(
                f"{API_BASE}/admin/security/pii?since_hours=24",
                headers=headers,
                timeout=5,
            )
            if r.status_code == 200:
                data = r.json()
                c1, c2, c3 = st.columns(3)
                c1.metric("마스킹된 토큰 (24h)", data.get("total_tokens_masked", 0))
                c2.metric("처리 요청 수", data.get("total_events", 0))
                avg = (data["total_tokens_masked"] / data["total_events"]) if data["total_events"] else 0
                c3.metric("요청당 평균 토큰", f"{avg:.2f}")

                # 시간별 차트
                if data.get("by_hour"):
                    import pandas as pd
                    df = pd.DataFrame(data["by_hour"])
                    if not df.empty:
                        df = df.set_index("hour")
                        st.line_chart(df[["events", "tokens"]])

                # 상위 actor
                if data.get("top_actors"):
                    st.caption("상위 PII 처리 actor")
                    st.dataframe(data["top_actors"][:5])
            elif r.status_code == 403:
                st.error("403 — admin role JWT 필요")
            else:
                st.warning(f"조회 실패: HTTP {r.status_code}")
        except Exception as e:
            st.error(f"네트워크 오류: {e}")
```

### [L4.2.b] 시각 검증

**실행**:
```powershell
# 다른 터미널에서 uvicorn 띄움
uvicorn api.main:app --reload --port 8000

# 본 터미널
streamlit run frontend/app.py --server.port 8501
```

**브라우저**: `http://localhost:8501` → Admin 탭 → JWT 입력 → 6번째 위젯 노출.

**검증**:
- 데이터 0건 → 3 metric 모두 0 표시, chart 안 그려짐
- 403 → JWT role 확인

---

## L4 종료 체크리스트

```
[ ] L4.0.a  SecurityAuditLog 모델 확인
[ ] L4.0.b  기존 admin 라우트 패턴 확인
[ ] L4.1.a  PIIStatsResponse 응답 모델
[ ] L4.1.b  /admin/security/pii 핸들러
[ ] L4.1.c  pytest 1 케이스
[ ] L4.1.d  V1/V2/V3 검증
[ ] L4.2.a  Streamlit 위젯
[ ] L4.2.b  시각 검증
```

**L4 PASS 시점**: L4.2.b 완료. **Maxi 옵션 종료**.

---

# Phase E — 통합 검증 스크립트

## [E.1] `scripts/dev/verify_day4.py` 작성

**위치**: `scripts/dev/verify_day4.py` (신규).

**구조** (기존 `verify_day3.py` 패턴 모방):

```python
"""ADR-008 hj-day4 자체 검증 스크립트.

L1~L4 의 모든 가시적 변경을 한 번에 정적/단위 검증.

실행:
    PYTHONUTF8=1 python scripts/dev/verify_day4.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

results: list[tuple[str, bool, str]] = []


def check(name: str):
    def wrapper(fn):
        try:
            fn()
            results.append((name, True, ""))
            print(f"  ✓ {name}")
        except Exception as e:
            results.append((name, False, str(e)))
            print(f"  ✗ {name}: {e}")
        return fn
    return wrapper


print("=" * 70)
print("ADR-008 hj-day4 검증")
print("=" * 70)


# =============================================================================
# L1 — 기존 6 테스트 + Insight hook
# =============================================================================
print("\n[L1] 기존 코드 회귀 검증")


@check("L1.1.a — Day 4 pytest 6 케이스 정의")
def _():
    src = (REPO_ROOT / "tests/test_day4_pii_anonymize.py").read_text(encoding="utf-8")
    expected = [
        "test_detect_and_anonymize_df",
        "test_anonymize_text_deterministic",
        "test_reattach_masks_to_stars",
        "test_reattach_blocks_self_generated_pii",
        "test_security_guard_stores_pii_mapping",
        "test_injection_blocked_by_guard",
    ]
    for t in expected:
        assert f"def {t}" in src, f"누락: {t}"


@check("L1.2.a — SecurityGuardAgent.__call__ 가 _pii 키에 mapping 저장")
def _():
    src = (REPO_ROOT / "agents/security_guard.py").read_text(encoding="utf-8")
    assert 'extras["_pii"]' in src
    assert '"mapping": mapping' in src


@check("L1.2.b — InsightAgent 가 _pii 키로 reattach")
def _():
    src = (REPO_ROOT / "agents/insight.py").read_text(encoding="utf-8")
    assert '.get("_pii")' in src
    assert "reattach_for_user" in src


# =============================================================================
# L2 — Output Carrier reattach
# =============================================================================
print("\n[L2] Output Carrier reattach")


@check("L2.1 — outputs/base.py 에 reattach_pii 정의")
def _():
    src = (REPO_ROOT / "outputs/base.py").read_text(encoding="utf-8")
    assert "def reattach_pii(" in src
    assert "PIIAnonymizer" in src


@check("L2.2.a — markdown_insight reattach 호출")
def _():
    src = (REPO_ROOT / "outputs/markdown_insight.py").read_text(encoding="utf-8")
    assert "reattach_pii" in src
    assert "state: Any = None" in src or "state=None" in src


@check("L2.2.b — pdf reattach 호출")
def _():
    src = (REPO_ROOT / "outputs/pdf.py").read_text(encoding="utf-8")
    assert "reattach_pii" in src


@check("L2.2.c — ppt reattach 호출")
def _():
    src = (REPO_ROOT / "outputs/ppt.py").read_text(encoding="utf-8")
    assert "reattach_pii" in src


@check("L2.2.d — html_dashboard reattach 호출")
def _():
    src = (REPO_ROOT / "outputs/html_dashboard.py").read_text(encoding="utf-8")
    assert "reattach_pii" in src


@check("L2.2.e — script reattach 호출")
def _():
    src = (REPO_ROOT / "outputs/script.py").read_text(encoding="utf-8")
    assert "reattach_pii" in src


@check("L2.3 — report_composer 가 state 전달")
def _():
    src = (REPO_ROOT / "agents/report_composer.py").read_text(encoding="utf-8")
    # state=state 또는 kwargs["state"]
    assert "state=state" in src or 'kwargs["state"]' in src


@check("L2.4 — tests/test_day4_carrier_reattach.py 존재")
def _():
    p = REPO_ROOT / "tests/test_day4_carrier_reattach.py"
    assert p.exists()
    src = p.read_text(encoding="utf-8")
    for t in [
        "test_reattach_pii_helper_with_empty_state",
        "test_reattach_pii_helper_with_mapping",
        "test_markdown_insight_redacts_pii",
    ]:
        assert f"def {t}" in src


# =============================================================================
# L3 — 패턴 정리 + df 마스킹
# =============================================================================
print("\n[L3] 패턴 정리 + DataFrame 마스킹")


@check("L3.1 — redactor docstring 의도 분리")
def _():
    src = (REPO_ROOT / "ada/error_handler/redactor.py").read_text(encoding="utf-8")
    assert "의도 분리" in src
    assert "PIIAnonymizer" in src


@check("L3.1 — guardrails docstring 의도 분리")
def _():
    src = (REPO_ROOT / "ada/security/guardrails.py").read_text(encoding="utf-8")
    assert "의도 분리" in src


@check("L3.2 — _pii_patterns.py 신규 모듈")
def _():
    p = REPO_ROOT / "ada/security/_pii_patterns.py"
    assert p.exists()
    src = p.read_text(encoding="utf-8")
    for sym in ["EMAIL_RE", "PHONE_KR_RE", "RRN_RE", "CARD_RE", "COMMON_PATTERNS"]:
        assert sym in src


@check("L3.2 — guardrails 가 _pii_patterns 사용")
def _():
    src = (REPO_ROOT / "ada/security/guardrails.py").read_text(encoding="utf-8")
    assert "from ada.security._pii_patterns" in src


@check("L3.2 — redactor 가 _pii_patterns 사용")
def _():
    src = (REPO_ROOT / "ada/error_handler/redactor.py").read_text(encoding="utf-8")
    assert "from ada.security._pii_patterns" in src


@check("L3.3 — data_profiler 가 _anonymize_uploaded_df hook")
def _():
    src = (REPO_ROOT / "agents/data_profiler.py").read_text(encoding="utf-8")
    assert "_anonymize_uploaded_df" in src
    assert "_merge_pii_extras" in src


# =============================================================================
# L4 — 어드민 PII 위젯
# =============================================================================
print("\n[L4] 어드민 PII 위젯")


@check("L4.1 — /admin/security/pii 라우트")
def _():
    src = (REPO_ROOT / "api/routes/admin.py").read_text(encoding="utf-8")
    assert "/admin/security/pii" in src
    assert "PIIStatsResponse" in src


@check("L4.1 — pytest test_admin_pii_stats_returns_aggregate")
def _():
    src = (REPO_ROOT / "tests/test_day3_admin_langfuse.py").read_text(encoding="utf-8")
    assert "test_admin_pii_stats_returns_aggregate" in src


@check("L4.2 — frontend admin PII 위젯")
def _():
    src = (REPO_ROOT / "frontend/app.py").read_text(encoding="utf-8")
    assert "/admin/security/pii" in src
    assert "오늘의 PII 마스킹" in src


# =============================================================================
# 결과 요약
# =============================================================================
print("\n" + "=" * 70)
passed = sum(1 for _, ok, _ in results if ok)
failed = sum(1 for _, ok, _ in results if not ok)
print(f"PASSED: {passed} / {len(results)}")
print(f"FAILED: {failed}")
if failed:
    print("\n실패 항목:")
    for name, ok, err in results:
        if not ok:
            print(f"  - {name}: {err}")
    sys.exit(1)
print("✅ 전체 검증 통과")
sys.exit(0)
```

**핵심 assertion 수**: 약 20개 (L1: 3, L2: 9, L3: 6, L4: 3). 각 옵션 별로 적절히 skip 처리 안 함 — 옵션 미적용 시 해당 check 가 fail 로 표시되어 진행 상황 가시화.

## [E.2] 실행

```powershell
$env:PYTHONUTF8="1"
python scripts/dev/verify_day4.py
```

**예상 출력 (Full 적용 시)**:
```
======================================================================
ADR-008 hj-day4 검증
======================================================================

[L1] 기존 코드 회귀 검증
  ✓ L1.1.a — Day 4 pytest 6 케이스 정의
  ✓ L1.2.a — SecurityGuardAgent.__call__ 가 _pii 키에 mapping 저장
  ✓ L1.2.b — InsightAgent 가 _pii 키로 reattach

[L2] Output Carrier reattach
  ✓ L2.1 — outputs/base.py 에 reattach_pii 정의
  ✓ L2.2.a — markdown_insight reattach 호출
  ... (총 9개)

[L3] 패턴 정리 + DataFrame 마스킹
  ✓ L3.1 — redactor docstring 의도 분리
  ... (총 6개)

[L4] 어드민 PII 위젯
  ✓ L4.1 — /admin/security/pii 라우트
  ... (총 3개)

======================================================================
PASSED: 21 / 21
FAILED: 0
✅ 전체 검증 통과
```

## [E.3] 전체 pytest 회귀

```powershell
python -m pytest tests/ -q
```

기대: baseline + 10 신규 (L2.1.d 의 3 + L2.4.a 의 4 + L3.3.c 의 2 + L4.1.c 의 1) = 350+ passed.

---

# Phase F+G+H — 커밋 + Push + 팀 공지

## [F.1] 레이어별 단계 커밋

```powershell
# L1 끝 (기존 코드 회귀만 — 새 파일 없음)
git add docs/ADR-008-DAY4-LLM-GUARD-PII.md docs/ADR-008-DAY4-IMPLEMENTATION-GUIDE.md
git commit -m "hj-day4 L1: 설계 문서 (ADR-008 + 구현 가이드)"
```

```powershell
# L2 끝
git add outputs/base.py outputs/markdown_insight.py outputs/pdf.py outputs/ppt.py outputs/html_dashboard.py outputs/script.py agents/report_composer.py tests/test_day4_carrier_reattach.py
git commit -m "hj-day4 L2: outputs/* reattach_pii 통합 — carrier 5종 사용자 노출 PII 마스킹

DoD: 'PII 컬럼 자동 마스킹 후 결과 페이지에 ***' 의 carrier 측 완전 충족.
변경:
- outputs/base.py: reattach_pii(state, text) 헬퍼 추가
- outputs/{md,pdf,ppt,html,script}.py: generate() 진입부에서 insights/user_intent/rationale 마스킹
- agents/report_composer.py: gen.generate(...) 호출 시 state 전달
- tests: 7 신규 케이스 (헬퍼 3 + carrier 3 + report_composer 정적 1)"
```

```powershell
# L3 끝
git add ada/security/_pii_patterns.py ada/security/guardrails.py ada/error_handler/redactor.py agents/data_profiler.py tests/test_day4_carrier_reattach.py
git commit -m "hj-day4 L3: 공유 PII 패턴 추출 + DataFrame 업로드 마스킹

L3.1 (docstring): redactor↔guardrails 의도 분리 명시 (통합 금지 이유 + reattach 깨짐 경고)
L3.2 (_pii_patterns): 4 공통 패턴 (email/phone/rrn/card) 을 단일 진실 원천으로 추출
L3.3 (data_profiler): 업로드 df 의 PII 컬럼 자동 마스킹 + state.category_extras['_pii']['df_columns'] 노출
  → 핸들러 (CS/NY/jh) 가 PII 컬럼 인지 가능"
```

```powershell
# L4 끝
git add api/routes/admin.py frontend/app.py tests/test_day3_admin_langfuse.py
git commit -m "hj-day4 L4: /admin/security/pii + Streamlit 위젯 — PII 마스킹 통계"
```

```powershell
# 검증 스크립트
git add scripts/dev/verify_day4.py
git commit -m "hj-day4 verify: verify_day4.py — 21 assertion (L1+L2+L3+L4)"
```

## [G.1] end_of_day.sh

```powershell
bash scripts/dev/end_of_day.sh
```

자동 실행 단계:
1. 의존성 동기화 (`pip install -r requirements.txt` 등)
2. 영역 검증 (`scripts/dev/check_scope.sh` — HJ 영역만)
3. pytest 전체
4. rebase onto main
5. rebase 후 재테스트
6. `git push --force-with-lease`

**예상 출력**:
```
✅ Day 4 작업 push 완료
PR 생성/갱신: https://github.com/youandi3535/ADA/pull/new/feat/hj-day4
```

## [G.2] PR 확인

브라우저로 PR URL 열기 → `.github/workflows/auto-pr.yml` 이 자동 채움:
- 제목: `feat(HJ): hj-day4 — LLM Guard PII anonymize↔reattach 풀 통합`
- 본문: 변경 파일 목록 + DoD 충족 여부 + Contract Day 안내

## [H.1] 팀 공지 (Contract Day 머지 직후)

**채널**: Notion `#ada-dev` 또는 Slack/Discord.

**메시지 템플릿** (부록 D 참조):

```
🛡️ Day 4 Contract Day 머지 완료 (HJ) — PR #XXX

변경:
  L1: 기존 PII 파이프라인 회귀 검증 (Day 4 pytest 6 → green)
  L2: outputs/* reattach_pii 통합 (carrier 5종 PII 마스킹)
  L3: 공유 PII 패턴 추출 + DataFrame 업로드 마스킹
  L4: /admin/security/pii + Streamlit 위젯

영향 분석:
  CS (timeseries): datetime 컬럼 → PII 패턴 매칭 없음. 영향 0.
  NY (anomaly): email/phone 이 feature 였다면 ['_pii_df_columns'] 확인 후 제외 권장.
  jh (tabular): 위와 동일. target_column 이 PII 면 경고.

여러분이 해야 할 일:
  1) git fetch && git rebase origin/main
  2) pytest tests/handlers/{여러분_카테고리}/ -q  → 회귀 0 확인
  3) (이론적으로) 핸들러 코드 변경 불필요 — carrier 가 PII 차단

문제 있으면 @HJ 멘션. 24시간 내 응답.
```

---

# 부록 0 — 검증 3중 표준 템플릿

> 본 절은 모든 sub-step 에서 복사해 사용하는 표준 검증 절차.
> V1/V2/V3 셋을 모두 통과해야 다음으로 진입.

## 표준 V1 — 정적 검증

```powershell
$file = "outputs/base.py"   # 변경한 파일

# (a) UTF-8 strict
python -c "open('$file', 'rb').read().decode('utf-8', errors='strict'); print('UTF-8 OK')"

# (b) AST parse
python -c "import ast; ast.parse(open('$file', encoding='utf-8').read()); print('AST OK')"

# (c) Ruff lint
python -m ruff check $file

# (d) Import 가능성
python -c "from outputs.base import reattach_pii; print('Import OK')"

# (e) Git diff 검토
git diff $file
```

기대: 5개 명령 모두 0 exit code + "OK" 메시지.

## 표준 V2 — 단위 검증

```powershell
# (a) 단일 테스트
python -m pytest tests/test_day4_carrier_reattach.py::test_specific -v --tb=short

# (b) 인터프리터 직접 호출
python -c @"
from outputs.base import reattach_pii
result = reattach_pii(None, 'email me@x.com')
assert 'me@x.com' not in result
print('Unit OK')
"@

# (c) 입력 케이스 3종 (정상/경계/에러)
python -m pytest tests/test_day4_carrier_reattach.py -v -k "reattach"
```

기대: assertion 실패 0건.

## 표준 V3 — 통합 검증

```powershell
# (a) 전체 회귀
python -m pytest tests/ -q
# 기대: baseline 카운트 유지/증가, failed 0건

# (b) 영역 검증 + pre-commit
bash scripts/dev/check_scope.sh
# 기대: ✅ 영역 검증 통과 — HJ

# (c) 시각 검증 (Streamlit/Swagger 영향 시)
streamlit run frontend/app.py  # L4 시
uvicorn api.main:app --reload --port 8000  # L4 시 + 브라우저
```

기대: baseline 회귀 0건 + 외부 가시성 (UI/swagger) 의도대로 표시.

## 검증 결과 기록 양식

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

## A.1 — Carrier 의 reattach 표준 호출

```python
def generate(self, *, insights, ..., user_intent, eval_result, state: Any = None) -> str:
    # ADR-008 L2 — PII 마스킹 (사용자 노출 직전)
    from outputs.base import reattach_pii
    insights = reattach_pii(state, insights)
    user_intent = reattach_pii(state, user_intent)
    if eval_result:
        eval_result = {**eval_result, "rationale": reattach_pii(state, eval_result.get("rationale"))}

    # 이후 carrier 본 로직 — insights / user_intent / eval_result 는 안전한 텍스트
    ...
```

**왜 이 순서**: 다른 모든 carrier 로직 (theme, layout, table 생성 등) 전에 마스킹하면 본 carrier 의 어떤 분기에서도 raw PII 가 출력에 흘러가지 않음.

## A.2 — Audit 이벤트 로깅 패턴 (Phase L3.3 / L4 의 결과 확인용)

```python
# agents/security_guard.py 의 기존 패턴 (line 79-86) — 그대로 따라하기
if self.session is not None:
    try:
        await log_event(
            self.session,
            event_type="security",
            action="pii_anonymized",
            result="success",
            actor_user_id=state.user_id,
            details={"n_tokens": len(mapping)},
        )
    except Exception:
        pass
```

## A.3 — PII 정규식 추가 시 표준 (L3.2 의 _pii_patterns)

```python
# 신규 패턴 추가 시 ada/security/_pii_patterns.py 에:
NEW_PATTERN_RE = re.compile(r"...")

# COMMON_PATTERNS 에 등록:
COMMON_PATTERNS = (
    ("email", EMAIL_RE),
    ("rrn", RRN_RE),
    ("phone", PHONE_KR_RE),
    ("card", CARD_RE),
    ("new_kind", NEW_PATTERN_RE),  # 신규
)
# __all__ 에 NEW_PATTERN_RE 추가
```

자동으로 guardrails.PIIAnonymizer 와 redactor 모두 적용됨.

---

# 부록 B — 디버깅 체크리스트

## B.1 — pytest 가 PII 마스킹 실패

1. `PYTHONUTF8=1` 환경변수 셋업? Windows cp949 → 한글 정규식 오작동
2. `pip install pandas==2.2.2` 됐는지 (Day 4 pytest 중 1건이 DataFrame 필요)
3. `ada.security.guardrails` import 성공? `python -c "from ada.security.guardrails import PIIAnonymizer"`

## B.2 — carrier 출력에 raw PII 가 보임

1. carrier 의 `generate()` 시작 부분에 `reattach_pii(state, ...)` 호출 있는지
2. `report_composer.py` 가 `state=state` 를 carrier 에 전달했는지
3. SecurityGuardAgent 가 그래프에서 호출됐는지 (`state.category_extras['_pii']` 채워졌는지)
4. mapping 이 비어있어도 정규식 안전망이 잡아야 함 — `reattach()` 의 마지막 for loop 확인

## B.3 — `<PII:...>` 토큰이 결과에 남음

1. mapping 이 carrier 까지 전파됐는지 (`reattach_pii(state, ...)` 의 `state` 가 None?)
2. LLM 이 토큰을 변형 (`<PII : email : ...>` 처럼 공백 삽입) — 정규식 안전망이 잡아야
3. mapping 의 key (token) 와 carrier 가 받은 텍스트의 token 이 정확히 일치하는지

## B.4 — `_pii_patterns` import 사이클

1. `_pii_patterns.py` 가 다른 ada 모듈 import 하면 안 됨 (stdlib `re` 만)
2. `guardrails.py` 가 `redactor.py` 를 import 하거나 그 반대 — 금지

## B.5 — data_profiler 가 핸들러 회귀 일으킴

1. `state.category_extras['_pii']['df_columns']` 가 핸들러에 노출되는지 확인
2. 핸들러 (jh) 의 fixture 가 PII 컬럼을 feature 로 쓰는지 — 그렇다면 핸들러 수정 필요 (Contract Day 협의)
3. 임시 해결: `data_profiler.py` 의 `_anonymize_uploaded_df` 가 빈 dict 반환하도록 monkeypatch (회귀 우회)

## B.6 — Streamlit 위젯 빈 화면

1. uvicorn 안 띄움 → ConnectionError
2. JWT 미입력 → 위젯 비활성
3. `/admin/security/pii` 라우트 등록 실패 → `findstr "/admin/security/pii" api/routes/admin.py`
4. 데이터 0건 (정상) → metric 모두 0 표시

## B.7 — Contract Day rebase 충돌

1. 다른 멤버가 같은 영역 (carrier, dispatcher) 건드렸을 리 없음 — HJ 단독 영역
2. 만약 충돌 → 멤버에게 알리고 본인 핸들러 영역으로 격리 권장

---

# 부록 C — 작업 시간 추적

| Phase | 예상 | 실제 (기록용) |
|---|---|---|
| L1.0 (사전조건) | 5분 | ___ |
| L1.1 (Day 4 pytest 6) | 5분 | ___ |
| L1.2 (grep 3중) | 10분 | ___ |
| L1.3 (Mini 결정) | 5분 | ___ |
| **L1 합계** | **30분** | ___ |
| L2.0 (사전 분석) | 5분 | ___ |
| L2.1 (reattach_pii 헬퍼) | 20분 | ___ |
| L2.2 (carrier 5종 wiring) | 40분 | ___ |
| L2.3 (report_composer) | 10분 | ___ |
| L2.4 (pytest 4 신규) | 15분 | ___ |
| L2.5 (Standard 결정) | 5분 | ___ |
| **L2 합계** | **1.5시간** | ___ |
| L3.0 (사전 분석) | 10분 | ___ |
| L3.1 (docstring 의도 분리) | 15분 | ___ |
| L3.2 (_pii_patterns 모듈) | 45분 | ___ |
| L3.3 (data_profiler hook) | 50분 | ___ |
| **L3 합계** | **2시간** | ___ |
| L4.0 (사전 분석) | 5분 | ___ |
| L4.1 (라우트 + pytest) | 35분 | ___ |
| L4.2 (Streamlit 위젯) | 20분 | ___ |
| **L4 합계** | **1시간** | ___ |
| E (verify_day4 + 회귀) | 20분 | ___ |
| F+G (commit + push) | 15분 | ___ |
| H (팀 공지) | 5분 | ___ |
| **E+F+G+H 합계** | **40분** | ___ |
| **Full 총합** | **5시간 40분** | ___ |

---

# 부록 D — Contract Day 팀 공지 템플릿

## D.1 — 머지 직후 공지 (필수, 정확히 복붙)

```
🛡️ Day 4 Contract Day 머지 완료 — PR #XXX (HJ)

[변경 요약]
- L1: 기존 Day 4 PII 파이프라인 회귀 검증 ✓
- L2: outputs/* reattach_pii 통합 (carrier 5종 사용자 노출 PII 마스킹)
- L3: 공유 PII 패턴 추출 + DataFrame 업로드 마스킹 hook
- L4: /admin/security/pii + Streamlit 위젯

[여러분이 해야 할 일]
1. git fetch && git rebase origin/main
2. pytest tests/handlers/{여러분_카테고리}/ -q  → 회귀 0 확인
3. 본인 핸들러가 fixture 에 PII 컬럼 (email/phone/rrn/card) 사용하면
   state.category_extras['_pii']['df_columns'] 보고 feature 후보에서 제외 권장

[영향 분석]
- CS (timeseries): datetime 컬럼 → PII 매칭 없음. 영향 0.
- NY (anomaly): email 컬럼이 feature → 토큰화로 카디널리티 변경.
  → contamination 추정에 영향 가능. 점검 권장.
- jh (tabular):
  - target_column 이 PII 면 학습 자체 의미 없음 → PIIAnonymizer.detect_pii_columns(df) 로 사전 확인 권장.
  - 일반 feature 가 PII 면 잘 알려진 컬럼 (email/phone) 만 제외 — 다른 컬럼은 영향 없음.

[방어망]
- 핸들러 코드 변경 없어도 carrier 가 사용자에게 raw PII 노출 차단함 (L2).
- 핸들러 출력 (text_blocks) 에 PII 가 섞여도 carrier 에서 *** 로 마스킹.
- 따라서 핸들러 코드 강제 변경 없음. 다만 위 영향 분석 참고해 정확도 점검 권장.

[문제 있으면]
- @HJ 멘션, 24시간 내 응답.
- 본 작업의 설계 문서: docs/ADR-008-DAY4-LLM-GUARD-PII.md
- 구현 가이드: docs/ADR-008-DAY4-IMPLEMENTATION-GUIDE.md
```

## D.2 — 후속 24시간 동안 모니터링 채널

- `#ada-dev` Slack/Notion 채널에 다음 commit 의 PR / pytest 결과 확인
- CS/NY/jh 의 rebase 후 첫 pytest 결과 받아서 회귀 0 인지 확인
- 만약 회귀 발견 → 본 ADR 의 부록 B.5 (data_profiler 회귀) 참고해 임시 우회 / 핸들러 수정

— 끝.
