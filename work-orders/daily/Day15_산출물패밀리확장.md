# Day 15 — 산출물 패밀리 확장 (OUT-01 ~ OUT-13) + G5 게이트 완성
> 프로젝트: Adaptive AutoAI Pipeline Agent | 3주 스프린트 Day 15/21
> 본 문서는 v2 신규 작업이다. 마스터 설계서 §8 참조.

---

## 📋 오늘의 목표

v1의 PPT·PDF·발표대본 3종을 넘어 **13종의 산출물 생성기** 를 완성한다. 사용자는 G5 게이트에서 13개 중 N개를 다중 선택할 수 있고, `ReportComposerAgent`가 이를 `output` Celery 큐에서 병렬 생성한다. 각 생성기는 독립 모듈이며, MinIO에 저장 후 `outputs` 테이블에 인벤토리 기록.

핵심 산출물:
- **OUT-01 PPT** (기존, 그대로 활용)
- **OUT-02 PDF** (기존)
- **OUT-03 발표 대본** (기존)
- **OUT-04 정적 웹 대시보드 (HTML 단일 파일)** 🆕
- **OUT-05 영상 제작 프롬프트** (5플랫폼) 🆕
- **OUT-06 외부 PPT 생성기 프롬프트** (Gamma/Beautiful.ai) 🆕
- **OUT-07 인사이트 정리** (Markdown) 🆕
- **OUT-08 학술 논문 초안 (IEEE/ACM LaTeX)** 🆕
- **OUT-09 기획안** (Word/Markdown) 🆕
- **OUT-10 1페이지 Executive Summary** 🆕
- **OUT-11 상세 비즈니스 리포트** 🆕
- **OUT-12 인포그래픽 디자인 프롬프트** 🆕
- **OUT-13 팟캐스트 대본 + 음성 합성 프롬프트** 🆕

---

## 👤 담당자

- **D** 주도 (산출물 패밀리 전체)
- 코드 리뷰: A (LLM 프롬프트), B (LaTeX 빌드)

---

## ✅ 작업 목록

### 1. OutputTypeSelectorAgent (G5 게이트)

- [ ] `agents/proposers/output_type_selector.py` — BaseGateAgent 상속, gate_code='G5'
- [ ] `state.user_intent_structured.deliverable_hint`, `state.user_intent_structured.audience`, `state.eval_result` 를 기반으로 추천 산출물 결정
- [ ] 추천 매핑 (`agents/proposers/recommend_outputs.py`):
  ```python
  RECOMMEND_BY_AUDIENCE = {
      "임원":      ["OUT-10","OUT-11","OUT-01","OUT-03"],
      "분석가":    ["OUT-02","OUT-07","OUT-11","OUT-04"],
      "일반대중":  ["OUT-05","OUT-12","OUT-04"],
      "학술":      ["OUT-08","OUT-01","OUT-03"],
      "마케팅":    ["OUT-05","OUT-12","OUT-13","OUT-04"],
      "운영":      ["OUT-11","OUT-04","OUT-02"],
  }
  RECOMMEND_BY_GOAL = {
      "예측":          ["OUT-01","OUT-02","OUT-11"],
      "분류":          ["OUT-01","OUT-02","OUT-11"],
      "군집화":        ["OUT-04","OUT-07","OUT-11"],
      "이상탐지":      ["OUT-11","OUT-04","OUT-07"],
      "예측+해석":     ["OUT-02","OUT-08","OUT-07"],
      "의사결정지원":  ["OUT-10","OUT-11","OUT-01"],
      "생성":          ["OUT-07","OUT-05"],
  }
  ```
- [ ] 두 가중치를 합산하여 상위 6개에 ⭐ 추천 배지, 나머지는 일반 옵션으로 응답
- [ ] G5 응답 JSON 구조:
  ```json
  {
    "recommended": ["OUT-10","OUT-11","OUT-01"],
    "all_options": [
      {"code":"OUT-01","title":"PPT 발표자료","est_min":3,"recommended":true},
      ...13개...
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

### 4. OUT-05 VideoPromptGenerator

- [ ] `reports/video_prompt.py`
- [ ] LLM (Sonnet 4.6)로 6씬 시나리오 생성:
  ```
  Scene 1 (인트로): 데이터 소개. 카메라: 와이드 → 클로즈업. BGM: 잔잔한 신스
  Scene 2 (문제정의): ...
  Scene 3 (분석 과정): ...
  Scene 4 (핵심 발견): 임팩트 있는 그래픽 줌인
  Scene 5 (비즈니스 임팩트): ...
  Scene 6 (결론): CTA 자막
  ```
- [ ] 동일 시나리오를 5개 플랫폼 포맷으로 변환:
  - `runway_gen3_alpha.txt`
  - `sora.txt`
  - `veo.txt`
  - `kling.txt`
  - `pika.txt`
- [ ] 각 파일은 플랫폼별 권장 길이/스타일 차이 반영 (Runway는 6초/씬, Sora는 12초/씬 등)

### 5. OUT-06 PPTPromptGenerator (Gamma/Beautiful.ai 외부 입력용)

- [ ] `reports/ppt_prompt.py`
- [ ] LLM으로 슬라이드 10장 분량 마크다운 outline 생성 + Gamma 페이스트 가능 형식
- [ ] 출력: `gamma_input.md`, `beautiful_ai_input.txt`

### 6. OUT-07 인사이트 정리 (Markdown)

- [ ] `reports/insight_md.py`
- [ ] InsightAgent 의 결과 + 추가 메타(SHAP top10, 차트 임베드, 한계점, 다음 단계)
- [ ] H1~H3 헤더 구조, 표·체크리스트 포함

### 7. OUT-08 PaperGenerator (LaTeX → PDF)

- [ ] `reports/paper_generator.py`
- [ ] LaTeX 템플릿 2종: `templates/paper_ieee.tex`, `templates/paper_acm.tex`
- [ ] LLM (Opus 4.7)으로 각 섹션 생성:
  - Abstract (250 단어)
  - Introduction (3 단락)
  - Related Work — pgvector 유사 사례에서 자동 추천 참고문헌 5건
  - Methodology — 사용된 파이프라인 상세
  - Experiments — 데이터셋, 베이스라인, 메트릭 표
  - Results — 비교표 + 통계 유의성
  - Discussion, Conclusion, References
- [ ] `tex2pdf` 마이크로서비스 (Day1 컨테이너 옵션 추가) 또는 `latexmk` 호출하여 PDF 컴파일
- [ ] 영문/한국어 선택 옵션 (`state.user_intent_structured.language`)

### 8. OUT-09 PlanGenerator (기획안)

- [ ] `reports/plan_generator.py`
- [ ] 8 페이지 기획안 구조 (Markdown → docx, pandoc 변환):
  1. 제목
  2. 요약 (Executive Summary)
  3. 배경 (분석 동기)
  4. 목표 (정량/정성)
  5. 분석 근거 (데이터, 메트릭)
  6. 솔루션 (추천 액션)
  7. 일정 (간트 차트 — Mermaid)
  8. 예산 (테이블)
- [ ] LLM Sonnet 4.6 사용, temperature=0.4

### 9. OUT-10 SummaryGenerator (1페이지 Executive Summary)

- [ ] `reports/summary_generator.py`
- [ ] 단일 PDF, A4 1페이지, 4개 박스 (문제, 핵심 발견, 비즈니스 임팩트, 다음 단계)
- [ ] WeasyPrint 또는 ReportLab

### 10. OUT-11 ReportGenerator (상세 비즈니스 리포트)

- [ ] `reports/report_generator.py`
- [ ] 20~30 페이지 PDF, OUT-02보다 비즈니스 관점 더 강함
- [ ] 섹션: 비즈니스 컨텍스트, 분석 방법론, 핵심 발견 5건, 데이터 기반 권고 3건, 부록(상세 메트릭)

### 11. OUT-12 InfographicPromptGenerator

- [ ] `reports/infographic_prompt.py`
- [ ] LLM이 인포그래픽 디자인 설명 텍스트 생성:
  - 컬러 팔레트 (HEX 5색)
  - 레이아웃 (Z-패턴 / F-패턴)
  - 핵심 통계 3~5개
  - 아이콘 추천 (FontAwesome 명칭)
- [ ] Canva/Adobe Express 입력용 포맷 + Midjourney `--ar 2:3 --style raw` 프롬프트 동시 출력

### 12. OUT-13 PodcastPromptGenerator

- [ ] `reports/podcast_prompt.py`
- [ ] 10~15분 분량 대화형 팟캐스트 대본 (호스트 + 게스트 분석가 역할극)
- [ ] ElevenLabs / OpenAI TTS 입력용 SSML 태그 포함 옵션

### 13. 산출물 다운로드 API 통합

- [ ] `GET /outputs/{job_id}` — 산출물 목록 + presigned URL (15분 만료)
- [ ] `GET /outputs/{job_id}/{output_code}` — 개별 다운로드 (Streaming)

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
        "OUT-05": VideoPromptGenerator,
        "OUT-06": PPTPromptGenerator,
        "OUT-07": InsightMDGenerator,
        "OUT-08": PaperGenerator,
        "OUT-09": PlanGenerator,
        "OUT-10": SummaryGenerator,
        "OUT-11": ReportGenerator,
        "OUT-12": InfographicPromptGenerator,
        "OUT-13": PodcastPromptGenerator,
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
| `agents/report_composer.py` | 수정 (13종 fan-out) |
| `reports/dashboard_artifact.py` | 신규 |
| `reports/video_prompt.py` | 신규 |
| `reports/ppt_prompt.py` | 신규 |
| `reports/insight_md.py` | 신규 |
| `reports/paper_generator.py` | 신규 |
| `reports/plan_generator.py` | 신규 |
| `reports/summary_generator.py` | 신규 |
| `reports/report_generator.py` | 신규 |
| `reports/infographic_prompt.py` | 신규 |
| `reports/podcast_prompt.py` | 신규 |
| `templates/dashboard_artifact.html` | 신규 |
| `templates/paper_ieee.tex`, `templates/paper_acm.tex` | 신규 |
| `templates/plan_template.md` | 신규 |
| `templates/summary_a4.html` | 신규 |
| `templates/report_long.html` | 신규 |
| `api/routes/outputs.py` | 신규 |
| `agents/proposers/recommend_outputs.py` | 신규 |
| `tests/reports/test_*.py` (13종) | 신규 |

---

## 🔗 의존성 & 선행 조건

- Day12 산출물 v1 3종 + 산출물 신규 파이프라인 완성
- Day13 결과 엔드포인트 골격
- `pandoc`, `texlive` (paper용) Docker 이미지에 설치
- `kaleido` Plotly PNG, `weasyprint` 한국어 폰트

---

## ✔️ 완료 기준

- [ ] 13종 생성기 단위 테스트 모두 통과
- [ ] E2E: G5에서 3개 산출물 선택 → 3개 모두 outputs 테이블 + MinIO 저장
- [ ] OUT-04 HTML 단일 파일 ≤ 5MB
- [ ] OUT-08 LaTeX 컴파일 → PDF 성공
- [ ] OUT-09 docx 변환 (pandoc) 성공
- [ ] 추천 1순위 산출물에 ⭐ 배지 표시 UI 확인

---

## ⚠️ 주의사항

- LaTeX 빌드는 시간 소요(10~30초). 영구화 위해 `texlive-full` 설치 필요 — Docker 이미지 크기 주의
- 외부 영상 플랫폼 프롬프트는 사용자가 별도 서비스에 입력해야 동작 (우리 시스템은 텍스트만 제공)
- LLM 호출 비용: OUT-08(논문) 이 가장 비쌈 (Opus 4.7 × 8 섹션) — 1잡당 ~$1.5 예상
- 사용자 선택 산출물이 12개 이상이면 경고 (시간/비용 폭주)
