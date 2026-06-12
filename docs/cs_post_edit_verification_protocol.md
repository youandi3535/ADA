# CS 수정 작업 후 표준 점검·조치 프로토콜

> 본인 요청: 모든 코드 수정 작업이 끝나면 점검·조치 후, 본인은 웹 대시보드에서 **F5 한 번만** 누르면 모든 수정 사항이 적용되게 준비.

---

## 1. 표준 점검 8항목 (수정 완료 후 매번 실행)

| # | 점검 항목 | 명령/방법 | 통과 기준 |
|---|---|---|---|
| 1 | **코드 문법** | 컨테이너 내 `python -m py_compile` 또는 `ast.parse` | `COMPILE_OK` ✓ |
| 2 | **마운트 동기화** | 호스트↔컨테이너 SHA256 비교 | 완전 일치 ✓ |
| 3 | **변경 실제 반영** | 컨테이너 내 `grep` 으로 새 코드/주석 확인 | 새 코드 발견 ✓ |
| 4 | **구·중복 컨테이너 없음** | `docker ps -a` (포트·이미지) | 단 1개 컨테이너, exited/중복 0 ✓ |
| 5 | **재시작 반영** | `StartedAt` 확인 (수정 시각보다 뒤) | 재시작 시각 갱신 ✓ |
| 6 | **서버 메모리 캐시 초기화** | 재시작으로 `@st.cache_*` 자동 초기화 | 별도 조치 불필요 ✓ |
| 7 | **Redis 캐시 점검** | `ada:stage_partial:{job_id}` / `ada:gate_data:{job_id}` 등 키+TTL | job 별 신규 키, 옛 데이터 영향 없음 ✓ |
| 8 | **서비스 응답** | `/_stcore/health` (frontend) / `/healthz` (api) | HTTP 200 ✓ |

### 추가 (필요 시)

- **로그 확인** — `docker logs --tail 50 ada-frontend` 에 error/warning 없음
- **brand-new job 테스트** — 새 job 으로 화면 1회 확인 (옛 캐시 영향 차단)

---

## 2. 변경 범위에 따른 컨테이너 처리

| 변경 파일 | 처리 방법 | 본인 측 명령 |
|---|---|---|
| `frontend/app.py` | bind mount → streamlit hot-reload | `docker restart ada-frontend` |
| `agents/*.py` (data_profiler, schema_validator 등) | bind mount X → 이미지 재빌드 필수 | `docker compose build ada-api ada-worker && docker compose up -d --no-deps ada-api ada-worker` |
| `api/routes/*.py` | bind mount → restart 만 | `docker restart ada-api` |
| `agents/handlers/timeseries/*.py` (CS 영역) | bind mount X → 재빌드 | `docker compose build ada-worker && docker compose up -d --no-deps ada-worker` |
| `requirements/*.txt` / `Dockerfile.*` | 완전 재빌드 (`--no-cache` 권장) | `docker compose build --no-cache ada-api ada-worker ada-frontend` |
| `.env` / `docker-compose.yml` | 컨테이너 재생성 | `docker compose down && docker compose up -d` |

---

## 3. claude 가 매 수정 후 자동 수행 (본인 무개입)

수정 완료 직후 claude 가 자동으로:

1. **코드 syntax 검증** (`bash python -c "import ast; ast.parse(...)"`)
2. **EOF 무결성** (Read 로 마지막 5줄 확인 — `_flow_screen()` 등)
3. **라인 수 확인** (`wc -l` 또는 Read offset 비교)
4. **변경 위치 grep** — 박은 주석 (`CS 2026-06-11`) 또는 코드 발견 확인
5. **회귀 위험 점검** — 다른 함수·테스트 영향 grep

위 5가지 끝난 후 본인에게 **간결한 점검 결과 보고** + **본인 측 명령 (재빌드/restart) 안내**.

---

## 4. 본인 측 행동 (F5 한 번)

claude 의 점검·보고 후 본인은:

1. **claude 가 안내한 docker 명령 한 번 실행** (변경 범위에 따라 restart 또는 build)
2. **브라우저 F5** 새로고침 (Streamlit 의 모달 HTML 은 매 실행마다 서버 측 재생성. 일반 새로고침으로 충분. **하드 리프레시 (Ctrl+Shift+R) 불필요**)
3. 화면 확인

= 본인 측 작업 ≤ 3 단계, ≤ 30초.

---

## 5. 보고서 템플릿 (claude 자동 출력)

```
## 점검·조치 결과 보고

| # | 점검 항목 | 결과 |
|---|---|---|
| 1 | 코드 문법 | ✓ syntax OK |
| 2 | 변경 위치 확인 | ✓ 라인 N 박힘 |
| 3 | EOF 무결성 | ✓ `_flow_screen()` 정상 |
| 4 | 영역 침범 점검 | ✓ HJ 위임 영역 안 |
| 5 | 회귀 위험 | ✓ 테스트 영향 없음 |

**본인 측 명령**:
```cmd
[변경 파일 종류에 맞는 docker 명령]
```

**본인 행동**: 위 명령 + 브라우저 F5
```

---

## 6. 메모리 저장 (표준 규칙)

본 프로토콜은 **모든 향후 수정 작업에 자동 적용** — 본인이 별도 요청 안 해도 claude 가 매 수정 후:
1. §3 의 5가지 자동 검증
2. §5 의 보고서 출력
3. §2 의 변경 범위에 맞는 본인 측 명령 안내

본인 측은 §4 의 3단계 (명령 + F5 + 화면 확인) 만.

---

## 7. 예외 처리

| 상황 | 조치 |
|---|---|
| syntax 깨짐 | 즉시 복원 (`git checkout HEAD -- file`) + 재시도 |
| EOF 잘림 | 즉시 복원 + bash heredoc + awk 로 재박기 |
| docker build 실패 | error 로그 본인에게 보고 + 원인 진단 |
| 회귀 발견 | 즉시 직전 commit 으로 롤백 |
| `.git/index.lock` 권한 문제 | 본인 측 windows 에서 lock 해제 명령 안내 |

---

## 8. 본 프로토콜 적용 시점

**작성 완료 시점 이후 모든 수정 작업** (cur=3·4·5 매핑, user_choice plug-in, 주제 선정 팝업, Dockerfile 최적화 등 2차 작업 전부 포함).

각 수정 단위 (commit) 후 §3 자동 + §5 보고 + §4 본인 안내.
