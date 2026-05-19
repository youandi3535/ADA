# Day 16 — 자동 오류 처리 에이전트 + Claude CLI 사이드카 브리지 + Error KB
> 프로젝트: Adaptive AutoAI Pipeline Agent | 3주 스프린트 Day 16/21
> 본 문서는 v2 신규 작업이다. 마스터 설계서 §6 참조.

---

## 📋 오늘의 목표

전체 에이전트 시스템을 감시하면서 **모든 예외를 1차로 잡아 처리하는 AutoErrorHandlerAgent** 와, **격리된 Claude CLI 사이드카** 를 통해 처음 보는 오류를 자가 진단/패치하는 시스템을 완성한다. 같은 오류가 다시 발생하면 KB에서 먼저 해결하고, 시간이 갈수록 Claude CLI 호출이 감소한다.

핵심:
- BaseAgent의 try/except 훅이 AutoErrorHandlerAgent로 라우팅
- error_hash 정규화 → error_kb 조회 → hit/miss 분기
- Claude CLI 사이드카로 격리 호출 → 패치 제안 → 샌드박스 적용 → 자동 또는 인간 검토
- 자체 해결률 (KP8) ≥ 60% 달성을 위한 신뢰도·통계 누적

---

## 👤 담당자

- **A** 주도 (에이전트, KB 알고리즘)
- **D** 협업 (Claude CLI 사이드카, 보안 격리)

---

## ✅ 작업 목록

### 1. `agents/auto_error_handler.py` — 완성

```python
class AutoErrorHandlerAgent(BaseAgent):
    """첫 호출 처리 책임. 모든 BaseAgent.__call__ 의 try/except 훅에서 진입."""

    use_llm = False  # 자체 Claude CLI 사용 (외부 sidecar)

    def handle(self, state: PipelineStateV2, exc: Exception, agent_name: str) -> PipelineStateV2:
        ctx = self._build_error_context(state, exc, agent_name)
        log_audit("auto_error_handler_invoked", "warn", ctx)

        error_hash = self._hash_error(agent_name, type(exc).__name__, ctx["stack"])
        kb_hit = self._lookup_kb(error_hash)

        if kb_hit and kb_hit["confidence"] >= 0.8:
            return self._apply_patch_from_kb(state, kb_hit, ctx)
        elif kb_hit and kb_hit["confidence"] >= 0.5:
            return self._retry_with_monitor(state, kb_hit, ctx)
        else:
            return self._call_cli_and_learn(state, ctx)

    # 이하 메서드들...
```

#### 1.1 `_hash_error` — stack trace 정규화

- [ ] 파일 경로 절대경로 → 상대경로 변환
- [ ] 라인 번호 제거 (예: `line 123` → `line N`)
- [ ] 메모리 주소 제거 (`0x7f4a...`)
- [ ] 임시 파일 경로 마스킹 (`/tmp/xyz` → `<TMP>`)
- [ ] 정규화된 텍스트 SHA-256

```python
def _hash_error(self, agent: str, exc_type: str, stack: str) -> str:
    normalized = re.sub(r"line \d+", "line N", stack)
    normalized = re.sub(r"0x[0-9a-fA-F]+", "<ADDR>", normalized)
    normalized = re.sub(r"/tmp/[^/\s]+", "<TMP>", normalized)
    sig = f"{agent}|{exc_type}|{normalized}"
    return hashlib.sha256(sig.encode("utf-8")).hexdigest()
```

#### 1.2 `_build_error_context`

```python
def _build_error_context(self, state, exc, agent):
    return {
        "agent": agent,
        "exc_type": type(exc).__name__,
        "exc_msg": str(exc)[:500],
        "stack": traceback.format_exc(limit=20),
        "state_summary": {
            "job_id": state.job_id,
            "category": state.category,
            "task": state.task,
            "current_gate": state.current_gate,
            "retry_count": state.retry_count,
        },
        "agent_inputs_hint": self._summarize_state(state),
        "git_sha": settings.GIT_SHA,
    }
```

#### 1.3 `_apply_patch_from_kb`

- [ ] kb_hit["patch_strategy"] 타입별 분기:
  - `param_adjust`: state 또는 모델 파라미터 자동 조정 후 재시도
  - `retry`: 단순 재시도
  - `fallback`: 대체 에이전트/모델 사용
  - `code_patch`: pending_patches에서 이미 검토 완료된 패치만 자동 적용
- [ ] 성공 → kb_hit["success_count"]+=1, confidence += 0.05 (상한 0.98)
- [ ] 실패 → fail_count+=1, confidence -= 0.10 (하한 0.10), 폴백 ErrorRecoveryAgent

#### 1.4 `_retry_with_monitor`

- [ ] 낮은 신뢰도 KB는 적용 + 결과 관찰
- [ ] 결과에 따라 confidence 조정

#### 1.5 `_call_cli_and_learn`

- [ ] Claude CLI 사이드카 호출 (§2)
- [ ] 응답 검증 후 error_kb INSERT (confidence는 응답에서 추출, 캡 0.8)
- [ ] 적용 시도, 결과 기록

### 2. `error_handler/cli_bridge.py` — Claude CLI 사이드카 호출

```python
import subprocess, json, tempfile, os
from pathlib import Path

CLI_CONTAINER = "claude-cli-sidecar"
WORKSPACE_RO = "/workspace"
PATCH_OUT = "/error_handler/patches"

REPAIR_PROMPT_TEMPLATE = """
당신은 격리된 컨테이너 안의 진단 보조입니다. 다음 오류를 분석하여
JSON 형식으로만 응답하세요. 코드는 절대 직접 수정하지 마세요.
필요하면 Read/Grep/Glob 로 코드를 살펴보고 정확한 진단을 내려주세요.

응답 형식:
{
  "root_cause": "...",
  "patch_strategy": {
    "type": "param_adjust|retry|fallback|code_patch",
    "detail": {...}      // type별 디테일
  },
  "patch_diff": "...",   // type='code_patch'인 경우 unified diff
  "confidence": 0.0~1.0,
  "test_plan": "...",
  "applies_to_agents": ["..."]
}

오류 컨텍스트:
{ctx_json}
"""

def ask_claude_cli(error_context: dict, max_turns: int = 3, timeout_s: int = 120) -> dict:
    prompt = REPAIR_PROMPT_TEMPLATE.format(ctx_json=json.dumps(error_context, ensure_ascii=False, indent=2))

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, dir="/tmp") as f:
        f.write(prompt)
        prompt_path = f.name

    cmd = [
        "docker", "exec", "-i", CLI_CONTAINER,
        "claude", "-p", "@-",
        "--max-turns", str(max_turns),
        "--output-format", "json",
        "--allowed-tools", "Read,Grep,Glob",
        "--system-prompt", "당신은 격리된 진단 보조입니다. 절대 파일을 쓰지 마세요. 절대 외부 네트워크에 접근하지 마세요.",
    ]
    with open(prompt_path) as pf:
        res = subprocess.run(cmd, stdin=pf, capture_output=True, text=True, timeout=timeout_s)
    os.unlink(prompt_path)

    if res.returncode != 0:
        raise RuntimeError(f"claude-cli failed (code {res.returncode}): {res.stderr[:300]}")

    # JSON 추출 (Claude CLI는 JSON 모드에서 마지막 메시지에 JSON 반환)
    try:
        out = json.loads(res.stdout)
    except json.JSONDecodeError:
        # Claude CLI output may wrap in {"result": "..."}
        wrapper = json.loads(res.stdout)
        out = json.loads(wrapper.get("result", "{}"))

    # 응답 검증
    required = {"root_cause", "patch_strategy", "confidence"}
    if not required.issubset(out.keys()):
        raise ValueError(f"claude-cli response missing required keys: {required - set(out.keys())}")
    if not (0.0 <= out["confidence"] <= 1.0):
        raise ValueError("confidence out of range")
    return out
```

### 3. `error_handler/patcher.py` — 패치 샌드박스 적용

```python
class PatchApplier:
    def apply(self, strategy: dict, state: PipelineStateV2) -> tuple[bool, str]:
        """Returns (success, log_message)."""
        ptype = strategy["type"]
        if ptype == "param_adjust":
            return self._apply_param_adjust(strategy["detail"], state)
        elif ptype == "retry":
            return True, "marked for retry"
        elif ptype == "fallback":
            return self._apply_fallback(strategy["detail"], state)
        elif ptype == "code_patch":
            return self._stage_code_patch(strategy["detail"])
        else:
            return False, f"unknown patch type: {ptype}"

    def _stage_code_patch(self, detail: dict) -> tuple[bool, str]:
        """
        code_patch 는 자동 적용 금지. pending_patches 큐로만 저장하고
        인간 검토 후 admin API 로 승인되어야 머지.
        """
        patch_id = uuid4()
        pp = PendingPatch(id=patch_id, patch_diff=detail.get("diff"),
                          test_plan=detail.get("test_plan"),
                          confidence=detail.get("confidence", 0.5))
        db.add(pp); db.commit()
        log_audit("patch_pending_review", "warn", {"patch_id": str(patch_id)})
        return False, f"staged patch {patch_id} for human review"
```

### 4. `error_handler/normalize.py` — 정규화 유틸 (Day3 베이스 강화)

- [ ] `normalize_stack(stack: str) -> str` — 파일경로/라인/주소/UUID/TMP 정규화
- [ ] `summarize_for_kb(ctx: dict) -> str` — KB 검색용 1줄 시그니처

### 5. error_kb 운영 자동화

- [ ] 야간 cron (`scripts/error_kb_maintenance.py`):
  - confidence < 0.2 + fail_count > 10 → `is_active=false`
  - 30일 미발생 + success_count = 0 항목 정리
  - 동일 agent_name + exc_type 의 유사 hash 군집화 (pgvector로 embedding 추후 추가)

### 6. AGENTS.md 자동 룰 (R-6xx)

- [ ] AutoErrorHandlerAgent 가 confidence ≥ 0.9 + 자동 적용 성공 시 RulesManager 통해 R-6xx 자동 누적
- [ ] 형식: "발생 조건 → 사전 차단 가드"

### 7. 단위 테스트 + 시뮬레이션

- [ ] `tests/test_error_handler/test_hash.py` — 동일 오류 다른 인스턴스가 동일 hash 산출
- [ ] `tests/test_error_handler/test_kb_lookup.py` — hit/miss 분기
- [ ] `tests/test_error_handler/test_cli_bridge.py` — Claude CLI 사이드카 mock (실제 호출 비싸므로 stub)
- [ ] `tests/test_error_handler/test_patcher.py` — 4가지 patch type 적용
- [ ] **시뮬레이션 (`tests/integration/test_error_kb_learning.py`):**
  - 시나리오 1: 동일 오류 5회 연속 발생 → 1회 CLI, 4회 KB hit, 자동해결률 80%
  - 시나리오 2: confidence 진화 — 5회 성공 후 confidence ≥ 0.95

---

## 🏗️ 구현 명세

### BaseAgent 훅 (Day3 작성, 여기서 활성화)

```python
class BaseAgent(ABC):
    def __call__(self, state):
        try:
            return self._call_impl(state)
        except Exception as exc:
            if not settings.ENABLE_AUTO_ERROR_HANDLER:
                raise
            from agents.auto_error_handler import AutoErrorHandlerAgent
            handler = AutoErrorHandlerAgent()
            try:
                return handler.handle(state, exc, self.__class__.__name__)
            except Exception:
                # AutoErrorHandler 자체 실패 → 최후 폴백
                from agents.error_recovery import ErrorRecoveryAgent
                return ErrorRecoveryAgent()(state.model_copy(update={
                    "error_info": {"original_exc": str(exc)},
                    "next_agent": "error_recovery",
                }))
```

### 사이드카 보안 정책

- [ ] 컨테이너 옵션: `--cap-drop ALL --security-opt no-new-privileges --read-only` (R-602)
- [ ] 네트워크: `ada-net` 내부만, 외부 인터넷 차단 (단, Anthropic API 호출은 필요 — proxy 또는 allowlist)
- [ ] `tmpfs /tmp` (쓰기 가능한 임시 공간)
- [ ] `--user 1001` 비루트 사용자
- [ ] 코드 마운트 `:ro` 강제. 출력은 `/error_handler/patches` 만 rw

### Anthropic API 사용 비용 가드

- [ ] `MAX_DAILY_CLI_USD=5` 일일 한도. Redis 토큰 버킷으로 누적 비용 추적
- [ ] 한도 초과 시 KB-only 모드로 자동 전환 (새 오류는 ErrorRecovery로 폴백)

---

## 📁 생성/수정 파일 목록

| 경로 | 작업 |
|---|---|
| `agents/auto_error_handler.py` | 완성 |
| `error_handler/cli_bridge.py` | 완성 |
| `error_handler/patcher.py` | 신규 |
| `error_handler/normalize.py` | 강화 |
| `error_handler/kb_client.py` | 강화 |
| `scripts/error_kb_maintenance.py` | 신규 |
| `tests/test_error_handler/*.py` (5 파일) | 신규 |
| `tests/integration/test_error_kb_learning.py` | 신규 |
| `agents/base.py` | 훅 활성화 |
| `docker-compose.yml` | claude-cli-sidecar 보안 옵션 강화 |

---

## 🔗 의존성 & 선행 조건

- Day1 claude-cli-sidecar 컨테이너 기동
- Day2 error_kb / pending_patches 테이블 + RLS
- Day3 error_handler 베이스 모듈
- ANTHROPIC_API_KEY 사이드카에서 사용 가능

---

## ✔️ 완료 기준

- [ ] AutoErrorHandler가 BaseAgent 훅 통해 진입하는 단위 테스트 통과
- [ ] error_kb hit → confidence 진화 → 자동 적용 시뮬레이션 통과
- [ ] Claude CLI 사이드카 호출 mock 단위 테스트 통과
- [ ] 시뮬레이션: 동일 오류 5회 → 자동해결률 ≥ 80%
- [ ] pending_patches 큐 + admin 승인 API 라운드트립 동작 확인
- [ ] `docker inspect claude-cli-sidecar` 에서 `ReadonlyRootfs=true`, `CapDrop=[ALL]` 확인

---

## ⚠️ 주의사항

- claude-cli 사이드카가 응답을 100% 보장 못 함 — timeout 120s 후 ErrorRecovery 폴백
- code_patch type 은 **절대 자동 적용 금지**. 무조건 pending_patches 큐 + 인간 검토
- error_kb 가 너무 많은 false hit 을 만들 위험 — confidence 하한 0.10 유지
- Anthropic API 비용 폭주 가드: 일일 한도 (MAX_DAILY_CLI_USD), 시간당 호출 수 (CLI_HOURLY_LIMIT=20)
- 컨테이너 탈출 시도 감지: `docker events` 모니터 + 비정상 명령 실행 시 사이드카 자동 재시작

---

## 🆕 v2.2 보강 (감사 보고서 2026-05-19 반영)

> 출처: `ADA_v2_감사보고서.docx`. 본 섹션이 v2.1 본문과 충돌 시 **v2.2가 우선**한다.

### 1) subprocess → Anthropic SDK 비동기 호출
- `docker exec` + `subprocess.run(timeout=120)` 패턴 폐지.
- Anthropic Python SDK 를 별도 스레드 풀에서 비동기 호출. extended thinking + prompt caching 활용.
- claude-cli-sidecar 는 read-only 코드 검색용으로만 유지 (옵션).

### 2) 회로차단기 (R-601 보강)
- `@claude_cli_breaker` 5회 실패 → 30분 OPEN.
- Redis 토큰 버킷: 시간당 호출 강제 제한(CLI_HOURLY_LIMIT=20).
- MAX_DAILY_CLI_USD=5 는 hard cap (초과 시 OPEN).

### 3) error_hash 정규화 강화
- 한글·이모지·CJK 비ASCII 스택 normalize 함수 + unit test 50건.
- 라인 번호 외에 메모리 주소·UUID·timestamp 도 정규화.

### 4) AutoErrorHandler 무한 재귀 가드
- handler 자체 실패 시 max 1회만 ErrorRecoveryAgent 로 폴백. 이후 즉시 critical alarm + 잡 abort.

### 5) Patch 자동 적용 정책 명시
- `code_patch` 타입은 절대 자동 적용 X (pending_patches 인간 검토만).
- `param_adjust`, `retry`, `fallback` 3종만 confidence ≥ 0.9 + 단위 테스트 통과 시 자동.

### 완료 기준 추가
- [ ] subprocess 호출 코드 0건 (grep 가드)
- [ ] @claude_cli_breaker 5회 실패 OPEN 테스트
- [ ] 한글 스택 정규화 50건 통과
- [ ] 무한 재귀 시뮬레이션 → 정확히 1회만 폴백

---

## 🧰 v2.3 도구 보강 (도구 카탈로그 2026-05-19 반영)

> 출처: `TOOL_CATALOG_2026.md`. 본 섹션은 Day-D / Day-E / v3_backlog 의 도구를 본 Day 의 코드 위치에 매핑한다.

### 적용 도구
- **SWE-agent** (⚪ v3 백로그 B.3) — AutoErrorHandler 의 read-only 한계를 넘어 자율 코드 패치 PR 생성.
- 현재(v2.3)는 R-601 보강(Anthropic SDK 비동기 + pybreaker)으로 충분. SWE-agent 는 30일 운영 + pending_patches 안정성 검증 후 도입 검토.
- 도입 시 100% 인간 검토 유지 + ADR-1108 작성 필수.
