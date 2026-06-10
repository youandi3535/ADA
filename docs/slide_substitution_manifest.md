# 산출 PPT — 카테고리별 슬라이드 대체 매니페스트

> 20슬라이드 골격 고정. 카테고리에서 의미 없는 슬라이드는 *비슷한 다른 걸로 대체* (skip 안 함).
> 본 표는 4 카테고리 × 20 슬라이드 의 매핑 기준.

## 구조 그룹 분류

| 그룹 | 슬라이드 | 변형 정도 |
|---|---|---|
| **A. 골격 (변형 거의 없음)** | S1 Cover, S3 Agenda, S20 Closing | ctx.meta 만 다름 |
| **B. ctx 만 다름** | S2 Exec Summary, S4 Hypothesis, S5 Data, S7 Method, S18 SWOT, S19 Roadmap | 카테고리 어휘는 동일, 수치만 변경 |
| **C. 카테고리별 대체 핵심** | S6 Tech Stack, S8~11 EDA, S12~17 모델·해석 | 본 매니페스트의 주된 대상 |

---

## C-1. Tech Stack (S6)

| 카테고리 | Tech Stack |
|---|---|
| tabular_ml | scikit-learn · CatBoost / LightGBM · SHAP · MLflow |
| tabular_dl | PyTorch · TabNet / FT-Transformer · Integrated Gradients · W&B |
| timeseries | statsmodels · Prophet / N-BEATS · Lag/Calendar features · MLflow |
| anomaly | scikit-learn · IsolationForest / LOF / AutoEncoder · ThresholdTuner · MLflow |

## C-2. EDA 슬라이드 (S8 ~ S11)

| 슬라이드 | tabular_ml | tabular_dl | timeseries | anomaly |
|---|---|---|---|---|
| **S8 EDA-1** | 주요 변수 1 (예: Sex) | 주요 변수 1 (또는 embedding 시각화) | 시간축 + 트렌드 | 정상 vs 이상 분포 비교 |
| **S9 EDA-2** | 주요 변수 2 (예: Pclass) | 주요 변수 2 | 계절 분해 (trend / seasonal / residual) | 변수 간 상관 패턴 차이 |
| **S10 EDA-3** | 주요 변수 3 (예: Age) | 주요 변수 3 | ACF / PACF | 시간·위치 차원 이상 분포 |
| **S11 EDA-Extra** | 변수 간 상관 / 데이터 품질 | 동일 또는 latent space cluster | 결측·이상치 구간 패턴 | feature 별 이상 기여도 |

## C-3. Modeling · 해석 · 평가 (S12 ~ S17)

| 슬라이드 | tabular_ml | tabular_dl | timeseries | anomaly |
|---|---|---|---|---|
| **S12 Model Perf** | Accuracy / F1 / AUC / Recall 4-metric | 동일 (또는 회귀 시 MAE/R²) | MAE / MAPE / RMSE + 예측 구간 | precision@k / recall@k / PR-AUC (라벨 있을 때) / 도메인 검증 (없을 때) |
| **S13 SHAP global** | SHAP Top 5 | Integrated Gradients Top 5 | 시점별 영향도 (lag importance / 외생변수 기여) | reason code 상위 5 (feature contribution) |
| **S14 SHAP cases** | 개별 예측 사례 3건 | attention map / per-sample IG | 계절 분해 효과 + 잔차 패턴 | 이상 사례 3건 + 각 이유 |
| **S15 Error CM** | Confusion Matrix + 오류 분석 | 동일 | 잔차 진단 (ACF residual / Q-Q plot) | precision@k 곡선 + 알람 budget 곡선 |
| **S16 Segment** | 세그먼트별 성능 (예: 성별·계층) | 동일 | 계절·시간대·요일별 성능 차이 | 정상 / 이상 클러스터 비교 |
| **S17 Policy Insight** | 도입 정책 + 운영 룰 | 동일 | 예측 구간 기반 안전재고·임계 설정 | 임계값·알람 budget·운영 시나리오 |

---

## verdict 분기 — adopt / iterate / reject

S2 (Exec Summary), S17 (Policy Insight), S19 (Roadmap) 는 ctx.verdict 에 따라 어조 변형:

| verdict | S2 어조 | S17 어조 | S19 어조 |
|---|---|---|---|
| **adopt** | "도입 권장 — N개월 내" | 운영 룰 + 모니터링 정책 | Phase 1 파일럿 → Phase 2 확장 |
| **iterate** | "재학습 권장 — 부족 영역 식별" | 보강 우선순위 + 재시도 조건 | 데이터 보강 → 재학습 → 재평가 |
| **reject** | "현 모델 도입 불가 — 사유" | 폐기 사유 + 대안 권고 | 재정의 → 대안 모델 탐색 → 검증 |

---

## 자동 추론 라벨

도메인 해석을 자동 채울 때 ( ctx.domain_source == "auto" ) 텍스트 끝에 `[auto-inferred]` 마커 부착 + 인용 면제. 예:

> "Master 호칭은 어린 소년을 의미 — Age 결측 보강 시 호칭별 평균이 단순 median 보다 정확 `[auto-inferred]`"

---

## 동적 채움 안전망

| 안전망 | 동작 |
|---|---|
| **필수 필드 매니페스트** | 슬라이드별 ctx 필수 필드 정의. 미충족 시 placeholder 대신 *대체 변형* 슬라이드로 스왑 |
| **글자 예산** | 박스 기하 → 글자 수 환산. 초과 시 *문장 경계* 에서 축약. mid-word truncation 금지 |
| **typed schema assert** | 렌더 직전 metric type assert (classification / regression / forecast / detection). 불일치 시 fallback 변형 슬라이드 |
| **단위 포매터 단일화** | 0.693 / 69% / +36% / 18.5%p 혼용 방지 — 슬라이드 단위로 표기 룰 고정 |
