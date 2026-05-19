# Day 12 — 산출물 생성 + 확장 파이프라인
> 프로젝트: Adaptive AutoAI Pipeline Agent | 2주 스프린트 Day 12/14

---

## 📋 오늘의 목표

분석 완료 후 사용자에게 전달할 **PPT / PDF / 발표 대본** 3종 산출물 생성 에이전트를 완성하고,
**이상탐지(Anomaly)** 파이프라인을 신규 구현하여 플랫폼이 지원하는 4개 카테고리 파이프라인(tabular_ml, tabular_dl, timeseries, anomaly_detection)을 모두 완성한다.

- ReportComposerAgent: PPT/PDF/Script 병렬 생성 조율
- PresentationGenerator: python-pptx 기반 7~10 슬라이드 PPT
- PDFGenerator: WeasyPrint + Jinja2 기반 PDF
- ScriptGenerator: Claude Sonnet 4.6 기반 발표 대본
- AnomalyPipeline: IsolationForest/LOF/OneClassSVM/AutoEncoder 파이프라인

> 본 스코프 제외: 이미지(Image) 파이프라인 및 NLP 파이프라인은 v2.1 리뉴얼에서 제외되었다. 관련 코드(`pipelines/image/`, `pipelines/nlp/`)는 작성하지 않는다.

---

## 👤 담당자

- **D**: ReportComposerAgent, PresentationGenerator, PDFGenerator, ScriptGenerator
- **B**: AnomalyPipeline

---

## ✅ 작업 목록

### 1. ReportComposerAgent 구현 (D)

- [ ] `agents/report_composer.py` 파일 생성
  - `ReportComposerAgent(BaseAgent)` 클래스 정의
  - LLM 미사용 (ScriptGenerator 내부에서 사용)
  - **병렬 생성 전략:**
    - `concurrent.futures.ThreadPoolExecutor(max_workers=3)` 활용
    - 세 작업 동시 제출: `executor.submit(generate_ppt)`, `executor.submit(generate_pdf)`, `executor.submit(generate_script)`
    - `futures.as_completed()` 로 결과 수집
  - 생성 완료 후:
    - `state.ppt_path` = MinIO PPT 경로
    - `state.pdf_path` = MinIO PDF 경로
    - `state.script_path` = MinIO 대본 경로
  - 3개 중 1개 실패 시 부분 성공 허용 (나머지 2개 반환)
  - 실패 항목은 `state.report_warnings` 리스트에 추가

### 2. PresentationGenerator 구현 (D)

- [ ] `reports/ppt_generator.py` 파일 생성
  - `PresentationGenerator` 클래스 (python-pptx 기반)
  - **슬라이드 구성 (7~10개):**
    1. **표지 슬라이드**: 프로젝트명 "Adaptive AutoAI Pipeline", 분석 날짜, 카테고리, 데이터셋 이름
    2. **데이터 개요**: 행 수/열 수/결측값 비율/주요 통계 표 (pptx `Table` 객체)
    3. **EDA 차트 1**: 분포 히스토그램 이미지 삽입 (`add_picture`)
    4. **EDA 차트 2**: 상관관계 히트맵 또는 시계열 라인 차트
    5. **EDA 차트 3**: 카테고리별 추가 차트 (이상치/단어빈도/클래스분포 등)
    6. **모델 비교표**: 후보 3개 모델 메트릭 비교 표 (4열 × N행)
    7. **최종 결과**: best model 이름, primary metric 값, 배지 스타일 강조
    8. **해석 이미지**: SHAP beeswarm 삽입 (SHAP 단일 방식, GradCAM/Attention map 미사용)
    9. **비즈니스 인사이트**: `state.insights` 단락 별 bullet points (최대 6개)
    10. **향후 제안 & 한계점**: 추가 분석 제안, 모델 한계, 데이터 수집 권고

  - **카테고리별 색상 테마 (4종):**
    ```python
    THEME_COLORS = {
        'tabular_ml':        RGBColor(37, 99, 235),    # 파랑 (#2563eb)
        'tabular_dl':        RGBColor(8, 145, 178),    # 청록 (#0891b2)
        'timeseries':        RGBColor(22, 163, 74),    # 초록 (#16a34a)
        'anomaly_detection': RGBColor(220, 38, 38),    # 빨강 (#dc2626)
    }
    ```
  - **레이아웃 설정:** `prs.slide_width = Inches(13.33)`, `prs.slide_height = Inches(7.5)` (와이드)
  - MinIO 저장 후 경로 반환: `minio_tool.save_bytes(ppt_bytes, f"reports/{job_id}/report.pptx")`

  - **구현 상세:**
    - `_add_title_slide(prs, state)`: 배경색 카테고리 색상, 흰색 텍스트
    - `_add_data_overview_slide(prs, state)`: 5열 통계 테이블
    - `_add_eda_slide(prs, state, chart_idx)`: MinIO에서 PNG 로드 후 삽입
    - `_add_model_comparison_slide(prs, state)`: 모델별 메트릭 비교 테이블
    - `_add_best_model_slide(prs, state)`: 대형 텍스트 + 메트릭 강조
    - `_add_explanation_slide(prs, state)`: 해석 이미지 + 설명 텍스트
    - `_add_insight_slide(prs, state)`: Markdown → 불릿 변환
    - `_add_recommendation_slide(prs, state)`: 제안사항 목록

### 3. PDFGenerator 구현 (D)

- [ ] `reports/pdf_generator.py` 파일 생성
  - `PDFGenerator` 클래스 (WeasyPrint + Jinja2 기반)
  - **Jinja2 HTML 템플릿 사용:**
    - `templates/pdf_report.html`: 메인 레이아웃
    - `templates/pdf_style.css`: 인쇄용 CSS (`@media print`, `@page` 설정)
  - **EDA 차트 삽입:**
    - MinIO에서 PNG 바이트 로드
    - `base64.b64encode(png_bytes).decode()` → HTML `<img src="data:image/png;base64,...">` 삽입
  - **PDF 구조:**
    - 표지 (A4 전체)
    - 목차 (자동 생성)
    - 데이터 개요 섹션
    - EDA 차트 섹션 (2열 격자)
    - 모델 비교 테이블
    - 인사이트 섹션
    - 참고사항 & 한계점
  - **페이지 설정:** A4, 상하좌우 여백 15mm
  - `weasyprint.HTML(string=html_content).write_pdf()` 로 PDF 바이트 생성
  - MinIO 저장: `minio_tool.save_bytes(pdf_bytes, f"reports/{job_id}/report.pdf")`

- [ ] `templates/pdf_report.html` 파일 생성
  - Jinja2 템플릿 변수: `{{ project_name }}`, `{{ analysis_date }}`, `{{ category }}`, `{{ insights }}`, `{{ eda_charts }}`, `{{ model_comparison }}`

- [ ] `templates/pdf_style.css` 파일 생성
  - `@page { size: A4; margin: 15mm; }`
  - 카테고리별 색상 변수: `var(--theme-color)`
  - 차트 이미지: `max-width: 100%; page-break-inside: avoid;`
  - 헤더/푸터: 페이지 번호 자동 삽입 (`content: counter(page)`)

### 4. ScriptGenerator 구현 (D)

- [ ] `reports/script_generator.py` 파일 생성
  - `ScriptGenerator` 클래스, Claude Sonnet 4.6 사용
  - **SCRIPT_PROMPT 정의:**
    ```
    당신은 데이터 분석 발표 대본 작성 전문가입니다.
    아래 슬라이드 내용을 바탕으로 각 슬라이드별 발표 대본을 작성하세요.

    규칙:
    1. 각 슬라이드 대본은 [Slide N] 형식으로 시작
    2. 각 슬라이드 발표 시간: 30~60초 (약 100~200자)
    3. 비즈니스 발표 톤, 존댓말 사용
    4. 청중: 데이터 분석 비전문가 (경영진 대상)
    5. 마지막 슬라이드 결론에 즉시 실행 가능한 액션 아이템 2~3개 포함
    6. 한국어로 작성

    슬라이드 내용:
    {slide_content}
    ```
  - `temperature=0.3` (일관성 있는 톤 유지)
  - 슬라이드별 내용 요약 → LLM 호출 → 대본 텍스트 반환
  - MinIO 저장: `minio_tool.save_text(script_text, f"reports/{job_id}/script.txt")`

### 5. AnomalyPipeline 구현 (B)

- [ ] `pipelines/anomaly/pipeline.py` 파일 생성
  - `AnomalyPipeline(BasePipeline)` 클래스 정의
  - 지원 알고리즘: `isolation_forest`, `lof`, `one_class_svm`, `autoencoder`
  - **IsolationForest:**
    - `sklearn.ensemble.IsolationForest(contamination=0.05, random_state=42)`
    - `predict()` → `-1` (이상) / `1` (정상)
  - **LOF (LocalOutlierFactor):**
    - `sklearn.neighbors.LocalOutlierFactor(n_neighbors=20, contamination=0.05)`
  - **OneClassSVM:**
    - `sklearn.svm.OneClassSVM(kernel='rbf', nu=0.05)`
  - **AutoEncoder (PyTorch MLP):**
    ```python
    class AnomalyAutoEncoder(nn.Module):
        def __init__(self, input_dim, encoding_dim=32):
            super().__init__()
            self.encoder = nn.Sequential(
                nn.Linear(input_dim, 64), nn.ReLU(),
                nn.Linear(64, encoding_dim), nn.ReLU()
            )
            self.decoder = nn.Sequential(
                nn.Linear(encoding_dim, 64), nn.ReLU(),
                nn.Linear(64, input_dim)
            )
        def forward(self, x):
            return self.decoder(self.encoder(x))
    ```
    - 재구성 오차 (`MSELoss`) 기반 이상 점수
    - threshold = `mean(reconstruction_error) + 3 * std(reconstruction_error)`
  - **메트릭:** `val_auc` (AUROC), `val_precision_at_k` (상위 k% 이상치 정밀도)
  - **평가:** 검증셋에 레이블이 있는 경우 AUROC, 없는 경우 실루엣 점수

---

## 🏗️ 구현 명세

### PresentationGenerator 핵심 구조

```python
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
import io

class PresentationGenerator:
    THEME_COLORS = {
        'tabular_ml':        RGBColor(37, 99, 235),
        'tabular_dl':        RGBColor(8, 145, 178),
        'timeseries':        RGBColor(22, 163, 74),
        'anomaly_detection': RGBColor(220, 38, 38),
    }

    def generate(self, state: PipelineState) -> str:
        prs = Presentation()
        prs.slide_width  = Inches(13.33)
        prs.slide_height = Inches(7.5)
        theme_color = self.THEME_COLORS.get(state.category, RGBColor(37, 99, 235))

        self._add_title_slide(prs, state, theme_color)
        self._add_data_overview_slide(prs, state)
        for i, chart_path in enumerate(state.eda_charts[:3]):
            self._add_eda_slide(prs, state, chart_path, i + 1)
        self._add_model_comparison_slide(prs, state)
        self._add_best_model_slide(prs, state, theme_color)
        self._add_explanation_slide(prs, state)
        self._add_insight_slide(prs, state)
        self._add_recommendation_slide(prs, state)

        buf = io.BytesIO()
        prs.save(buf)
        buf.seek(0)
        path = minio_tool.save_bytes(buf.read(), f"reports/{state.job_id}/report.pptx")
        return path
```

### PDFGenerator 핵심 구조

```python
from jinja2 import Environment, FileSystemLoader
import weasyprint
import base64

class PDFGenerator:
    def generate(self, state: PipelineState) -> str:
        env = Environment(loader=FileSystemLoader('templates'))
        template = env.get_template('pdf_report.html')

        # EDA 차트 base64 인코딩
        eda_charts_b64 = []
        for chart_path in state.eda_charts:
            png_bytes = minio_tool.load_bytes(chart_path)
            b64 = base64.b64encode(png_bytes).decode()
            eda_charts_b64.append(f"data:image/png;base64,{b64}")

        html_content = template.render(
            project_name="Adaptive AutoAI Pipeline",
            analysis_date=datetime.now().strftime('%Y-%m-%d'),
            category=state.category,
            data_profile=state.data_profile,
            model_comparison=state.model_comparison_table,
            best_model=state.best_model,
            insights=state.insights,
            eda_charts=eda_charts_b64,
            top_features=state.explanations.get('top_features', []),
        )
        pdf_bytes = weasyprint.HTML(string=html_content).write_pdf()
        path = minio_tool.save_bytes(pdf_bytes, f"reports/{state.job_id}/report.pdf")
        return path
```

### AnomalyPipeline AutoEncoder 학습 구조

```python
def _train_autoencoder(self, X_train, X_val, params):
    input_dim = X_train.shape[1]
    model = AnomalyAutoEncoder(input_dim, encoding_dim=params.get('encoding_dim', 32))
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    criterion = nn.MSELoss()
    for epoch in range(params.get('epochs', 50)):
        model.train()
        for batch in DataLoader(TensorDataset(torch.FloatTensor(X_train.values)), batch_size=256):
            x = batch[0]
            loss = criterion(model(x), x)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
    # threshold 설정
    model.eval()
    with torch.no_grad():
        X_val_t = torch.FloatTensor(X_val.values)
        recon = model(X_val_t)
        errors = ((X_val_t - recon) ** 2).mean(dim=1).numpy()
    threshold = errors.mean() + 3 * errors.std()
    return model, threshold, errors
```

---

## 📁 생성/수정 파일 목록

| 경로 | 작업 | 설명 |
|------|------|------|
| `agents/report_composer.py` | 신규 생성 | PPT/PDF/Script 병렬 생성 조율 |
| `reports/ppt_generator.py` | 신규 생성 | python-pptx 기반 PPT 생성 |
| `reports/pdf_generator.py` | 신규 생성 | WeasyPrint 기반 PDF 생성 |
| `reports/script_generator.py` | 신규 생성 | Claude Sonnet 4.6 발표 대본 생성 |
| `templates/pdf_report.html` | 신규 생성 | PDF Jinja2 템플릿 |
| `templates/pdf_style.css` | 신규 생성 | PDF 인쇄용 CSS |
| `pipelines/anomaly/pipeline.py` | 신규 생성 | 이상탐지 파이프라인 4종 |
| `pipelines/anomaly/__init__.py` | 신규 생성 | 패키지 초기화 |
| `reports/__init__.py` | 신규 생성 | 패키지 초기화 |
| `shared/pipeline_factory.py` | 수정 | anomaly 파이프라인 등록 |
| `core/state.py` | 수정 | ppt_path, pdf_path, script_path 필드 추가 |

---

## 🔗 의존성 & 선행 조건

### Day 11까지 완료되어야 하는 항목

- `state.eda_charts` 리스트 설정 완료 (EDAAgent)
- `state.insights` Markdown 텍스트 설정 완료 (InsightAgent)
- `state.explanations` dict 설정 완료 (ExplainabilityAgent)
- `state.model_comparison_table` 설정 완료 (MetricsAggregator)
- MinIO 연결 및 `load_bytes`, `save_bytes` 메서드 구현 완료

### Python 패키지 의존성

```
python-pptx>=0.6.23
weasyprint>=61.0
jinja2>=3.1.4
scikit-learn>=1.4.0
torch>=2.2.0
```

### 외부 의존성

- `kaleido`: Plotly 이미지 내보내기
- `Cairo` 라이브러리: WeasyPrint 렌더링 (Docker 이미지에 `apt install -y libcairo2`)

---

## ✔️ 완료 기준 (Done Criteria)

- [ ] `PresentationGenerator`: 7~10 슬라이드 PPT 파일 생성, MinIO 저장 확인
- [ ] `PresentationGenerator`: 카테고리별 색상 테마 적용 확인 (표지 배경색, 4종 카테고리)
- [ ] `PDFGenerator`: A4 PDF MinIO 저장, EDA 차트 2개 이상 포함 확인
- [ ] `ScriptGenerator`: `[Slide 1]` ~ `[Slide N]` 형식 대본 생성 확인
- [ ] `ScriptGenerator`: 마지막 슬라이드 액션 아이템 포함 확인
- [ ] `AnomalyPipeline`: IsolationForest, AutoEncoder 2종 학습 후 `val_auc` 반환 확인
- [ ] `pipeline_factory.get('anomaly_detection')` 정상 반환 확인
- [ ] `ReportComposerAgent`: 3종 병렬 생성 완료 후 `state.ppt_path`, `state.pdf_path`, `state.script_path` 모두 설정 확인

---

## ⚠️ 주의사항 & 제약

1. **WeasyPrint Cairo 의존성**: Docker 이미지에 `libcairo2-dev`, `libpango1.0-dev`, `libgdk-pixbuf2.0-dev` 설치 필수.
2. **PPT 슬라이드 이미지 크기**: `add_picture()`시 너비/높이 명시 필수. 미명시 시 원본 크기로 슬라이드 초과 가능.
3. **병렬 생성 스레드 안전성**: `PresentationGenerator`와 `PDFGenerator`가 같은 MinIO 경로에 동시 쓰기 방지 (경로에 타입명 포함).
4. **Script 대본 언어**: SCRIPT_PROMPT에 "한국어 작성" 명시. LLM이 영어로 응답할 경우 재호출 로직 필요.
5. **AnomalyPipeline 레이블 없는 경우**: 순수 비지도 학습 시 `val_auc` 계산 불가. 합성 레이블(isolation forest 예측값) 기반 AUROC 계산으로 대체.
6. **PDF 한국어 폰트**: WeasyPrint 한국어 렌더링을 위해 `NanumGothic` 또는 `Noto Sans KR` 폰트 Docker 이미지에 포함 필요.

---

## 🆕 v2 확장 작업 (마스터 설계서 §7 · §4-D)

> Day12 의 v2 핵심: **정형 트랜스포머 파이프라인 정식 도입** (8종: TabTransformer, FTTransformer, TabPFN, Informer, TFT, PatchTST, TranAD, AnomalyTransformer). 이 날 산출물은 PPT/PDF/대본 3종은 그대로 두고, 산출물 패밀리 확장(5종)은 Day15에서 본격화.

### 1. `pipelines/transformer/` 패키지 신설

- [ ] `pipelines/transformer/__init__.py`
- [ ] `pipelines/transformer/tabular.py` — TabTransformer, FTTransformer, TabPFN 통합 인터페이스
  - 라이브러리: `tab-transformer-pytorch`, `pytorch-tabnet`, `tabpfn`
  - 공통 인터페이스: `train(X, y, params) → model`, `evaluate(model, Xv, yv, task) → metrics`
- [ ] `pipelines/transformer/timeseries.py` — Informer, TFT, PatchTST
  - 라이브러리: `pytorch-forecasting`, `neuralforecast`, `gluonts`
- [ ] `pipelines/transformer/anomaly.py` — TranAD, AnomalyTransformer

### 2. LoRA 어댑터 학습기 (`pipelines/transformer/lora.py`)

- [ ] `peft.LoraConfig(r=8, lora_alpha=16, target_modules=...)` 기반
- [ ] 데이터 < 1000행 → 어댑터만 학습, ≥ 1000 → 전체 미세조정
- [ ] BaseTransformer 클래스에 `freeze_backbone(self, enable=True)`, `enable_lora(self, config)` 메서드 추가

### 3. PipelineFactory v2 등록

```python
PIPELINE_REGISTRY_V2 = {
    ...v1...
    "transformer_tabular":    TabularTransformerPipeline,
    "transformer_timeseries": TSTransformerPipeline,
    "transformer_anomaly":    AnomalyTransformerPipeline,
}
```

### 4. 모델 캐시 볼륨

- [ ] `docker-compose.yml` 의 worker-training 에 `./models_cache:/root/.cache` 볼륨 마운트
- [ ] 첫 실행 시 다운로드/포팅, 이후 캐시 사용

### 5. 완료 기준 (v2 추가)

- [ ] TabularTransformerPipeline (TabTransformer) Titanic E2E `val_f1 ≥ 0.78`
- [ ] Informer Pipeline AirPassengers `val_mape ≤ 0.20`
- [ ] LoRA 어댑터 학습으로 트랜스포머 미세조정 시 학습 시간 ≥ 40% 단축 확인
- [ ] PipelineFactory.create("transformer_tabular") 정상 인스턴스화

### 6. 주의사항 (v2)

- TabPFN은 GPU 권장, CPU에서도 동작하나 매우 느림 (1만행 한계)
- TranAD 의 공식 구현은 없음 — 내부 포팅 (`tranad/model.py`) 필요
