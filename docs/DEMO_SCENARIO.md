# 데모 시나리오 (Day21)

## 시나리오 A — Titanic 정형 ML
1. `/upload` 로 titanic.csv 업로드
2. `/pipeline/start` (category=tabular_ml, target=Survived, intent="고객 생존 예측")
3. G1 ~ G5 게이트 5회 응답 (UI 또는 API)
4. 산출물 OUT-01 / OUT-04 / OUT-07 다운로드
5. KP1 (E2E ≥ 85%), KP2 (90s/180s), KP6 (룰 ≥ 15) 확인

## 시나리오 B — 시계열 매출 예측
1. monthly_sales.csv 업로드 (category=timeseries, target=sales)
2. G2 에서 Prophet/SARIMA/TFT 중 SARIMA 선택
3. OUT-02 PDF + OUT-04 HTML 대시보드 확인

## 시나리오 C — 이상탐지
1. 신용카드 거래 csv (category=anomaly_detection, target=is_fraud)
2. IsolationForest / LOF / AutoEncoder 비교
3. OUT-04 대시보드 + 이상치 분포

## 시나리오 D — 자체학습 (3-Stack)
- 같은 카테고리 3회 실행 → recipe KB 증류
- 4번째 실행에서 ModelSelectionAgent 가 KB 인용 (R-501)
