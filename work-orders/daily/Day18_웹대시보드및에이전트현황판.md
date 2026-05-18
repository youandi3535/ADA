# Day 18 — 웹 대시보드 + 에이전트 현황판 + HITL UI + 산출물 다운로드
> 프로젝트: Adaptive AutoAI Pipeline Agent | 3주 스프린트 Day 18/21
> 본 문서는 v2 신규 작업이다. 마스터 설계서 §9 참조.

---

## 📋 오늘의 목표

> **"한 페이지에서 시스템 전체가 무엇을 하고 있는지 보이고, 또 다른 페이지에서 사용자가 5번 가벼운 선택을 한다."**

웹 프론트엔드를 v1의 진행률 바에서 **3페이지 대시보드 + 인터랙티브 분석 워크플로우** 로 재설계한다.

페이지 구성:
- **P1 시스템 현황판** (대시보드 메인) — 에이전트 매트릭스, 자체학습 누적, 실행 중 잡, 보안 알람
- **P2 분석 시작 (인터랙티브)** — 업로드 → G0~G5 게이트 카드 UI → 산출물 다운로드
- **P3 잡 히스토리** — 내 분석 이력, 산출물 다시 받기, 재실행

---

## 👤 담당자

- **A** 주도 (대시보드 + 게이트 UI)
- **C** 협업 (백엔드 API 데이터 셰이프)

---

## ✅ 작업 목록

### 1. 페이지 구조 (`frontend/`)

```
frontend/
├── app.py                          # 진입점 (Streamlit multipage)
├── pages/
│   ├── 01_시스템현황판.py
│   ├── 02_분석시작.py
│   └── 03_잡히스토리.py
├── components/
│   ├── agent_matrix.py             # 27 에이전트 매트릭스 위젯
│   ├── gate_card.py                # G1~G5 공용 카드
│   ├── gate_g1_3options.py         # G1 전용 3안 카드
│   ├── gate_g2_methodology.py      # G2 표 형식
│   ├── gate_g3_strategy.py         # G3 매트릭스
│   ├── gate_g4_compare.py          # G4 비교 차트
│   ├── gate_g5_outputs.py          # G5 체크박스 + ⭐ 추천
│   ├── learning_stats.py           # 자체학습 누적 효과
│   ├── alarm_panel.py              # 보안 알람
│   ├── progress_stream.py          # WebSocket 진행률 스트림
│   └── output_card.py              # 산출물 다운로드 카드
└── utils/
    ├── api_client.py               # FastAPI 호출 + JWT 자동 첨부
    └── auth.py                     # 로그인/로그아웃/토큰 관리
```

### 2. P1 시스템 현황판

#### 2.1 헤더 — 헬스 게이지

- [ ] `GET /health` 호출 → 4개 서비스 상태 색상 배지 (postgres/redis/minio/llm)
- [ ] `st.metric` 4개 (응답 시간, 큐 깊이, 활성 잡, 24h 처리량)

#### 2.2 에이전트 매트릭스 (27개)

- [ ] `GET /dashboard/agents` 응답:
  ```json
  {
    "categories": {
      "입력·검증": [
        {"name":"SupervisorAgent","status":"idle","success_rate":0.98,"avg_ms":1200},
        {"name":"IntentElicitorAgent","status":"running","current_job":"7a1b...","success_rate":0.95},
        ...
      ],
      "의사결정 제안": [...],
      ...
    }
  }
  ```
- [ ] 컴포넌트 `agent_matrix.py`:
  - 카테고리별 가로 grid
  - 에이전트마다 ● (초록=idle, 노랑=running, 빨강=fail) + 이름 + tooltip(성공률/평균 ms)
  - 클릭 시 우측 사이드바에 상세 패널 (역할 설명, capabilities, 최근 24h 로그, 사용 LLM)

#### 2.3 실행 중인 잡 테이블

- [ ] `GET /dashboard/jobs?status=active`
- [ ] 컬럼: job_id (짧게), 카테고리, 현재 게이트, 진행률 막대, 사용자(마스킹), 시작 시각, [→ 잡 상세]

#### 2.4 자체학습 누적 효과

- [ ] `GET /dashboard/learning` 응답:
  ```json
  {
    "success_patterns": {"total":137,"delta_7d":24},
    "model_recipes":     {"total":42,"delta_7d":8},
    "error_kb_auto_solve_rate": 0.64,
    "claude_cli_calls_7d": [12, 9, 7, 8, 5, 4, 3]
  }
  ```
- [ ] 시각화:
  - 빅 넘버 + 7일 델타 (`st.metric`)
  - Claude CLI 호출 추이 라인차트 (감소 추세 강조)
  - 카테고리별 success_patterns 분포 막대

#### 2.5 보안 알람 패널

- [ ] `GET /dashboard/alarms?hours=24`
- [ ] 심각도 색상: info=회색, warn=노랑, error=주황, critical=빨강
- [ ] 항목별 [세부 보기] 버튼 → `security_audit_log` 풀 컨텍스트

### 3. P2 분석 시작 (인터랙티브 워크플로우)

이 페이지가 핵심 사용자 여정 (마스터 §1.1) 의 구현체.

#### 3.1 단계 1 — 파일 업로드

- [ ] `st.file_uploader(type=['csv','xlsx','parquet','json','zip','pdf','txt','html','jpg','png','wav'], accept_multiple_files=False)`
- [ ] 업로드 후 미리보기 (`st.dataframe` 또는 이미지 썸네일)
- [ ] PII 미니 게이트 발동 시: 컬럼별 라디오 (마스킹/제외/유지) UI

#### 3.2 단계 2 — 의도 입력 (G0)

- [ ] `st.text_area("어떤 분석/결과물이 필요하신가요?", placeholder="예: 다음 분기 매출을 예측해서 임원 보고용 PPT 만들어줘", max_chars=2000)`
- [ ] [예시 의도 보기] 토글 — 5가지 예시 (마케팅, 운영, 학술, 임원, 일반)
- [ ] [시작] 클릭 → POST /pipeline/start → job_id 획득 → session_state['job_id'] 저장

#### 3.3 단계 3 — 진행률 + 게이트 인터럽트 수신

- [ ] WebSocket `ws://api/pipeline/ws/{job_id}` 연결
- [ ] 메시지 종류:
  - `progress` → progress_stream 업데이트
  - `interrupt` → 해당 게이트 카드를 펼침
  - `completed` → 산출물 카드 표시
  - `error` → 에러 배너 + 재시도 버튼

#### 3.4 단계 4 — 게이트 카드 (G1~G5)

##### G1 — 분석 방향 3안

- [ ] 카드 3장 (`gate_g1_3options.py`):
  - 카드 헤더: 제목 + ⭐ 추천 배지 (rank=1)
  - 본문: why (왜 이 방향) + plan_outline 체크리스트
  - 메타: 예상 메트릭, 예상 시간, 트랜스포머 사용 여부 ⚡ 아이콘
  - 푸터: [이 방향 선택] 버튼
- [ ] 클릭 → POST /pipeline/{job_id}/decision (gate=G1, choice={index, ...})

##### G2 — 방법론 비교 표

- [ ] DataFrame 형식 표:
  - 방법론 | 적합도 | 이유 | 트랜스포머 가능 | 예상 메트릭 | 해석가능성 | 비용
- [ ] 각 행 마지막에 [선택] 버튼

##### G3 — 모델 전략 매트릭스

- [ ] 카드 3장 + 펼침 패널 (architecture_sketch, fallback)
- [ ] 학습 시간/메트릭 예상값 막대 비교

##### G4 — 모델 비교 (학습 후)

- [ ] 좌측: 막대 차트 (val_metric × 3 모델)
- [ ] 우측: 학습 곡선 + SHAP top5 미니 차트
- [ ] 하단: 모델별 [선택] 버튼

##### G5 — 산출물 다중 선택

- [ ] 체크박스 그리드 (13종):
  ```
  [✓] ⭐ OUT-01 PPT 발표자료     [ ]    OUT-04 정적 웹 대시보드
  [✓] ⭐ OUT-02 PDF 리포트       [✓]    OUT-05 영상 프롬프트
  [ ]    OUT-03 발표 대본         [ ]    OUT-06 외부 PPT 프롬프트
  ... (13개 전부)
  ```
- [ ] ⭐ 가 시스템 추천. 기본 체크된 상태
- [ ] [생성 시작] 버튼 → POST /pipeline/{job_id}/decision (gate=G5, choice=[...codes])

#### 3.5 단계 5 — 산출물 다운로드 카드

- [ ] 완료 시 `GET /outputs/{job_id}` 호출
- [ ] 각 산출물별 카드:
  - 아이콘 + 코드 + 제목 + 파일 크기 + 생성 시간
  - [📥 다운로드] (presigned URL)
  - [👁️ 미리보기] (가능한 경우 — HTML 대시보드, Markdown 인사이트는 인라인 렌더)
- [ ] [모두 ZIP 다운로드] 버튼

### 4. P3 잡 히스토리

- [ ] `GET /jobs?user=me&limit=50&offset=0`
- [ ] 테이블: job_id, 카테고리, 상태, 생성 시각, 산출물 수, [→ 결과 보기], [♻️ 재실행]
- [ ] 필터: 카테고리, 상태, 기간

### 5. 백엔드 데이터 API (Day19 사전 부분)

- [ ] `GET /dashboard/agents` — agent_registry + 최근 agent_runs 집계
- [ ] `GET /dashboard/jobs` — jobs 테이블 status 필터
- [ ] `GET /dashboard/learning` — self_learning_kb, error_kb 집계
- [ ] `GET /dashboard/alarms` — security_audit_log 최근

### 6. WebSocket 메시지 라우팅 강화

- [ ] `api/routes/websocket.py` 의 메시지 type 확장:
  ```json
  {"type":"progress","agent":"...","pct":...}
  {"type":"interrupt","gate":"G1","proposals":[...]}
  {"type":"agent_status","agent":"...","status":"running|idle|fail"}
  {"type":"completed","outputs":{...}}
  {"type":"warning","message":"...","severity":"low|medium|high"}
  {"type":"error","message":"...","recoverable":bool}
  ```

### 7. 다크/라이트 테마

- [ ] `.streamlit/config.toml`:
  ```toml
  [theme]
  primaryColor = "#3b82f6"
  backgroundColor = "#0b1220"
  secondaryBackgroundColor = "#111827"
  textColor = "#e5e7eb"
  font = "sans serif"
  ```
- [ ] 사용자 토글 (`st.sidebar.toggle("라이트 모드")`)

### 8. 접근성 + 모바일 대응

- [ ] 색상 명도 대비 WCAG AA (4.5:1) 확인
- [ ] 키보드 탐색 (Tab/Enter) — Streamlit 기본 지원
- [ ] 모바일 뷰포트에서 카드 grid → 단일 컬럼 자동 폴드

---

## 🏗️ 구현 명세

### `components/gate_card.py` 인터페이스

```python
import streamlit as st

def render_gate_card(card: dict, on_select: Callable[[dict], None], recommended: bool=False):
    """공용 게이트 카드 컴포넌트."""
    with st.container(border=True):
        col1, col2 = st.columns([4, 1])
        with col1:
            badge = "⭐ 추천" if recommended else ""
            st.markdown(f"### {card['title']} {badge}")
            st.write(card["why"])
        with col2:
            if card.get("transformer_used"):
                st.caption("⚡ Transformer")
            st.caption(f"≈ {card.get('est_duration_min','?')}분")
            st.caption(f"메트릭: {card.get('est_metrics', {}).get('primary','?')}")
        if "plan_outline" in card:
            with st.expander("실행 계획"):
                for s in card["plan_outline"]:
                    st.markdown(f"- {s}")
        if st.button(f"이 방안 선택", key=f"select_{card.get('rank','x')}", type="primary"):
            on_select(card)
```

### `components/progress_stream.py` (WebSocket 폴 폴백)

```python
import asyncio, json, websockets

async def stream_progress(job_id, jwt_token, on_message):
    uri = f"ws://api:8000/pipeline/ws/{job_id}"
    headers = [("Authorization", f"Bearer {jwt_token}")]
    async with websockets.connect(uri, extra_headers=headers) as ws:
        async for raw in ws:
            on_message(json.loads(raw))
            if json.loads(raw).get("type") in ("completed","error"):
                break
```

Streamlit 안에서:

```python
import threading
def run_async(coro):
    loop = asyncio.new_event_loop()
    threading.Thread(target=lambda: loop.run_until_complete(coro), daemon=True).start()
```

---

## 📁 생성/수정 파일 목록

| 경로 | 작업 |
|---|---|
| `frontend/app.py` | 신규 (multipage 진입점) |
| `frontend/pages/01_시스템현황판.py` | 신규 |
| `frontend/pages/02_분석시작.py` | 신규 |
| `frontend/pages/03_잡히스토리.py` | 신규 |
| `frontend/components/*.py` (12 파일) | 신규 |
| `frontend/utils/api_client.py` | 신규 |
| `frontend/utils/auth.py` | 신규 |
| `api/routes/dashboard.py` | 신규 |
| `api/routes/websocket.py` | 메시지 type 확장 |
| `.streamlit/config.toml` | 테마 갱신 |
| `tests/frontend/test_pages_smoke.py` | 신규 (Selenium/Playwright) |

---

## 🔗 의존성 & 선행 조건

- Day13/17 인증 미들웨어 완료
- Day15 OUT-04 dashboard_artifact 가 별도 정적 산출물이라는 점에 유의 (시스템 현황판과 다름)
- Day4 LangGraph v2 가 게이트 메시지 발행
- 패키지: `streamlit>=1.35`, `websockets`, `httpx`, `plotly`

---

## ✔️ 완료 기준

- [ ] P1 진입 시 27 에이전트 매트릭스 표시 + 색상 상태 정상 갱신 (5초 폴링)
- [ ] P2 업로드 → G0~G5 모든 게이트 인터랙션 E2E 통과 (mock 또는 실제)
- [ ] G5 선택 후 산출물 생성 → 다운로드 카드 표시
- [ ] WebSocket 메시지 6종 type 모두 정상 라우팅
- [ ] 다크 모드/라이트 모드 토글 정상 동작
- [ ] WCAG AA 명도 대비 통과 (Lighthouse 측정)

---

## ⚠️ 주의사항

- Streamlit `st.fragment(run_every=5)` 는 1.35+ 기능. 미만이면 `st_autorefresh` 컴포넌트
- WebSocket 인증: JWT 를 첫 메시지에 포함시키는 방식 (브라우저 WebSocket은 헤더 직접 못 보냄)
- 게이트 응답 전송 후 동일 게이트 카드는 비활성화 (중복 클릭 방지)
- 모바일에서 13개 산출물 그리드는 2열 → 1열로 reflow
- 대시보드가 무거우면 캐시 적극 활용: `@st.cache_data(ttl=5)`
