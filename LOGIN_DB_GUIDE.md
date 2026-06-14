# 🔐 ADA 로그인 & DB 완전 정복 가이드

> 초보 서버 관리자용 · 2026-06-14 · 구글 로그인 v1 기준
> "로그인하면 DB에 뭐가 쌓이고, 그걸 어떻게 들여다보는가"를 처음부터 끝까지 정리했습니다.

---

## 0. 지금 무엇이 완성됐나

사용자가 **구글 계정으로 로그인/회원가입**할 수 있고, 그 과정의 **계정 정보·로그인 기록이 전부 DB에 자동 저장**됩니다.

- 비밀번호는 **저장하지 않습니다** (구글이 본인 확인을 대신 해주니까요)
- 처음 누르면 **자동 가입**, 다음부턴 **로그인** — 구글 로그인은 이 둘이 한 흐름이에요

---

## 1. 한눈에 보는 전체 그림

```
[사용자]  "Google 계정으로 로그인" 클릭
   │
   ▼
[프론트(Streamlit, 8501)]  →  전체 창이 구글로 이동
   │
   ▼
[구글]  본인 인증 + 동의
   │
   ▼
[백엔드(FastAPI, 8000/api)]  /auth/google/callback
   │   ① 구글이 준 정보 검증 (이메일·이름·구글 고유ID)
   │   ② DB 조회/저장 ←──────────────┐
   │   ③ 로그인 토큰(JWT) 발급         │
   ▼                                  │
[프론트]  로그인 완료 → 스튜디오 진입   │
                                      │
                          ┌───────────┴───────────┐
                          ▼                       ▼
                  [PostgreSQL DB]          여기에 다 쌓입니다
```

핵심: **화면(8501)** 과 **두뇌(api, 8000)** 와 **창고(DB)** 가 따로 있고, 로그인할 때마다 창고(DB)에 기록이 쌓입니다.

---

## 2. DB에 저장되는 3가지 (테이블)

DB 안에 표 3개가 있습니다. 각각 역할이 달라요.

| 테이블 | 한 줄 설명 | 들어가는 것 |
|---|---|---|
| **users** | 누가 우리 서비스 회원인가 | 이메일, 이름, 권한(role), 가입일, 마지막 로그인 시각 |
| **oauth_accounts** | 그 회원이 어떤 구글 계정과 연결됐나 | 제공자(google), 구글 고유ID, 이메일 |
| **security_audit_log** | 언제·어디서 로그인했나 (출입 기록) | 로그인 성공/실패, 시각, 접속 IP, 브라우저 정보 |

### 더 자세히

**① users — 회원 명부**
- `email` : 로그인 아이디 (구글 이메일)
- `name` : 구글 프로필 이름
- `role` : 권한 등급 (기본 `analyst`)
- `password_hash` : **구글 로그인 사용자는 비어 있음**(비번이 없으니까)
- `is_verified` : 이메일 인증 여부 (구글 = 자동 true)
- `last_login_at` : 마지막 로그인 시각
- `created_at` : 가입 시각

**② oauth_accounts — 구글 연결 고리**
- `provider` : `google`
- `provider_account_id` : 구글이 주는 **변하지 않는 고유 번호**(sub). 이메일이 바뀌어도 같은 사람으로 인식하게 해주는 진짜 열쇠
- `email` : 연동 당시 구글 이메일

**③ security_audit_log — 출입 기록**
- `event_type` : `login` / `logout` 등
- `result` : `success` / `failure` / `blocked`
- `ip_address` : 접속한 IP
- `user_agent` : 어떤 브라우저/기기인지
- `created_at` : 그 일이 일어난 시각
- ⚠️ 비밀번호·토큰 같은 민감정보는 **여기 안 남깁니다**

---

## 3. 로그인 한 번 = DB에서 일어나는 일

사용자가 구글 로그인을 1회 하면, 순서대로:

1. 구글이 이메일·이름·고유ID(sub)를 우리 백엔드에 넘김
2. `oauth_accounts`에서 그 구글 고유ID를 찾음
   - **있으면** → 기존 회원, 바로 로그인
   - **없으면** → 처음 온 사람:
     - 같은 이메일의 `users`가 있으면 그 계정에 **연결**
     - 없으면 `users`에 **새 회원 생성**
     - `oauth_accounts`에 **연결 기록 생성**
3. `users.last_login_at`을 지금 시각으로 갱신
4. `security_audit_log`에 **로그인 성공 기록**(IP·브라우저 포함) 추가
5. 로그인 토큰(JWT) 발급 → 화면이 스튜디오로 진입

즉 **새 사람이 처음 로그인하면 users 1줄 + oauth_accounts 1줄 + audit 1줄**이, **기존 사람이 로그인하면 audit 1줄**이 늘어납니다.

---

## 4. ⭐ DB 들여다보는 법 (제일 중요)

### 방법 1 — 요약 한 방에 보기 (가장 쉬움)

우리가 만든 점검 스크립트예요. 숫자로 요약해줍니다.

```powershell
docker exec ada-api python /app/scripts/dev/verify_oauth_db.py
```

출력 예시:
```
• 전체 사용자(users)         : 3 명
• 소셜 연동(oauth_accounts)  : 3 건  (구글: 3)
• 로그인 성공 기록(audit)    : 7 건
```
→ 로그인할 때마다 이 숫자가 늘면 정상입니다.

### 방법 2 — DB에 직접 들어가서 보기 (상세)

진짜 데이터를 한 줄 한 줄 보고 싶을 때. PostgreSQL에 접속합니다.

```powershell
docker exec -it ada-postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```
→ `ada=#` 같은 프롬프트가 뜨면 접속 성공. 이제 아래 명령들을 쳐보세요.

**자주 쓰는 조회 (그대로 복사해서 쓰세요):**

```sql
-- 테이블 목록 보기
\dt

-- 가입한 회원 전체 (최근 가입 순)
SELECT email, name, role, is_verified, created_at
FROM users ORDER BY created_at DESC;

-- 구글 연동 현황
SELECT provider, email, created_at
FROM oauth_accounts ORDER BY created_at DESC;

-- 최근 로그인 기록 20건 (언제·어디서·성공여부)
SELECT created_at, result, ip_address
FROM security_audit_log
WHERE event_type = 'login'
ORDER BY created_at DESC LIMIT 20;

-- 회원이 몇 명인지 숫자만
SELECT count(*) FROM users;

-- 빠져나가기
\q
```

> 💡 `psql` 안에서 한글이 깨지면 무시해도 돼요(데이터는 멀쩡). 명령 끝에는 꼭 **세미콜론(;)** 을 붙이세요.

---

## 5. 자주 쓸 관리 명령어

```powershell
# 컨테이너 상태 (다 떠 있는지)
docker ps

# api 최근 로그 (에러 확인할 때)
docker logs ada-api --tail 50

# 화면(프론트) 다시 시작 (코드 바꾼 뒤)
docker restart ada-frontend

# 구글 열쇠가 api 안에 들어갔는지 확인 (값은 가려서 나옴)
docker exec ada-api sh -c 'echo CLIENT_ID=${GOOGLE_CLIENT_ID:+있음}; echo SECRET=${GOOGLE_CLIENT_SECRET:+있음}'
```

---

## 6. 문제 생기면 (지금까지 겪은 것 정리)

| 증상 | 원인 | 해결 |
|---|---|---|
| 팝업에 `GOOGLE_CLIENT_ID not set` | .env에 구글 값이 없거나 키 이름 오타 | `.env`에 `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`(← `CLIENT_` 꼭!) 넣기 |
| .env 고쳤는데 반영 안 됨 | `docker restart`는 .env를 다시 안 읽음 | **재생성**: `docker compose --profile core up -d --force-recreate api` |
| `oauth_accounts does not exist` | 새 마이그레이션이 컨테이너에 없음 | api 이미지 **재빌드** (켜질 때 자동 적용됨) |
| 구글 버튼이 깨져 보임 | 작은 창/iframe 안에서 구글이 안 열림(구글 정책) | 전체 창으로 이동(이미 적용) |
| 화면 코드 바꿨는데 그대로 | 프론트 재시작·새로고침 안 함 | `docker restart ada-frontend` + 브라우저 `Ctrl+Shift+R` |

### ⚠️ 꼭 기억할 두 가지
1. **`restart` ≠ `재생성`**: `.env`(환경변수)를 바꿨으면 `restart`로는 안 되고 `up --force-recreate`로 컨테이너를 다시 만들어야 새 값이 들어갑니다.
2. **컨테이너 안 코드 ≠ 내 PC 코드**: 마이그레이션·파이썬 의존성(authlib 등)은 **이미지에 구워지므로** 새로 만들면 재빌드가 필요합니다. (반면 `frontend/app.py`는 실시간 연결돼 있어 재시작만으로 반영)

---

## 7. 로컬(내 PC) vs 운영(VPS)

|  | 로컬 PC | VPS (ada-aiagent.com) |
|---|---|---|
| 접속 | localhost:8501 | https://ada-aiagent.com |
| 코드 | 내가 수정한 최신 | **git pull 해야 받음** |
| .env | localhost용 | ada-aiagent.com용 |
| redirect URI | `http://localhost:8000/auth/google/callback` | `https://ada-aiagent.com/api/auth/google/callback` (← `/api` 포함!) |

**VPS에 올리는 순서:**
```
1. (로컬에서) git add -A && git commit -m "..." && git push
2. ssh ada@115.68.216.191
3. cd /opt/ada && git pull
4. nano .env  → GOOGLE_CLIENT_ID / SECRET / REDIRECT_URI(/api) / FRONTEND_URL
5. cd docker && docker compose --profile core up -d --force-recreate api
   (켜질 때 마이그레이션·authlib 자동 반영)
```

---

## 8. 보안 — 꼭 지킬 것

- 🔑 `.env`는 **절대 git에 안 올라갑니다**(.gitignore로 막혀 있음). 구글 Secret 같은 비밀이 들었으니까요.
- 🔑 Client Secret은 **채팅·메신저·코드에 붙이지 마세요.** "넣었다"고만.
- 🔑 우리는 사용자의 **비밀번호를 저장하지 않습니다** (구글이 인증 대행).
- 🔑 "구글 로그인 가능" ≠ "우리 서비스 전체 사용 가능". 누가 뭘 할 수 있는지는 `role`(권한)으로 따로 통제합니다.

---

## 9. 앞으로 할 일

- [ ] **VPS 배포** — 위 7번 순서대로 (팀이 ada-aiagent.com에서 테스트하려면 필수)
- [ ] **앱 게시(Publish)** — 구글 콘솔 "대상"에서. 그래야 테스트 사용자 100명 제한이 풀리고 누구나 로그인 가능 (우리는 기본 권한만 써서 구글 심사 불필요)
- [ ] **권한(role) 설계** — 신규 가입자 기본 권한, 관리자 구분 등
- [ ] **v2 (선택)** — 이메일+비밀번호 가입, 이메일 인증, 비번 재설정 (메일 발송 서비스 필요)

---

## 부록 — 우리가 만든/고친 파일

| 파일 | 역할 |
|---|---|
| `frontend/app.py` | "시작하기 → 로그인 팝업 → 구글 버튼" 화면 |
| `api/routes/auth.py` | `/auth/google`, `/auth/google/callback` 로그인 처리 |
| `ada/db/models.py` | users 확장 + oauth_accounts 테이블 정의 |
| `migrations/versions/005_oauth_login.py` | DB에 oauth_accounts 테이블 만드는 변경 기록 |
| `ada/core/config.py` | 구글 설정값 읽기 |
| `requirements/api.txt` | `authlib`(구글 OAuth 라이브러리) 추가 |
| `scripts/dev/verify_oauth_db.py` | **DB 상태 눈으로 확인하는 점검 도구** |
```
