# ADR-009 — Day 5: JWT RS256 전환 + Vault 키 로딩

> **Status**: Accepted (HJ)
> **Date**: 2026-05-28 (hj-day5)
> **Owners**: HJ
> **Related**: ADR-004 (Vault Raft), `ada/security/jwt.py`, `scripts/security/jwt_keygen.sh`
> **Contract Day**: No — 본 변경은 토큰 발급 측 내부 구현만 바꾼다. 클라이언트 측 계약 (Authorization Bearer header) 변경 없음.
> **TEAM_10DAY_SCHEDULE 매핑**: Day 5 HJ — `RS256 JWT 전환 + Vault 에서 키 로딩 (현재 HS256 dev)`. 단독 수정 파일: `ada/security/jwt.py`, `scripts/security/jwt_keygen.sh`. DoD: `decode_token RS256 통과 단위 테스트`.

---

## 1. 배경

Day 1~4 까지의 dev 환경은 HS256 + `settings.jwt_secret` (기본값 `"dev-jwt"`) 로 대칭키 서명을 사용했다. 운영 가까이 가면서 다음 두 가지 요구가 떠올랐다:

1. **비대칭키화** — 마이크로서비스 다수에 토큰 검증이 분산될 때 공개키만 배포하면 충분하도록 RS256 으로 전환
2. **키 출처 일원화** — `.env` 의 평문 secret 대신 Vault (ADR-004 Raft) 에서 키를 로딩

dev 호환성을 깨지 않고, 토큰 유효기간(`JWT_EXPIRE_MIN=60`) 동안 발급된 기존 HS256 토큰을 검증 실패시키지 않은 채 전환해야 한다.

## 2. 결정

### 2.1 알고리즘 선택 우선순위 (sign)

`ada/security/jwt.py::_effective_algo()` 가 다음 순으로 결정한다:

1. `settings.jwt_algo == "RS256"` **그리고** `_load_rs_keys()` 가 `private_key` 를 반환 → **RS256**
2. 그 외 모든 경우 → **HS256** (dev fallback)

즉 `.env` 에 `JWT_ALGO=RS256` 만 두고 키 로딩이 실패하면 자동으로 HS256 으로 떨어진다 — 운영 미설정으로 인한 503 회피.

### 2.2 키 로딩 폴백 체인

`_load_rs_keys()` 는 `lru_cache(1)` 로 캐시되며 다음 순으로 시도:

| 우선 | 소스 | 형태 |
|---|---|---|
| 1 | Vault KV v2 — `secret/jwt/rs256` | `{"private_key": "<PEM>", "public_key": "<PEM>"}` |
| 2 | 환경변수 | `JWT_PRIVATE_KEY`, `JWT_PUBLIC_KEY` (PEM 통째) |
| 3 | (없음) | 빈 dict → HS256 강제 |

Vault 응답이 비거나 예외 발생 시 즉시 env 시도 — Vault 장애가 토큰 발급 장애로 전파되지 않음.

### 2.3 검증 (decode) 측의 dual-algorithm

`decode_token()` 은 `(key, algo)` 쌍 리스트를 만들어 순서대로 시도한다:

1. RS public key 가 있으면 `(pub, "RS256")` 먼저
2. `(settings.jwt_secret, "HS256")` 폴백

이 구조 덕분에 **전환 시점에 이미 발급되어 떠다니는 HS256 토큰**과 **전환 후 발급된 RS256 토큰**이 동시에 통과한다. 운영 전환 윈도우(= JWT_EXPIRE_MIN 1시간) 안에 자연 마이그레이션.

### 2.4 _verify_keys 데드코드 제거

이전 버전에 정의만 되어 있던 `_verify_keys()` 헬퍼는 호출처가 없어 Day 5 에서 제거. 동일 책임은 `decode_token()` 인라인 pairs 빌더로 대체.

---

## 3. 실행 절차 (운영 전환 SOP)

### 3.1 키 발급

```bash
# 1) 키쌍 생성 (현재 디렉토리에 jwt_private.pem / jwt_public.pem)
bash scripts/security/jwt_keygen.sh

# 2) Vault 에 동시에 저장하려면
bash scripts/security/jwt_keygen.sh --vault
```

### 3.2 Vault 경로 확인

```bash
vault kv get secret/jwt/rs256
# private_key=<PEM>, public_key=<PEM>
```

placeholder 가 없으면 `_load_rs_keys()` 가 Vault 404 로 떨어져 env 폴백을 시도한다. `scripts/vault_seed.sh` 가 Day 5 부터 빈 placeholder 를 시드한다 (실제 키는 jwt_keygen.sh 가 덮어쓴다).

### 3.3 환경변수 전환

```bash
# .env (운영)
JWT_ALGO=RS256
# JWT_PRIVATE_KEY, JWT_PUBLIC_KEY 는 Vault 사용 시 생략 가능
```

### 3.4 캐시 무효화

서비스 재시작 없이 키 로테이션을 반영하려면:

```python
from ada.security.jwt import reset_key_cache
reset_key_cache()
```

---

## 4. 키 로테이션 SOP (3-step)

1. **새 키 발급** — `jwt_keygen.sh --vault` 로 `secret/jwt/rs256` 덮어쓰기
2. **dual-verify 윈도우** — 구 토큰 만료까지 `JWT_EXPIRE_MIN` 분 대기. 이 동안 발급은 신규 키, 검증은 양쪽 키로 통과
3. **구 키 폐기** — Vault 의 이전 version 을 destroy. KV v2 metadata API:
   ```bash
   vault kv metadata delete secret/jwt/rs256  # 옵션: 전체 폐기
   ```

> ⚠️ 운영에선 새 키 발급과 구 키 폐기 사이에 반드시 `JWT_EXPIRE_MIN` 분 이상의 간격을 둘 것. 즉시 폐기 시 떠다니는 토큰 전체가 401.

---

## 5. 위험 / 트레이드오프

| 위험 | 완화 |
|---|---|
| Vault 장애 시 토큰 발급 실패 | `_load_rs_keys()` 예외 흡수 → env 폴백 → HS256 폴백. 발급 자체는 절대 막히지 않음 |
| dual-verify 윈도우 동안 HS256 토큰도 통과 | 의도된 호환성. 윈도우 종료 후 `settings.jwt_secret` 을 무의미한 값으로 바꿔 사실상 비활성화 가능 |
| `cryptography` 패키지 미설치 환경에서 RS256 sign 실패 | `python-jose[cryptography]` 를 `requirements/api.txt` 에 명시. pytest 는 `pytest.importorskip("Crypto")` 로 스킵 |
| `lru_cache` 때문에 키 갱신이 즉시 반영 안 됨 | `reset_key_cache()` 공개 + 워커 재시작 매뉴얼 |

---

## 6. 단위 테스트 (DoD)

`tests/test_day5_rs256_jwt.py` 5 케이스:

| # | 케이스 | DoD 충족 |
|---|---|---|
| 1 | `test_keygen_script_exists` | 스크립트 존재 + `bash -n` syntax 통과 |
| 2 | `test_hs256_roundtrip` | HS256 호환성 (회귀 방지) |
| 3 | **`test_rs256_roundtrip_via_env`** | 환경변수 RS 키로 sign→decode, 헤더 `alg=RS256` 검증 — **DoD 핵심** |
| 4 | `test_decode_accepts_both_when_rs_available` | RS 환경에서 HS 토큰 디코드 통과 |
| 5 | `test_vault_priority_over_env` | `_load_rs_keys()` 우선순위 검증 |

추가 정적 검증: `python scripts/dev/verify_day5.py` — L1~L5 13 체크.

---

## 7. 미해결 / Day 9+ 추적

- **JWKS endpoint 노출** — 외부 서비스가 공개키 fetch 할 수 있도록 `/auth/jwks.json` 라우트 추가. ADR-009 의 범위 외, Day 9 (`outputs/base.py` 확장과 무관한 별도 작업).
- **JWT 캐시 메트릭** — Vault 호출 빈도 Prometheus counter 추가. 운영 후 필요 시.
- **키 회전 자동화** — Vault audit log + cron 으로 N일마다 자동 회전. 시점 미정.
