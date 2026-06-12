# G2 헤더 정합 — 기획안 v4 (CS, 2026-06-11)

> v3 까지의 전제 (HEAD = 9f9c210 상태 = 정상) 가 무너짐. **main 브랜치가 진짜 기준**.
> feat/cs 의 frontend/app.py 가 main 보다 447줄 적은 상태 = 의도치 않게 누락.
> 본인 지시: **main 의 누락 코드 복구 + HEAD 로 다시 안 돌아가게 진행**.

---

## 1. 현재 진단 (2026-06-11)

### 1-1. 브랜치 비교

| 항목 | main | feat/cs (현재 HEAD) | 차이 |
|---|---|---|---|
| frontend/app.py 라인 수 | **2153** | **1706** | feat/cs 가 **447줄 부족** |
| git diff main..HEAD | 135 insertions / 584 deletions | | |

→ feat/cs 브랜치의 frontend/app.py 가 main 의 코드 상당 부분이 빠진 상태.

### 1-2. git 상태 손상

- `.git/index` corrupt (`index uses ??? extension`)
- `.git/index.lock` 존재 (권한 부족으로 claude 제거 불가)
- 결과: `git status`, `git diff`, `git checkout`, `git commit` 모두 불가
- claude 권한 = read-only git 명령 (`git show`, `git log`) 만 가능

### 1-3. v3 기획안 전제 무너짐

- v3 = "HEAD(14f454a) = 9f9c210 정상 롤백 상태" 가정
- 실제 = HEAD 자체가 main 대비 447줄 부족한 비정상 상태
- v3 의 라인 번호 (gateHeader = 라인 990 등) 가 실제 파일과 안 맞음

---

## 2. 본인 측 긴급 조치 (Windows)

claude 권한 밖이라 본인이 직접 수행:

```cmd
cd C:\IT\workspace_python\ADA

REM 1) git index + lock 제거
del .git\index
del .git\index.lock

REM 2) index 재생성 (HEAD 기준)
git read-tree HEAD

REM 3) git 상태 확인 (이제 동작해야 함)
git status

REM 4) frontend/app.py 를 main 의 상태로 가져오기
git checkout main -- frontend/app.py

REM 5) 라인 수 확인 (2153 이어야)
wc -l frontend\app.py
```

또는 PowerShell:

```powershell
cd C:\IT\workspace_python\ADA
Remove-Item .git\index, .git\index.lock -Force
git read-tree HEAD
git status
git checkout main -- frontend/app.py
```

---

## 3. main 의 frontend/app.py 진단 (claude 측에서 사전 확인)

main 의 frontend/app.py 가 이미 어떤 카테고리 매핑을 갖고 있는지 확인 필요:

- `GATE_HEADER_BY_CATEGORY` 존재 여부
- `gateHeader()` 함수 시작 라인
- `modalHtml()` 함수 시작 라인
- `TOPIC_HEADER_BY_CATEGORY` 존재 여부

본인 측 조치 (§2) 완료되면 → claude 가 main 기준 파일에서 위 항목 grep + 작업 범위 재산정.

---

## 4. 1차 구현 범위 (변경 없음)

본인 지시 그대로 — **C-1 + C-2 + C-3 = 3 단계 변경**:

| 단계 | 대상 | 파일 |
|---|---|---|
| C-1 | G2 = cur=1 static 헤더 카테고리별 매핑 | frontend/app.py |
| C-2 | G2→G3 = cur=2 loading 헤더 카테고리별 매핑 | frontend/app.py |
| C-3 | G2→G3 팝업 = cur=2 modal 안의 h2+en+desc 를 C-2 와 동기화 | frontend/app.py |

**main 의 기존 카테고리 매핑과 충돌 가능성** → main 의 GATE_HEADER_BY_CATEGORY 가 이미 있으면 그걸 base 로 + cur=1/2 부분 본인 의도대로 정정.

---

## 5. 작업 분할 원칙 (v3 유지)

1. **한 변경 = 작은 단위** (Edit 도구 잘림 회피 → bash awk/heredoc 사용)
2. **매 변경 후 syntax + tail 검증** (EOF 손실 즉시 감지)
3. **claude 는 commit 안 만듦** — 본인이 직접 commit
4. **commit 후 docker 재빌드** — 본인 수행
5. **회귀 발생 시 즉시 직전 상태로 복원** — 디버깅보다 정상화 우선

---

## 6. Docker 재빌드 + 화면 확인 절차 (v3 유지)

```bash
docker compose -f docker/docker-compose.yml build ada-frontend
docker compose -f docker/docker-compose.yml up -d --no-deps ada-frontend
# 또는 단축
docker restart ada-frontend
```

브라우저 Ctrl+Shift+R 강제 새로고침 후 화면 확인.

---

## 7. 정독 절차 (v3 유지, 매 시작 전 강제)

1. 프로젝트 전체 정독
2. 본 기획안 정독
3. 정독 결과 1줄 요약 보고 후 코드 변경 시작

---

## 8. 본인 확인 받을 것 (진행 직전)

1. **§2 본인 측 조치 완료** (git index 복구 + frontend/app.py 를 main 으로 가져오기) → 완료 확인 받기
2. **§3 main 의 frontend/app.py 진단** → claude 가 grep 결과 보고 후 본인 OK
3. **§4 1차 구현 범위 (C-1+C-2+C-3)** 확정?
4. **§5 작업 분할 원칙** OK?

---

## 9. 영역 점검 (v3 유지)

| 항목 | 상태 |
|---|---|
| 본인 영역 (CS handlers timeseries) | 본 작업과 무관 — 안 건드림 |
| HJ 위임 영역 (frontend/app.py, api/routes/pipeline.py) | 본 작업 대상 |
| G1 (cur=0) | **건드리지 않음** (본인 명시) |
| .env / docker-compose / Dockerfile | **변경 없음** |
| requirements / pyproject | **변경 없음** |
| 새 의존성 추가 | 없음 |
| 마이그레이션 | 없음 |
| PipelineState 필드 추가 | 없음 |

---

## 10. 변경 이력

- v1 (2026-06-11 오전): 초안 작성 (트랙 A/B/C 분리)
- v2: 회귀 발생 → 롤백 결정 + 작업 분할 원칙 강제 추가
- v3: 롤백 완료 (14f454a = 9f9c210 상태) 가정, 1차 범위 한정 + docker 재빌드 절차
- **v4 (2026-06-11 오후)**: **v3 전제 무너짐** — main 대비 447줄 부족 발견 + git index corrupt. main 기준으로 재설계. 본인 측 긴급 조치 (§2) 우선.
