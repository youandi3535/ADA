# Day 15 — 산출물 패밀리 확장 (OUT-01 ~ OUT-04, OUT-07) + G5 게이트 완성
> 프로젝트: Adaptive AutoAI Pipeline Agent | 3주 스프린트 Day 15/21
> 본 문서는 v2 신규 작업이다. 마스터 설계서 §8 참조.
> **v2.1 스코프 축소 적용** — RENEWAL_SPEC.md §2 권위. 산출물 13종 → 5종.

---

## 📋 오늘의 목표

v1의 PPT·PDF·발표대본 3종을 넘어 **5종의 산출물 생성기** 를 완성한다. 사용자는 G5 게이트에서 5개 중 N개를 다중 선택할 수 있고, `ReportComposerAgent`가 이를 `output` Celery 큐에서 병렬 생성한다. 각 생성기는 독립 모듈이며, MinIO에 저장 후 `outputs` 테이블에 인벤토리 기록.

핵심 산출물 (5종):
- **OUT-01 PPT 발표자료** (.pptx, 기존, 그대로 활용)
- **OUT-02 상세 PDF 리포트** (.pdf, 기존)
- **OUT-03 발표 대본** (.txt, 기존)
- **OUT-04 정적 웹 대시보드** (.html 단일 파일) 🆕
- **OUT-07 인사이트 정리** (.md) 🆕

> v2.1 축소로 OUT-05/06/08/09/10/11/12/13 (영상 프롬프트, 외부 PPT 프롬프트, 학술 논문, 기획안, Executive Summary, 상세 비즈니스 리포트, 인포그래픽, 팟캐스트) 는 **모두 제거**.

---

## 👤 담당자

- **D** 주도 (산출물 패밀리 전체)
- 코드 리뷰: A (LLM 프롬프트)

---

## ✅ 작업 목록

### 1. OutputTypeSelectorAgent (G5 게이트)

- [ ] `agents/proposers/output_type_selector.py` — BaseGateAgent 상속, gate_code='G5'
- [ ] `state.user_intent_structured.deliverable_hint`, `state.user_intent_structured.audience`, `state.eval_result` 를 기반으로 추천 산출물 결정
- [ ] 추천 매핑 (`agents/proposers/recommend_outputs.py`) — RENEWAL_SPEC.md §12 권위:
  ```python
  RECOMMEND_BY_AUDIENCE = {
      "임원":      ["OUT-01", "OUT-03"],
      "분석가":    ["OUT-02", "OUT-07", "OUT-04"],
      "일반대중":  ["OUT-04"],
      "운영":      ["OUT-04", "OUT-02"],
  }
  RECOMMEND_BY_GOAL = {
      "예측":          ["OUT-01", "OUT-02"],
      "분류":          ["OUT-01", "OUT-02"],
      "군집화":        ["OUT-04", "OUT-07"],
      "이상탐지":      ["OUT-04", "OUT-07"],
      "예측+해석":     ["OUT-02", "OUT-07"],
      "의사결정지원":  ["OUT-01"],
  }
  ```
- [ ] 두 가중치를 합산하여 상위 3개에 ⭐ 추천 배지, 나머지는 일반 옵션으로 응답
- [ ] G5 응답 JSON 구조:
  ```json
  {
    "recommended": ["OUT-01","OUT-02","OUT-07"],
    "all_options": [
      {"code":"OUT-01","title":"PPT 발표자료","est_min":3,"recommended":true},
      {"code":"OUT-02","title":"상세 PDF 리포트","est_min":5,"recommended":true},
      {"code":"OUT-03","title":"발표 대본","est_min":2,"recommended":false},
      {"code":"OUT-04","title":"정적 웹 대시보드","est_min":4,"recommended":false},
      {"code":"OUT-07","title":"인사이트 정리(MD)","est_min":2,"recommended":true}
    ],
    "rationale": "임원 청중 + 예측+해석 의도에 맞춰..."
  }
  ```

### 2. ReportComposerAgent v2 — 병렬 fan-out

- [ ] state.user_choice_g5 (사용자가 선택한 산출물 코드 리스트) 만큼 ThreadPoolExecutor(max_workers=4)로 생성기 호출
- [ ] 각 생성기 결과를 `state.produced_outputs[code] = minio_path` 로 누적
- [ ] outputs 테이블 INSERT (job_id, output_code, minio_path, file_size_bytes, generation_ms)
- [ ] 일부 실패 시 부분 성공 허용 (실패 코드는 `state.output_warnings` 에 기록)

### 3. OUT-04 DashboardArtifactGenerator

- [ ] `reports/dashboard_artifact.py`
- [ ] Jinja2 단일 HTML 템플릿 (`templates/dashboard_artifact.html`):
  - Chart.js (CDN + 오프라인 폴백)
  - 인라인 base64 EDA 차트 5장
  - 인터랙티브 모델 비교 (사용자가 메트릭 토글)
  - 사용자 인사이트(Markdown→HTML)
  - 모델 다운로드 링크 (presigned URL)
- [ ] 모든 데이터를 `<script id="data" type="application/json">` 안에 임베드
- [ ] 출력 파일 크기 ≤ 5MB 권장

### 4. OUT-07 인사이트 정리 (Markdown)

- [ ] `reports/insight_md.py`
- [ ] InsightAgent 의 결과 + 추가 메타(SHAP top10, 차트 임베드, 한계점, 다음 단계)
- [ ] H1~H3 헤더 구조, 표·체크리스트 포함

### 5. 산출물 다운로드 API 통합

- [ ] `GET /outputs/{job_id}` — 산출물 목록 + presigned URL (15분 만료)
- [ ] `GET /outputs/{job_id}/{output_code}` — 개별 다운로드 (Streaming)

> v2.1 축소로 **삭제된 작업 항목** (참고):
> - ~~OUT-05 VideoPromptGenerator (5플랫폼)~~ — 제거됨 (v2.1 스코프 축소)
> - ~~OUT-06 PPTPromptGenerator (Gamma/Beautiful.ai)~~ — 제거됨
> - ~~OUT-08 PaperGenerator (LaTeX → PDF)~~ — 제거됨 (pandoc/texlive 의존성 함께 제거)
> - ~~OUT-09 PlanGenerator (기획안)~~ — 제거됨
> - ~~OUT-10 SummaryGenerator (1페이지 Executive Summary)~~ — 제거됨
> - ~~OUT-11 ReportGenerator (상세 비즈니스 리포트)~~ — 제거됨
> - ~~OUT-12 InfographicPromptGenerator~~ — 제거됨
> - ~~OUT-13 PodcastPromptGenerator~~ — 제거됨

---

## 🏗️ 구현 명세

### ReportComposerAgent v2 시그니처

```python
class ReportComposerAgent(BaseAgent):
    GENERATORS = {
        "OUT-01": PresentationGenerator,
        "OUT-02": PDFGenerator,
        "OUT-03": ScriptGenerator,
        "OUT-04": DashboardArtifactGenerator,
        "OUT-07": InsightMDGenerator,
    }

    def __call__(self, state: PipelineStateV2) -> PipelineStateV2:
        codes = [c["code"] for c in (state.user_choice_g5 or [])]
        if not codes:
            codes = ["OUT-01", "OUT-02"]  # 기본 폴백
        results = {}
        warnings = []
        with ThreadPoolExecutor(max_workers=4) as ex:
            futures = {ex.submit(self._run_generator, code, state): code for code in codes}
            for fut in as_completed(futures):
                code = futures[fut]
                try:
                    minio_path, gen_ms = fut.result(timeout=300)
                    results[code] = minio_path
                    self._record_output(state.job_id, code, minio_path, gen_ms)
                except Exception as e:
                    warnings.append({"code": code, "error": str(e)})
                    logger.exception("output_generation_failed", code=code)
        return state.model_copy(update={
            "produced_outputs": results,
            "output_warnings": warnings,
            "next_agent": "self_learning_dispatch",
        })

    def _run_generator(self, code, state):
        t0 = time.monotonic()
        gen = self.GENERATORS[code]()
        path = gen.generate(state)
        return path, int((time.monotonic() - t0) * 1000)
```

### OUT-04 dashboard_artifact.html 골자

```html
<!doctype html><html><head>
<meta charset="utf-8"><title>분석 대시보드 — {{ project }}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0"></script>
<style>body{font-family:system-ui;margin:0;padding:24px;background:#0b1220;color:#e5e7eb}
.card{background:#111827;border-radius:12px;padding:20px;margin-bottom:16px}</style>
</head><body>
<h1>{{ project }} — {{ category }}</h1>
<div class="card"><h2>핵심 메트릭</h2><div id="metrics"></div></div>
<div class="card"><h2>모델 비교</h2><canvas id="modelChart"></canvas></div>
<div class="card"><h2>EDA</h2>{% for img in eda_charts_b64 %}<img src="{{ img }}">{% endfor %}</div>
<div class="card"><h2>인사이트</h2>{{ insights_html|safe }}</div>
<script id="data" type="application/json">{{ data_json|safe }}</script>
<script>const data = JSON.parse(document.getElementById('data').textContent);
new Chart(document.getElementById('modelChart'), {type:'bar', data: data.modelChart});</script>
</body></html>
```

---

## 📁 생성/수정 파일 목록

| 경로 | 작업 |
|---|---|
| `agents/proposers/output_type_selector.py` | 신규 (G5) |
| `agents/report_composer.py` | 수정 (5종 fan-out) |
| `reports/dashboard_artifact.py` | 신규 |
| `reports/insight_md.py` | 신규 |
| `templates/dashboard_artifact.html` | 신규 |
| `api/routes/outputs.py` | 신규 |
| `agents/proposers/recommend_outputs.py` | 신규 |
| `tests/reports/test_*.py` (5종) | 신규 |

---

## 🔗 의존성 & 선행 조건

- Day12 산출물 v1 3종 + 산출물 신규 파이프라인 완성
- Day13 결과 엔드포인트 골격
- `kaleido` Plotly PNG (EDA 차트 임베드용)

> v2.1 축소로 제거된 의존성: ~~`pandoc`, `texlive` (논문/기획안용)~~, ~~`weasyprint` (Executive Summary용)~~

---

## ✔️ 완료 기준

- [ ] 5종 생성기 단위 테스트 모두 통과
- [ ] E2E: G5에서 3개 산출물 선택 → 3개 모두 outputs 테이블 + MinIO 저장
- [ ] OUT-04 HTML 단일 파일 ≤ 5MB
- [ ] OUT-07 Markdown 헤더 구조 검증 (H1 1회, H2 ≥ 3개)
- [ ] 추천 1순위 산출물에 ⭐ 배지 표시 UI 확인

---

## ⚠️ 주의사항

- OUT-04 HTML 산출물은 base64 인라인 이미지로 5MB 한도 주의
- LLM 호출 비용은 v2.1에서 크게 감소 (OUT-08/09/10/11 제거로 잡당 비용 ~80% 절감)
- 사용자 선택 산출물이 모두 5개 선택돼도 병렬 fan-out으로 ≤ 30초 목표

---

## 🆕 v2.2 보강 (감사 보고서 2026-05-19 반영)

> 출처: `ADA_v2_감사보고서.docx`. 본 섹션이 v2.1 본문과 충돌 시 **v2.2가 우선**한다.

### 1) 산출물 버전 관리
- `outputs.version` 컬럼 추가. 같은 잡 재실행 시 v2, v3 … 누적. 이전 버전 다운로드 가능.

### 2) 다운로드 감사 로그 (R-508 신설)
- /outputs/{id}/download 호출 시 audit_log INSERT (event_type='output_download', resource_id=output_id).
- presigned URL 만료 15분 후에도 마지막 다운로드자·시각 기록.

### 3) 부분 실패 재시도 큐
- ReportComposer 의 ThreadPoolExecutor 부분 실패(예: PDF 만 실패) 시 누락 산출물을 `output_retry` Redis 큐에 INSERT. 백그라운드 재시도.

### 4) OUT-04 단일 HTML 크기 한도
- 5MB 초과 시 이미지 외부 링크 모드로 자동 전환 + 경고.

### 5) 산출물 생성기 동적 등록
- `reports/registry.py` — GENERATORS 딕셔너리를 entry_points 기반 자동 등록 (Day04 플러그인 패턴과 동일).

### 완료 기준 추가
- [ ] outputs.version 누적 단위 테스트
- [ ] /download audit_log INSERT 검증
- [ ] 부분 실패 재시도 시나리오

---

## 🧰 v2.3 도구 보강 (도구 카탈로그 2026-05-19 반영)

> 출처: `TOOL_CATALOG_2026.md`. 본 섹션은 Day-D / Day-E / v3_backlog 의 도구를 본 Day 의 코드 위치에 매핑한다.

### 적용 도구
- **python-docx** (🔴 Day-D §4) — OUT-02-DRAFT 보조 산출. G5 옵션 체크박스.
- **Chart.js / Plotly** (🟡 Day-E §4) — OUT-04 단일 HTML 대시보드 엔진.

### 코드 위치
- `reports/word_generator.py` — Word 초안 생성기 (Day-D).
- `reports/dashboard/charts_chartjs.py` — Chart.js 기반 (가벼움).
- `reports/dashboard/charts_plotly.py` — Plotly 기반 (인터랙티브).
- DashboardArtifactGenerator 가 차트 종류·데이터 크기에 따라 자동 선택.

### G5 UI 변경
- OUT-02 추천 시 "PDF + Word 초안" 옵션 체크박스 추가 (Day-D §4.3).

---

# 📦 통합본 (v2.4) — 원래 Day-D §4: python-docx (Word 초안 산출)

> 통합일: 2026-05-19 (v2.4)
> 원래 `Day-D_도구즉시도입.md §4` 본문. v2.4 부터 본 Day15 산출물 패밀리 영역에서 단일 권위.

#### §4. python-docx — Word 초안 산출

#### 4.1 산출물
- `reports/word_generator.py` — `WordDraftGenerator` 클래스 (PPT 생성기와 동일 인터페이스)
- OUT-02 PDF 생성 직전에 Word 초안(.docx) 1개 생성 + MinIO 저장

#### 4.2 구현

```python
# reports/word_generator.py
from docx import Document
from docx.shared import Pt, RGBColor

class WordDraftGenerator:
    def __init__(self, palette):
        self.palette = palette  # 카테고리별 색상 (마스터 §8.4)

    def build(self, state) -> bytes:
        doc = Document()
        # 표지·요약·EDA·모델·평가·해석·결론·부록 8섹션
        doc.add_heading(state.title, level=0)
        doc.add_paragraph(state.subtitle)
        self._add_summary(doc, state)
        self._add_metrics_table(doc, state)
        self._add_shap_section(doc, state)
        self._add_insight_section(doc, state)
        # 한글 폰트 강제
        for p in doc.paragraphs:
            for run in p.runs:
                run.font.name = "맑은 고딕"
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()
```

#### 4.3 산출물 카테고리 변경
- v2.1 OUT 코드와 충돌 방지 위해 **OUT-02-DRAFT** 라는 보조 코드 부여. 사용자는 G5 에서 "PDF 보고서 + Word 초안" 옵션 체크박스로 선택.
- 기본은 PDF 만 제출. Word 초안은 옵션.

#### 4.4 룰 R-1004
OUT-02 PDF 생성 전 옵션이 활성화되면 Word 초안(.docx)을 동일 잡 ID 디렉토리에 보관. 다운로드 가능 + audit_log.

#### 4.5 테스트
- `tests/outputs/test_word_generator.py` — 표/이미지/한글 폰트/스타일 적용 통과.
- `tests/outputs/test_pdf_word_consistency.py` — Word ↔ PDF 콘텐츠 동일 (제목·메트릭·인사이트 동일).

---


---

## 📦 통합본 (v2.4) — Day-D 통합 테스트·완료 기준·주의사항

> Day-D 의 종합 테스트·완료·주의 섹션이 본 Day15 끝에 보관된다.

#### 🧪 통합 테스트 (Day-D 종합)

`tests/integration_v2.3/test_day_d_smoke.py`:
1. 분석 잡 1건 실행 — Langfuse 에 27 에이전트 trace 모두 기록
2. 인젝션 페이로드 입력 → LLM Guard 차단 + audit_log
3. anomaly_detection 카테고리 → PyOD Top-3 후보
4. G5 에서 Word 초안 옵션 선택 → .docx 생성 + MinIO 저장

---

#### ✅ 완료 기준

- [ ] Langfuse UI 접속 후 27 에이전트 trace 표시
- [ ] LLM Guard 100종 페이로드 모두 차단 + audit_log INSERT
- [ ] PyOD 카테고리별 Top-3 후보 학습 통과
- [ ] Word 초안 .docx 생성 + 한글 폰트 + 표·이미지 표시
- [ ] 4개 도구 통합 smoke 테스트 통과
- [ ] R-1001~R-1004 AGENTS.md 등록

---

#### ⚠️ 주의사항

- Langfuse 자체 DB 가 Postgres 일 경우 ada 메인 DB 와 분리 권고 — 컴플라이언스/리텐션 정책 다름.
- LLM Guard 의 PII 마스킹은 영문 중심 — 한글 PII 는 ADA Presidio 또는 KLUE NER 보강 필요.
- PyOD AutoEncoder/VAE/DeepSVDD 는 PyTorch 의존 — GPU 미가용 시 자동 폴백.
- python-docx 한글 폰트는 Dockerfile.worker 에 NanumGothic 또는 맑은고딕 사전 포함.
- 4개 도구 모두 R-709(pybreaker)·R-505(decay)·R-902(SHA256) 영향 없음 — 독립 모듈.

---

# 📦 통합본 (v2.4) — 원래 Day-E §4: Chart.js / Plotly (OUT-04 시각화 엔진)

> 통합일: 2026-05-19 (v2.4)
> 원래 `Day-E_도구단기도입.md §4` 본문. v2.4 부터 본 Day15 의 OUT-04 영역에서 단일 권위.

#### §4. Chart.js / Plotly — OUT-04 시각화 엔진

#### 4.1 산출물
- `reports/dashboard/charts_chartjs.py` — Chart.js 기반 (가벼움, 정적)
- `reports/dashboard/charts_plotly.py` — Plotly 기반 (인터랙티브)
- DashboardArtifactGenerator 갱신 — 차트 종류·데이터 크기에 따라 자동 선택

#### 4.2 선택 규칙

| 차트 유형 | 데이터 크기 | 인터랙션 필요 | 라이브러리 |
|---|---|---|---|
| Bar/Line/Pie | < 10k 포인트 | 아니오 | Chart.js |
| 3D scatter, surface | 임의 | 예 | Plotly |
| Heatmap, Sunburst | > 1k 포인트 | 예 | Plotly |
| Sparkline 인덱스 | 매우 작음 | 아니오 | Chart.js |
| SHAP force plot | 임의 | 예 | Plotly (또는 shap.js) |

#### 4.3 단일 HTML 5MB 한도
- Chart.js CDN 사용 시 인라인 데이터만 추가 → 보통 1~2MB.
- Plotly 인라인 + plotly.min.js CDN → 2~4MB. 5MB 초과 시 이미지 외부 링크 모드 폴백 (Day15 §4 와 연계).

#### 4.4 룰 R-1008
OUT-04 단일 HTML 은 Chart.js 우선, 인터랙티브 필요 또는 Chart.js 미지원 차트 시 Plotly 폴백.

#### 4.5 ExplainabilityAgent 시각화
- SHAP summary plot → Plotly (인터랙티브 호버).
- 시계열 분해 (trend/seasonal/residual) → Chart.js (가벼움).
- TabTransformer attention map → Plotly heatmap.

#### 4.6 테스트
- `tests/outputs/test_chartjs_render.py` — 5종 차트 렌더 + 파일 크기 < 5MB.
- `tests/outputs/test_plotly_interactivity.py` — Plotly figure JSON 유효성 + 호버 데이터 포함.

---


---

## 📦 통합본 (v2.4) — Day-E 통합 테스트·완료 기준·주의사항

> Day-E 의 종합 테스트·완료·주의 섹션이 본 Day15 끝에 보관된다.

#### 🧪 통합 테스트 (Day-E 종합)

`tests/integration_v2.3/test_day_e_smoke.py`:
1. tabular_ml 잡 — Guardrails 가 G1~G5 모두 schema 검증 통과
2. KB 비어있는 신규 데이터셋 — FLAML 폴백 → Optuna enqueue 확인
3. timeseries 잡 — Top-3 에 StatsForecast 베이스라인 포함
4. OUT-04 생성 — Chart.js + Plotly 혼합 렌더 + 5MB 이내

---

#### ✅ 완료 기준

- [ ] 11개 LLM 사용 에이전트 모두 Pydantic schema 정의 + Guardrails 통과
- [ ] FLAML 폴백 단위 테스트 통과 + Optuna enqueue 검증
- [ ] StatsForecast Top-3 포함 통합 테스트 통과
- [ ] OUT-04 5종 차트 + 5MB 이내 단위 테스트 통과
- [ ] R-1005~R-1008 AGENTS.md 등록

---

#### ⚠️ 주의사항

- Guardrails AI 의 자동 재시도는 비용 증가 원인 — `max_retries=2` 고정 + Langfuse 로 재시도 모니터링.
- FLAML 과 Optuna 가 같은 estimator 를 중복 탐색 — FLAML 결과를 Optuna 초기값으로만 사용해 중복 최소화.
- StatsForecast 의 frequency inference 가 실패하면 사용자에게 명시적 freq 입력 요청.
- Plotly 인라인 JS 는 ~4MB → CDN 사용이 기본. 오프라인 환경은 별도 정책.
- 4개 도구 모두 Day-D 의 Langfuse trace 데코레이터 자동 적용 (이중 추적 방지: 동일 trace tree).
