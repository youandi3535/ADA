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
