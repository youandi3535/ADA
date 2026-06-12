# 수정 후 점검·리로드 표준 절차 (ADA)

> HJ 지시 표준 규칙. **모든 코드 수정이 끝나면** 이 절차를 돌린 뒤,
> 사용자는 웹 대시보드에서 **새로고침(F5) 한 번**이면 모든 수정이 반영된다.
> 자동화 스크립트: `scripts/dev/verify_and_reload.sh`

---

## 한 줄 사용법

```bash
bash scripts/dev/verify_and_reload.sh <수정한_파일들...> [옵션]
```

수정 파일이 마운트된 **실행 중 컨테이너를 자동으로 찾아** 점검·재시작한다.
하드코딩 맵이 없으므로 compose가 바뀌어도 자동 추종한다.

### 자주 쓰는 예시

```bash
# 프론트엔드(Streamlit) 수정
bash scripts/dev/verify_and_reload.sh frontend/app.py

# PDF 산출물(워커) 수정 — 여러 파일 한 번에
bash scripts/dev/verify_and_reload.sh \
  outputs/architect/skeletons/report_skeleton.py \
  outputs/carriers/pdf_carrier.py

# 제거한 코드가 정말 사라졌는지 확인
bash scripts/dev/verify_and_reload.sh outputs/pdf.py --grep-absent "_MAX_LINES"

# 추가한 함수가 컨테이너에 들어갔는지 확인
bash scripts/dev/verify_and_reload.sh frontend/app.py --grep-present "def _stageBox"

# 재시작 없이 점검만
bash scripts/dev/verify_and_reload.sh outputs/pdf.py --no-restart
```

---

## 8가지 점검 항목 (HJ 보고서 양식과 동일)

| # | 점검 항목 | 방법 | 통과 기준 |
|---|---|---|---|
| 1 | 코드 문법 | 호스트 `py_compile` | COMPILE_OK |
| 2 | 마운트 동기화 | 호스트↔컨테이너 **SHA256** 비교 | 완전 일치 |
| 3 | 변경 반영 | 컨테이너 내부 `grep` (`--grep-present/absent`) | 의도대로 있음/없음 |
| 4 | 잔여·중복 컨테이너 | `docker ps -a` | exited/dead/중복 없음 |
| 5 | 재시작 반영 | `docker inspect StartedAt` 갱신 확인 | 새 시각으로 갱신 |
| 6 | 메모리 캐시 | 재시작으로 `@st.cache_*`·프로세스 메모리 자동 초기화 | 별도 조치 불필요 |
| 7 | Redis 캐시 | `ada:stage_partial:{job_id}` job별 키+TTL 600s | 옛 데이터 영향 없음 |
| 8 | 서비스 응답 | frontend `/_stcore/health`, api `/health`, 워커 Running | HTTP 200 / 정상 |

끝나면 **점검·조치 결과 보고서** 표가 콘솔에 출력되고,
모두 통과 시: `→ 웹 대시보드에서 새로고침(F5) 한 번이면 모든 수정이 반영됩니다.`

---

## 왜 재시작이 필요한가 (반영 원리)

| 대상 | 컨테이너 | 마운트 | 반영 방식 |
|---|---|---|---|
| Streamlit UI | `ada-frontend` | `../frontend:/app/frontend` | 파일은 즉시 보이나 `runOnSave` 꺼져 있음 → **재시작**으로 새 코드+캐시 초기화. 이후 F5 |
| PDF·산출물 | `ada-worker-output` | `../outputs` 등 | **Celery는 파이썬 핫리로드 불가 → 반드시 재시작** |
| 파이프라인/학습 | `ada-worker-pipeline/harness/training` | `../agents` `../ada` 등 | 동일 — 재시작 필요 |
| API | `ada-api` | `../api` 등 | uvicorn reload 미사용 시 재시작 |

> 핵심: **마운트는 "파일을 보이게" 할 뿐, "메모리에 로드된 코드"를 바꾸지 않는다.**
> 특히 워커(Celery)는 이미 import 된 모듈을 계속 쓰므로 재시작이 유일한 반영 경로다.

---

## 영역별 적용 (NY = outputs/)

NY가 PDF 작업(`outputs/`)을 끝냈을 때 표준 순서:

```bash
# 1) 수정 후 점검·리로드
bash scripts/dev/verify_and_reload.sh \
  outputs/architect/skeletons/report_skeleton.py \
  outputs/carriers/pdf_carrier.py

# 2) (선택) 실제 PDF 렌더로 최종 확인
docker exec -it ada-worker-output python -m outputs.dev_preview3 titanic
#   → C:\IT\workspace_python\ADA\outputs\report_preview3_titanic.pdf

# 3) 웹 대시보드 F5
```

> 주의(HANDOFF §9): 샌드박스 bash의 `py_compile`/`import` 결과는 stale 사본일 수 있다.
> **권위 있는 최종 확인은 항상 `docker exec` 실렌더**다. 본 스크립트의 SHA256(2번)이
> 호스트↔컨테이너 실동기화를 보장한다.

---

## 참고 사항 (문제 아님)

- **RestartCount**: 수동 `docker restart`는 이 카운터에 안 잡힌다. 실제 반영은 **StartedAt 갱신**으로 확인한다(5번이 그렇게 검증).
- **slim 이미지 `ps` 미설치**: 워커는 HTTP health가 없어 `State.Running=true / Restarting=false`로 대체 검증한다.
- **브라우저 캐시**: Streamlit은 모달 HTML을 매 실행마다 서버에서 새로 생성하므로 일반 F5로 충분(하드 리프레시 불필요).

---

작성: NY (HJ 지시) · `scripts/dev/verify_and_reload.sh` 동반 · 2026-06
