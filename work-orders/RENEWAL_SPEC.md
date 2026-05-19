# ADA v2.1 리뉴얼 스펙 (스코프 축소)

> **결정일**: 2026-05-18
> **권위**: 본 문서가 모든 작업지시서·README의 단일 권위 (Day00 마스터설계서보다 우선)
> 모든 daily/*.md 파일은 이 스펙에 일치하도록 갱신되어야 한다.

---

## 1. 분석 카테고리 (6종 → 4종)

### 유지 (4종)
- `tabular_ml` — 정형 ML
- `tabular_dl` — 정형 DL
- `timeseries` — 시계열
- `anomaly_detection` — 이상탐지

### 제거 (2종)
- ❌ `image` — 이미지
- ❌ `nlp` — 자연어

---

## 2. 산출물 (13종 → 5종)

### 유지 (5종)
- OUT-01 PPT 발표자료 (.pptx)
- OUT-02 상세 PDF 리포트 (.pdf)
- OUT-03 발표 대본 (.txt)
- OUT-04 정적 웹 대시보드 (.html 단일)
- OUT-07 인사이트 정리 (.md)

### 제거 (8종)
- ❌ OUT-05 영상 제작 프롬프트
- ❌ OUT-06 외부 PPT 생성기 프롬프트
- ❌ OUT-08 학술 논문 초안
- ❌ OUT-09 기획안
- ❌ OUT-10 Executive Summary
- ❌ OUT-11 상세 비즈니스 리포트
- ❌ OUT-12 인포그래픽 프롬프트
- ❌ OUT-13 팟캐스트 프롬프트

---

## 3. 모델 카탈로그

### 유지 모델 (19종)

**정형 ML (4)**: RandomForest, XGBoost, LightGBM, CatBoost
**정형 DL (3)**: TabTransformer, FTTransformer, TabPFN
**시계열 (6)**: ARIMA, SARIMA, Prophet, Informer, TFT, PatchTST
**이상탐지 (6)**: IsolationForest, LOF, OneClassSVM, AutoEncoder, TranAD, AnomalyTransformer

### 제거 모델 (이름 언급도 제거)
- ResNet, ResNet50
- EfficientNet, EfficientNet-B0, EfficientNetB0
- ViT, ViT-B/16, ViT-Tiny, ViT-B
- Swin-T, SwinT
- DeiT-S, DeiTS, DeiT
- klue/bert-base, KLUE_BERT, klue-bert, BERT
- XLM-RoBERTa, XLMRoBERTa
- DeBERTa, DeBERTa-v3, DeBERTaV3

### TRANSFORMER_REGISTRY (14종 → 8종)
- TabTransformer, FTTransformer, TabPFN
- Informer, TFT, PatchTST
- TranAD, AnomalyTransformer

---

## 4. 데이터 입력 형식 (10종 → 8종)

### 유지
csv, xlsx, parquet, json, zip, pdf, txt, html

### 제거
- ❌ jpg, png, jpeg (이미지)
- ❌ wav, mp3 (오디오)

---

## 5. Python 버전

**3.10 사용 (3.11 표기 모두 변경)**

- `python:3.11-slim` → `python:3.10-slim`
- `Python 3.11` → `Python 3.10`
- `python-version: 3.11` → `python-version: 3.10`
- `python-version: "3.11"` → `python-version: "3.10"`

---

## 6. MLflow 실험 (6종 → 4종)

### 유지
- ada-tabular-ml
- ada-tabular-dl
- ada-timeseries
- ada-anomaly

### 제거
- ❌ ada-image
- ❌ ada-nlp

---

## 7. 카테고리별 색상 테마 (6색 → 4색)

### 유지
- tabular_ml: 파랑 `#2563eb` / `RGBColor(37, 99, 235)`
- tabular_dl: 청록 `#0891b2` / `RGBColor(8, 145, 178)`
- timeseries: 초록 `#16a34a` / `RGBColor(22, 163, 74)`
- anomaly_detection: 빨강 `#dc2626` / `RGBColor(220, 38, 38)`

### 제거
- ❌ image: 보라 `#7c3aed` / `RGBColor(124, 58, 237)`
- ❌ nlp: 주황 `#ea580c` / `RGBColor(234, 88, 12)`

---

## 8. 변경되는 수치/카운트

| 표현 | 이전 | 신규 |
|---|---|---|
| 산출물 종류 | 13종 | **5종** |
| 생성기 유틸리티 | 13종 | **5종** |
| 분석 카테고리 | 6종 (6/6) | **4종 (4/4)** |
| 트랜스포머 레지스트리 | 14종 (또는 9종) | **8종** |
| MLflow 실험 | 6종 | **4종** |
| API 엔드포인트 | ~30 | **~25** |
| 데모 매트릭스 | 5×5 | **4×5** (4 카테고리 × 5 산출물) |
| 통합 테스트 IT | IT-1~IT-5 | **IT-1~IT-4** |
| 인수 테스트 AT | AT-1~AT-5 | **AT-1~AT-4** |

---

## 9. 변경되지 않는 것 (그대로 유지)

- **27 에이전트** (카운트, 시드 27행 모두 유지)
- **5 HITL 게이트** (G0~G5)
- **G0_PII 미니게이트**
- **3-Stack 자체학습** (PostgreSQL + MinIO + pgvector)
- **25 노드 LangGraph 그래프**
- **agent_registry seed 27행** (모든 에이전트 등록)
- **보안 풀스택** (JWT, RBAC, RLS, PII, Vault)
- **AutoErrorHandler + Claude CLI 사이드카**
- **11개 KPI** (단 KP4는 "4/4", KP9는 "≥25%"로 조정)

---

## 10. 에이전트 동작 변경 (이름은 유지, 내부 로직 축소)

- **DataProfilerAgent**: 이미지/오디오 핸들러 제거
- **PreprocessingStrategistAgent**: 이미지/NLP 전처리 분기 제거
- **EDAAgent**: 워드클라우드/이미지 그리드 차트 제거
- **ExplainabilityAgent**: GradCAM / Attention map 제거. **SHAP만 사용**
- **ModelSelectionAgent**: 후보 모델 풀에서 image/NLP 모델 제거
- **ReportComposerAgent**: GENERATORS 딕셔너리 13개 → 5개
- **OutputTypeSelectorAgent**: G5 추천 매핑 5종 한정

---

## 11. 코드 자체가 작성되지 않는 항목

- `pipelines/image/` 디렉토리 및 `ImagePipeline` 클래스
- `pipelines/nlp/` 디렉토리 및 `NLPPipeline` 클래스
- `reports/video_prompt.py` (OUT-05)
- `reports/ppt_prompt.py` (OUT-06)
- `reports/paper_generator.py` (OUT-08)
- `reports/plan_generator.py` (OUT-09)
- `reports/summary_generator.py` (OUT-10)
- `reports/report_generator.py` (OUT-11)
- `reports/infographic_prompt.py` (OUT-12)
- `reports/podcast_prompt.py` (OUT-13)
- LaTeX 템플릿 (paper용)
- 이미지 transform / NLP 토크나이저 모듈
- GradCAM / Attention 시각화 모듈

---

## 12. G5 추천 매핑 단순화

```python
# 청중별
RECOMMEND_BY_AUDIENCE = {
    "임원":      ["OUT-01", "OUT-03"],
    "분석가":    ["OUT-02", "OUT-07", "OUT-04"],
    "일반대중":  ["OUT-04"],
    "운영":      ["OUT-04", "OUT-02"],
}

# 목표별
RECOMMEND_BY_GOAL = {
    "예측":          ["OUT-01", "OUT-02"],
    "분류":          ["OUT-01", "OUT-02"],
    "군집화":        ["OUT-04", "OUT-07"],
    "이상탐지":      ["OUT-04", "OUT-07"],
    "예측+해석":     ["OUT-02", "OUT-07"],
    "의사결정지원":  ["OUT-01"],
}
```

기존 매핑에서 OUT-05/06/08~13 참조는 모두 제거. 청중 카테고리 "학술", "마케팅"은 사용하지 않거나 위 5종으로 매핑.

---

## 13. 검수 체크리스트 (모든 파일 수정 후)

- [ ] grep `image` (소문자) 결과에 분석 카테고리 의미의 매치 없음 (PIL 같은 라이브러리 언급은 OK)
- [ ] grep `nlp` 결과에 분석 카테고리 의미의 매치 없음
- [ ] grep `OUT-05|OUT-06|OUT-08|OUT-09|OUT-10|OUT-11|OUT-12|OUT-13` 매치 0
- [ ] grep `ResNet|EfficientNet|ViT|SwinT|DeiT|BERT|RoBERTa|DeBERTa|klue` 매치 0
- [ ] grep `python:3.11|Python 3.11|python-version: 3.11` 매치 0
- [ ] grep `ada-image|ada-nlp` 매치 0
- [ ] grep `워드클라우드|wordcloud|GradCAM|Attention map` 매치 0
- [ ] grep `13종 산출물|6 카테고리|6/6` 매치 0 또는 적절한 컨텍스트
- [ ] agent_registry 27행 유지 확인
- [ ] 5 HITL 게이트 / 3-Stack / 25 노드 LangGraph 언급 유지 확인
