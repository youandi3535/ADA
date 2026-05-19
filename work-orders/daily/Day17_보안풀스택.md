# Day 17 — 보안 풀스택 (AuthN·RBAC·PII·프롬프트 인젝션·암호화·Vault·감사)
> 프로젝트: Adaptive AutoAI Pipeline Agent | 3주 스프린트 Day 17/21
> 본 문서는 v2 신규 작업이다. 마스터 설계서 §10 참조.

---

## 📋 오늘의 목표

v2 시스템 전체에 대한 **종단 보안 모델** 을 완성한다. 사용자 인증, 권한 부여, PII 보호, 프롬프트 인젝션 방어, 데이터 암호화, 시크릿 관리, 감사 로그가 모두 활성화되어 침투 테스트 50종을 0건 통과 (KP10).

---

## 👤 담당자

- **D** 주도 (보안 총괄)
- **C** 협업 (DB RLS, 컬럼 암호화)
- **A** 협업 (프롬프트 인젝션 방어, AGENTS.md 보안 룰)

---

## ✅ 작업 목록

### 1. 인증 (Authentication) — JWT

- [ ] `api/middleware/auth.py` — Bearer 토큰 파싱, 검증, request.state.user 설정
- [ ] `api/routes/auth.py`:
  - `POST /auth/register` — 이메일+패스워드 (Argon2id 해시)
  - `POST /auth/login` — JWT 발급 (access 24h + refresh 30d)
  - `POST /auth/refresh` — refresh 토큰으로 access 재발급
  - `POST /auth/logout` — 토큰 블랙리스트 추가 (Redis SET, TTL = 토큰 만료 시각)
  - `GET /auth/me` — 현재 사용자 정보
  - `POST /auth/mfa/enable`, `POST /auth/mfa/verify` (TOTP, `pyotp`)
- [ ] JWT 클레임:
  ```json
  {
    "sub": "user_uuid",
    "email": "user@example.com",
    "role": "analyst",
    "iat": 1715800000,
    "exp": 1715886400,
    "jti": "unique_token_id"
  }
  ```
- [ ] HS256, secret from Vault (`secret/data/jwt/secret_key`)

### 2. 권한 부여 (Authorization) — RBAC

- [ ] `api/dependencies/rbac.py`:
  ```python
  def require_role(*roles):
      def dep(current_user = Depends(get_current_user)):
          if current_user.role not in roles:
              raise HTTPException(403, "권한 없음")
          return current_user
      return dep
  ```
- [ ] 4역할 매트릭스 (마스터 §10.2) 모든 엔드포인트 데코레이션:
  ```python
  @router.post("/admin/rules/{id}/approve", dependencies=[Depends(require_role("admin"))])
  ```
- [ ] 자원 소유권 검증 (analyst가 다른 analyst 잡 접근 차단):
  ```python
  def require_owner(job_id: UUID, user = Depends(get_current_user)):
      job = db.get(Job, job_id)
      if user.role != "admin" and job.user_id != user.id:
          raise HTTPException(403)
      return job
  ```

### 3. Row-Level Security (RLS)

- [ ] Day2에서 깐 RLS 정책을 모든 사용자 관련 테이블에 확대:
  - `uploads`, `jobs`, `agent_runs`, `models`, `outputs`, `interactive_sessions`, `decisions`
- [ ] API 진입 시점에 SQLAlchemy 이벤트 hook으로 `SET LOCAL app.current_user_id = ...`
- [ ] 슈퍼유저 우회 방지: 워커 전용 role `autoai_worker` 분리 (BYPASSRLS 권한 없음)

### 4. PII 보호 — 풀 파이프라인

- [ ] `security/pii_detector.py` 강화:
  - 정규식 (한국 주민번호, 한국 휴대전화, 신용카드 Luhn, 이메일, IPv4/v6, 한국 도로명/지번 주소 시그니처)
  - 정규식 + 한국어 키워드 휴리스틱 only (v2.1: NER 모델 의존성 제거)
  - 컬럼명 휴리스틱: ['name','email','phone','mobile','id','ssn','rrn','card','address','addr','dob','birth',...]
  - 검사 대상은 정형 컬럼(텍스트/숫자)만 — v2.1 스코프 축소로 이미지/오디오 컬럼은 입력 형식 자체에서 제외됨
- [ ] `security/pii_masker.py`:
  - `mask_text(s)` — 정규식 매칭 부분 `***` 또는 부분 마스킹 (`010-****-1234`)
  - `pseudonymize_column(s, salt)` — Faker 기반 결정론적 가명화 (동일 원본 → 동일 가명)
- [ ] DataProfilerAgent 진입 시 자동 스캔 (Day5 v2 확장에서 이미 연결)
- [ ] InsightAgent / 산출물 생성기들이 LLM 호출 직전 사용자 데이터 텍스트화할 때 자동 마스킹

### 5. 프롬프트 인젝션 방어

- [ ] `security/prompt_defense.py` (Day3에서 시작) — 정규식 + 휴리스틱:
  ```python
  INJECTION_PATTERNS = [
      r"ignore\s+(previous|all|above)\s+instruction",
      r"system\s*[:>]\s*",
      r"<\|system\|>", r"<\|im_start\|>",
      r"\\n\\n(Human|Assistant):",
      r"jailbreak", r"DAN\s+mode",
      r"이전\s*명령\s*무시", r"시스템\s*프롬프트",
      r"sudo\b", r"`rm\s+-rf",
      r"export\s+\w+\s*=", r"환경\s*변수",
  ]
  ```
- [ ] 사용자 입력 모든 진입점:
  - POST /upload (filename, metadata)
  - POST /pipeline/start (user_intent)
  - POST /pipeline/{}/decision (rationale)
- [ ] `wrap_in_user_block` — LLM 시스템 프롬프트에 `<<<USER_INPUT_BEGIN>>> ... <<<USER_INPUT_END>>>` 구분자 강제
- [ ] LLM 응답에서 system role 이스케이프 검출 → 응답 거부 + audit_log

### 6. SecurityGuardAgent — 메타 에이전트

- [ ] `agents/security_guard.py`:
  - 모든 LLM 호출 직전 입력 검사 (BaseAgent._call_llm 안에서 invoke)
  - 모든 LLM 응답 직후 검사 (PII 누출 감지, 정책 위반 텍스트)
  - 위반 발견 시: 차단 + audit_log + Slack 알림 (`SLACK_SECURITY_WEBHOOK`)
- [ ] 통계 누적: `audit_log` 기준 일별 차단 횟수

### 7. 데이터 암호화

#### 7.1 전송 중

- [ ] `nginx` 리버스 프록시 컨테이너 추가:
  ```yaml
  nginx:
    image: nginx:1.25-alpine
    ports: ["443:443"]
    volumes:
      - ./docker/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./certs:/etc/nginx/certs:ro
    depends_on: [api, frontend]
  ```
- [ ] mkcert 또는 Let's Encrypt 인증서, TLS 1.3 강제
- [ ] HSTS 헤더, CSP, X-Frame-Options DENY, X-Content-Type-Options nosniff

#### 7.2 저장 시

- [ ] PostgreSQL `pg_crypto` 컬럼 암호화 (`users.email_enc`, `audit_log.subject_email_enc`):
  - SQL: `pgp_sym_encrypt(email, current_setting('app.crypto_key'))`
  - `app.crypto_key`는 부팅 시 Vault에서 fetch → `ALTER SYSTEM SET app.crypto_key`
- [ ] MinIO SSE-S3:
  ```python
  s3.put_object(Bucket=..., Key=..., Body=data, ServerSideEncryption='AES256')
  ```
- [ ] PostgreSQL 디스크 암호화는 운영 환경에서 LUKS/EBS 권장 (개발은 생략)

### 8. 시크릿 관리 — Vault

- [ ] Day1에서 깐 Vault dev 컨테이너 활용
- [ ] `scripts/vault_seed.sh`:
  ```bash
  export VAULT_ADDR=http://localhost:8200
  export VAULT_TOKEN=$VAULT_DEV_TOKEN
  vault secrets enable -path=secret kv-v2
  vault kv put secret/anthropic api_key=$ANTHROPIC_API_KEY
  vault kv put secret/postgres password=$POSTGRES_PASSWORD
  vault kv put secret/jwt secret_key=$(openssl rand -hex 32)
  vault kv put secret/crypto key=$(openssl rand -hex 32)
  vault kv put secret/minio access_key=... secret_key=...
  ```
- [ ] `security/vault_client.py`:
  ```python
  class VaultClient:
      def __init__(self):
          self.client = hvac.Client(url=settings.VAULT_ADDR, token=settings.VAULT_TOKEN)
          self._cache = {}
          self._ttl = {}
      def get(self, path, ttl=300):
          if path in self._cache and time.time() - self._ttl[path] < ttl:
              return self._cache[path]
          v = self.client.secrets.kv.v2.read_secret_version(path=path)["data"]["data"]
          self._cache[path] = v; self._ttl[path] = time.time()
          return v
  ```
- [ ] 모든 시크릿 사용처 (Anthropic, Postgres, MinIO, JWT) Vault 경유로 변경
- [ ] `.env` 는 Vault 토큰만 남기고 평문 시크릿 제거 (dev 환경에서도)

### 9. 시크릿 회전 (cron)

- [ ] `scripts/rotate_secrets.py`:
  - `JWT_SECRET` 30일 회전 (기존 토큰은 grace period 24h 유지)
  - `POSTGRES_PASSWORD` 90일 회전 (`ALTER USER ... WITH PASSWORD`)
  - `app.crypto_key` 회전은 데이터 재암호화 필요 — 수동/계획적 (분기별)
- [ ] cron: `0 3 * * 0 python /scripts/rotate_secrets.py`

### 10. 감사 로그 — `security_audit_log` 적극 사용

- [ ] 모든 보안 이벤트 INSERT:
  - 로그인 성공/실패, 로그아웃, MFA 등록/검증
  - PII 스캔 결과, 마스킹 적용
  - 프롬프트 인젝션 시도 차단
  - 권한 위반 시도 (403)
  - 시크릿 회전, KV 접근
  - Rate limit 차단
  - 게이트 자동 처리 (auto_resolved)
  - 패치 적용/거부
- [ ] 보존 정책: 1년 (월별 파티셔닝)
- [ ] 대시보드 §9 알람 패널이 이 테이블을 읽음

### 11. 컨테이너 격리 강화

- [ ] 모든 컨테이너 `--user 1001 --cap-drop ALL --read-only`
- [ ] `tmpfs /tmp`, `tmpfs /var/run`
- [ ] `--security-opt seccomp=docker/seccomp_strict.json` (Docker default seccomp 변형)
- [ ] 워커 컨테이너에는 추가로 `--cap-add SYS_NICE` (학습 우선순위 조정용) 만 허용
- [ ] `docker scout` 또는 `trivy` 로 이미지 취약점 스캔, CI 단계 통합

### 12. Rate Limit 풀 적용

- [ ] `security/rate_limit.py` (Day3 베이스 강화):
  ```python
  @rate_limit(key=lambda r: f"{r.url.path}:{r.state.user.id}", limit=20, window=60)
  ```
- [ ] 엔드포인트별 한도:
  - `/upload`: 20/min/user
  - `/pipeline/start`: 5/min/user
  - `/pipeline/.../decision`: 60/min/user
  - `/predict/*`: 100/min/user
  - `/auth/login`: 5/15min/IP (브루트포스 방어)
- [ ] 한도 초과: 429 + `X-RateLimit-Limit/Remaining/Reset`

### 13. 침투 테스트 시나리오 (Day20에서 실행, 여기서 작성)

- [ ] `tests/security/penetration_tests.py` — 50종:
  - SQL injection 페이로드 20종 (uploads, filename, intent)
  - 프롬프트 인젝션 페이로드 15종 (한/영 혼합)
  - 권한 우회 (다른 user의 job_id 직접 호출) 5종
  - JWT 변조 (alg=none, 만료, 변조) 5종
  - Path traversal (filename: `../../etc/passwd`) 3종
  - Zip bomb 2종
- [ ] 각 시나리오는 차단 응답(4xx) 또는 sanitize 확인

### 14. AGENTS.md R-7xx 보안 룰 14개

- [ ] R-701~R-714 작성 (마스터 §14.1)

---

## 🏗️ 구현 명세

### JWT 미들웨어 핵심

```python
# api/middleware/auth.py
from jose import jwt, JWTError
from fastapi import Request, HTTPException

class JWTAuthMiddleware:
    def __init__(self, app, public_paths={"/auth/login","/auth/register","/health"}):
        self.app = app
        self.public = public_paths
    async def __call__(self, request, call_next):
        path = request.url.path
        if path in self.public or path.startswith("/docs"):
            return await call_next(request)
        token = request.headers.get("authorization","").removeprefix("Bearer ").strip()
        if not token:
            raise HTTPException(401, "토큰 없음")
        try:
            payload = jwt.decode(token, vault.get("jwt")["secret_key"], algorithms=["HS256"])
        except JWTError:
            raise HTTPException(401, "토큰 무효")
        if redis.sismember("jwt:blacklist", payload["jti"]):
            raise HTTPException(401, "토큰 폐기됨")
        request.state.user = User(id=payload["sub"], email=payload["email"], role=payload["role"])
        # RLS: SET LOCAL app.current_user_id
        async with AsyncSessionLocal() as sess:
            await sess.execute(text(f"SET LOCAL app.current_user_id = '{payload['sub']}'"))
        return await call_next(request)
```

### Argon2id 패스워드 해시

```python
from argon2 import PasswordHasher
ph = PasswordHasher(time_cost=3, memory_cost=64*1024, parallelism=4, hash_len=32)
hash_str = ph.hash("user_password")
ph.verify(hash_str, "user_password")
```

---

## 📁 생성/수정 파일 목록

| 경로 | 작업 |
|---|---|
| `api/middleware/auth.py` | 신규 |
| `api/routes/auth.py` | 신규 |
| `api/dependencies/rbac.py` | 신규 |
| `security/pii_masker.py` | 신규 |
| `security/vault_client.py` | 신규 |
| `agents/security_guard.py` | 신규 |
| `docker/nginx.conf` | 신규 |
| `docker/seccomp_strict.json` | 신규 |
| `scripts/vault_seed.sh` | 신규 |
| `scripts/rotate_secrets.py` | 신규 |
| `migrations/006_pgcrypto_columns.sql` | 신규 (이메일 등 컬럼 enc) |
| `tests/security/penetration_tests.py` | 신규 (50종) |
| `.github/workflows/security_scan.yml` | 수정 (trivy 추가) |
| AGENTS.md | R-701~R-714 추가 |

---

## 🔗 의존성 & 선행 조건

- Day1 vault 컨테이너
- Day2 RLS 정책 베이스
- Day3 prompt_defense, pii_detector, vault_client 스텁
- 패키지: `python-jose`, `argon2-cffi`, `hvac`, `pyotp`

---

## ✔️ 완료 기준

- [ ] /auth/login → JWT 발급 + /auth/me 정상 동작
- [ ] role=viewer 사용자가 /pipeline/start 호출 시 403
- [ ] analyst 사용자가 다른 user의 job_id 조회 시 0행 (RLS)
- [ ] 이메일 컬럼이 SELECT * 결과에 평문 표시되지 않음 (pg_crypto)
- [ ] MinIO 객체 메타에 `x-amz-server-side-encryption: AES256` 확인
- [ ] 프롬프트 인젝션 50종 페이로드 sanitize 결과에 `[BLOCKED]` 또는 거부
- [ ] PII 포함 데이터 업로드 → G0_PII 미니 게이트 발동
- [ ] `docker inspect` 컨테이너들에 `ReadonlyRootfs`, `CapDrop=[ALL]` 확인
- [ ] /auth/login 6회 연속 실패 시 429 응답
- [ ] security_audit_log 신규 24h 이내 INSERT ≥ 50건

---

## ⚠️ 주의사항

- Vault dev 모드는 데이터 영속화 안 됨. 재시작 시 시드 재실행 필요
- pg_crypto 컬럼 암호화는 검색 효율 저하 — 인덱스 가능한 hash 컬럼 별도 생성 (이메일은 lower + sha256 인덱스)
- Argon2 파라미터는 하드웨어에 맞게 튜닝 (memory_cost 64MB는 1초 미만)
- 프롬프트 인젝션 정규식은 false positive 가능 — 사용자에게 "차단됨" 명확히 표시 후 재입력 유도
- TLS 1.3 인증서 자동 갱신은 운영 환경에서 cert-manager 또는 acme.sh 사용
- 침투 테스트는 격리된 dev 환경에서만 (운영 트래픽에 영향 X)

---

## 🆕 v2.2 보강 (감사 보고서 2026-05-19 반영)

> 출처: `ADA_v2_감사보고서.docx`. 본 섹션이 v2.1 본문과 충돌 시 **v2.2가 우선**한다.

### 1) Day-C 와 강결합 — 보강 6항목

Day-C(보안 보강) 신설로 다음 항목이 Day17 베이스라인을 보강한다:

- **mTLS** — 내부 서비스 6종 인증서 발급·배포 (R-703).
- **MLflow 인증** — basic-auth 또는 OAuth-proxy (R-704).
- **MFA (TOTP)** — admin/service 의무 (R-705).
- **SBOM + cosign + Trivy** — CI 통합 (R-706).
- **JWT RS256** — HS256 사용 금지 (R-707).
- **Indirect prompt injection** — 데이터 추출 텍스트 sanitize (R-708).
- **pybreaker + Rate limit** — 외부 API 호출 의무 (R-709).

### 2) 침투 50종 실제 페이로드
- OWASP ZAP + Nuclei templates 자동 스캔으로 보강.
- Zip bomb 은 디스크 폭발 위험 → `max_unzip_size=100MB` 가드 단위 테스트로 대체.

### 3) Vault Dev 모드 폐지 (R-903, Day-A 연계)
- v2.2 부터 Raft 모드 필수. Dev 모드 사용 시 ruff 룰 위반.

### 4) Secret rotation 무중단
- JWT 30일 회전 시 grace period 24h + 진행 중 잡 토큰 추적 + 만료 24h 전 알림.

### 5) Falco + AppArmor (Day-C)
- 워커 컨테이너 비정상 syscall·외부 IP 연결 탐지.

### 완료 기준 추가
- [ ] 6개 mTLS 핸드셰이크 통과
- [ ] MFA 미설정 admin 로그인 거부
- [ ] OWASP ZAP 스캔 critical 0건
- [ ] Vault Raft snapshot 정기 생성

---

## 🧰 v2.3 도구 보강 (도구 카탈로그 2026-05-19 반영)

> 출처: `TOOL_CATALOG_2026.md`. 본 섹션은 Day-D / Day-E / v3_backlog 의 도구를 본 Day 의 코드 위치에 매핑한다.

### 적용 도구
- **LLM Guard** (🔴 Day-D §2) — Day17 베이스라인의 INJECTION_PATTERNS 앞단 강화. PromptInjection·Anonymize·BanCode·Toxicity·TokenLimit 스캐너.
- **Guardrails AI** (🟡 Day-E §1) — 출력 스키마 강제. 27 에이전트 중 LLM 사용 11개 모두 schema 정의.

### Day-C 와의 관계
- Day-C(보안 보강): mTLS·MFA·SBOM·JWT RS256·회로차단기.
- Day-D §2(LLM Guard): 콘텐츠 보안(인젝션·PII·독성).
- Day-E §1(Guardrails): 구조 보안(스키마·할루시네이션).
- 셋이 **3중 방어** 구성 (전송·콘텐츠·구조).

### 룰 의무화
- R-1002: 사용자 입력 sanitize = LLM Guard 우선 → ADA 정규식 폴백.
- R-1005: 모든 게이트 LLM 응답 = Guardrails schema 검증 통과 의무.

---

# 📦 통합본 (v2.4) — 원래 Day-A: 백업·DR·복구 인프라

> 통합일: 2026-05-19 (v2.4)
> 원래 `Day-A_백업및DR인프라.md` 의 본문 전체. 신설 Day-A 파일은 v2.4 부터 본 Day17 안의 § 섹션으로 흡수되었다.
> 백업·DR 은 보안·운영 풀스택의 일부로 본 Day17 에서 단일 권위.


---

# 📦 통합본 (v2.4) — 원래 Day-C: 보안 보강 (mTLS·MFA·SBOM·회로차단기)

> 통합일: 2026-05-19 (v2.4)
> 원래 `Day-C_보안보강.md` 의 본문 전체. 신설 Day-C 파일은 v2.4 부터 본 Day17 안의 § 섹션으로 흡수되었다.
> 보안 풀스택의 자연스러운 보강으로 본 Day17 에서 단일 권위.


---

# 📦 통합본 (v2.4) — 원래 Day-D §2: LLM Guard (보안 가드 통합)

> 통합일: 2026-05-19 (v2.4)
> 원래 `Day-D_도구즉시도입.md §2` 본문. v2.4 부터 본 Day17 보안 풀스택에서 단일 권위.

#### §2. LLM Guard — 보안 가드 통합

#### 2.1 산출물
- `security/llm_guard_pipeline.py` — Input/Output Scanner 묶음
- `security/data_sanitize.py` 보강 — 기존 ADA INJECTION_PATTERNS 정규식 앞에 LLM Guard 우선 적용

#### 2.2 구현

```python
# security/llm_guard_pipeline.py
from llm_guard.input_scanners import (
    PromptInjection, Anonymize, BanCode, Toxicity, TokenLimit
)
from llm_guard.output_scanners import (
    Deanonymize, NoRefusal, Sensitive, Bias, MaliciousURLs
)
from llm_guard.vault import Vault as LGVault

_vault = LGVault()
INPUT_SCANNERS = [
    PromptInjection(threshold=0.85),
    Anonymize(_vault, language="en"),   # 한글은 ADA Presidio 사용
    BanCode(),
    Toxicity(threshold=0.7),
    TokenLimit(limit=4096),
]
OUTPUT_SCANNERS = [
    Deanonymize(_vault),
    Sensitive(),
    Bias(threshold=0.6),
    MaliciousURLs(),
    NoRefusal(),
]

def scan_input(text: str) -> tuple[str, bool, dict]:
    sanitized = text
    results = {}
    for s in INPUT_SCANNERS:
        sanitized, is_valid, score = s.scan(sanitized)
        results[s.__class__.__name__] = {"valid": is_valid, "risk": score}
        if not is_valid:
            return sanitized, False, results
    return sanitized, True, results

def scan_output(prompt: str, output: str) -> tuple[str, bool, dict]:
    sanitized = output
    results = {}
    for s in OUTPUT_SCANNERS:
        sanitized, is_valid, score = s.scan(prompt, sanitized)
        results[s.__class__.__name__] = {"valid": is_valid, "risk": score}
        if not is_valid:
            return sanitized, False, results
    return sanitized, True, results
```

#### 2.3 통합 위치
- `api/middleware/security.py` — `/decision/{job_id}` 사용자 응답에 `scan_input` 우선 적용.
- `agents/base.py` — `_call_llm` 진입 직전 `scan_input(state.user_intent)` + 직후 `scan_output(prompt, llm_response)`.
- 실패 시 audit_log INSERT (severity=warn) + 사용자에게 사유 안내.

#### 2.4 룰 R-1002
사용자 입력 sanitize 경로는 **LLM Guard 우선 → ADA INJECTION_PATTERNS 폴백** 2단계. 둘 다 통과해야 LLM 컨텍스트 진입.

#### 2.5 테스트
- `tests/security/test_llm_guard.py` — 100종 인젝션 페이로드 (Day-C 의 50종 + LLM Guard 샘플 50종) 모두 차단.
- `tests/security/test_pii_anonymize.py` — 영문 PII 마스킹 + 한글은 ADA Presidio 가 보강.

---


---

# 📦 통합본 (v2.4) — 원래 Day-E §1: Guardrails AI (LLM 출력 스키마 강제)

> 통합일: 2026-05-19 (v2.4)
> 원래 `Day-E_도구단기도입.md §1` 본문. v2.4 부터 본 Day17 보안 풀스택의 스키마 강제 영역에서 단일 권위.

#### §1. Guardrails AI — LLM 출력 스키마 강제

#### 1.1 산출물
- `guardrails/rail_specs/` — 27 에이전트별 RAIL 명세 (또는 Pydantic schema)
- `shared/llm/guarded_llm.py` — Anthropic SDK + Guardrails 래퍼

#### 1.2 구현 패턴

```python
# guardrails/rail_specs/analysis_proposer.py
from pydantic import BaseModel, Field
from typing import List

class Proposal(BaseModel):
    title: str = Field(min_length=4, max_length=80)
    why: str = Field(min_length=20, max_length=400)
    plan_outline: List[str] = Field(min_items=2, max_items=6)
    expected_metric: str
    expected_duration_min: int = Field(ge=1, le=120)

class AnalysisProposerOutput(BaseModel):
    proposals: List[Proposal] = Field(min_items=3, max_items=3)
    referenced_past_jobs: List[str]  # KB 인용 ID 강제 (R-501)
```

```python
# shared/llm/guarded_llm.py
from guardrails import Guard
from anthropic import AsyncAnthropic

class GuardedLLM:
    def __init__(self, schema_cls, model="claude-sonnet-4-6"):
        self.guard = Guard.from_pydantic(schema_cls)
        self.client = AsyncAnthropic()
        self.model = model

    async def call(self, prompt: str, max_retries=2):
        for attempt in range(max_retries + 1):
            resp = await self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text
            try:
                validated = self.guard.parse(text)
                return validated
            except Exception as e:
                if attempt == max_retries:
                    raise
                prompt += f"\n\n[VALIDATION_ERROR] 이전 응답이 스키마를 위반했습니다. 정확한 JSON으로 다시 응답하세요. 오류: {e}"
```

#### 1.3 BaseAgent 통합
- BaseAgent._call_llm 이 schema_cls 인자 받음 — schema 가 있으면 GuardedLLM, 없으면 일반 호출(점진 마이그레이션).
- 27 에이전트 중 LLM 사용 11개(Sonnet/Opus) 모두 schema 정의 의무.

#### 1.4 룰 R-1005
모든 게이트(G0~G5) LLM 응답은 Guardrails AI 스키마 검증 통과 후에만 state 반영. 검증 실패 + 2회 재시도 실패 → AutoErrorHandler 로 escalate.

#### 1.5 테스트
- `tests/guardrails/test_schema_enforcement.py` — 잘못된 JSON 반환 시뮬 → 자동 재시도 → 성공.
- `tests/guardrails/test_kb_citation_required.py` — referenced_past_jobs 누락 시 validation fail.

---

