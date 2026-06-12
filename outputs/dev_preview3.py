"""outputs.dev_preview3 — 파이프라인 1~5단계 없이 보고서 PDF 만 즉시 렌더하는 개발용 하네스.

출력 파일명: report_preview3_{주제}.pdf  (주제 = 넣는 데이터에 따라 자동: titanic / telco / 덤프의 데이터셋명)

사용법 (ADA 루트, 워커와 같은 venv). 도커에서는 `docker exec -it ada-worker-output` 를 앞에 붙임:
    python -m outputs.dev_preview3                       # 내장 샘플 ctx 로 렌더 (Telco) → outputs/report_preview3_telco.pdf
    python -m outputs.dev_preview3 titanic                # 내장 타이타닉 ctx 로 렌더 → outputs/report_preview3_titanic.pdf
    python -m outputs.dev_preview3 report_context_dump.json   # 실제 덤프 ctx 로 렌더 → outputs/report_preview3_{데이터셋명}.pdf
    python -m outputs.dev_preview3 dump.json out.pdf     # 출력 경로 직접 지정

목적
    carrier/skeleton 의 레이아웃·폰트·색·목차 수정을 **초 단위**로 확인.
    MinIO/Redis/Celery/게이트(1~5단계) 전부 불필요 — ctx 만 있으면 보고서가 나온다.

주의
    - 매 실행이 새 프로세스라 .pyc 캐시 영향 없음 (서비스 재시작 불필요).
    - reportlab/matplotlib/koreanize-matplotlib/Pillow 설치된 환경에서 실행.
    - image_embed(EDA 실 PNG) 는 로컬에 파일이 없으면 자동 스킵되므로, 샘플은
      numbers 기반 막대 차트로 EDA 를 채워 미리보기가 비지 않게 했다.

내장 샘플 = Telco Customer Churn (통신 고객 이탈) — 불균형·범주형 동인·세그먼트·이탈 임팩트로
비즈니스 의사결정형 보고서를 끝까지 자극한다.

NY (HJ 위임) 2026-06 — OUT-02 보고서 프리뷰 전용. 프로덕션 경로(pdf.py)와 무관.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _sample_ctx():
    """Telco Customer Churn 유사 샘플 ReportContext — 이탈 예측(불균형 분류) 비즈니스 케이스."""
    from outputs.context.schema import (
        BaselineSet,
        BusinessKPI,
        DatasetProfile,
        DomainContext,
        EDAChart,
        EDAFindings,
        Evaluation,
        FeatureEngineering,
        FeatureSpec,
        GlobalImportance,
        Interpretation,
        LimitationItem,
        Limitations,
        Meta,
        ModelCandidate,
        ModelSelection,
        PreprocessingStep,
        PreprocessingTrace,
        ReportContext,
    )

    dtypes = {
        "customerID": "object",
        "gender": "object",
        "SeniorCitizen": "int64",
        "Partner": "object",
        "Dependents": "object",
        "tenure": "int64",
        "InternetService": "object",
        "OnlineSecurity": "object",
        "TechSupport": "object",
        "Contract": "object",
        "PaperlessBilling": "object",
        "PaymentMethod": "object",
        "MonthlyCharges": "float64",
        "TotalCharges": "float64",
        "Churn": "object",
    }
    glossary = {
        "customerID": "고객 ID",
        "gender": "성별",
        "SeniorCitizen": "고령 고객 여부",
        "Partner": "배우자 유무",
        "Dependents": "부양가족 유무",
        "tenure": "가입 기간(개월)",
        "InternetService": "인터넷 서비스",
        "OnlineSecurity": "온라인 보안",
        "TechSupport": "기술 지원",
        "Contract": "계약 형태",
        "PaperlessBilling": "전자청구서",
        "PaymentMethod": "결제 수단",
        "MonthlyCharges": "월 요금",
        "TotalCharges": "총 요금",
        "Churn": "이탈 여부",
    }
    return ReportContext(
        dataset=DatasetProfile(
            dataset_name="Telco 고객 이탈",
            shape={"rows": 7043, "cols": 21},
            dtypes=dtypes,
            missing_rate={**{c: 0.0 for c in dtypes}, "TotalCharges": 0.0016},
            cardinality={"Churn": 2, "Contract": 3, "PaymentMethod": 4, "InternetService": 3, "tenure": 73, "gender": 2},
            detected_target="Churn",
            detected_id_cols=["customerID"],
            categorical_top={
                "Churn": [
                    {"value": "No", "count": 5174},
                    {"value": "Yes", "count": 1869},
                ]
            },
            numeric_stats={
                "tenure": {"min": 0.0, "max": 72.0, "mean": 32.4},
                "MonthlyCharges": {"min": 18.25, "max": 118.75, "mean": 64.76},
            },
        ),
        domain=DomainContext(
            inferred_industry="통신(텔레콤)",
            inferred_use_case="고객 이탈 예측",
            glossary=glossary,
        ),
        preprocessing=PreprocessingTrace(
            applied_steps=[
                PreprocessingStep(op="impute_numeric", scope=["TotalCharges"], rationale="공백 11건 중앙값 대치"),
                PreprocessingStep(op="encode_categorical", scope=["Contract", "PaymentMethod", "InternetService"], rationale="범주형 인코딩"),
                PreprocessingStep(op="scale_numeric", scope=["tenure", "MonthlyCharges", "TotalCharges"], rationale="표준화"),
                PreprocessingStep(op="drop_id", scope=["customerID"], rationale="식별자 누수 방지"),
            ],
            leakage_checks=[
                {"check": "타깃-파생 변수 상관 점검", "passed": True},
                {"check": "TotalCharges 시점 누수 점검", "passed": True},
            ],
        ),
        features=FeatureEngineering(
            created=[
                FeatureSpec(name="tenure_group", formula="가입기간 구간화", rationale="초기 이탈 구간 포착"),
                FeatureSpec(name="charge_per_tenure", formula="총요금/가입기간", rationale="누적 가치 대비 부담"),
                FeatureSpec(name="service_count", formula="가입 서비스 수 합산", rationale="묶임 정도(락인) 대리"),
            ],
            dropped=[
                {"name": "customerID", "reason": "식별자"},
                {"name": "PhoneService", "reason": "MultipleLines와 중복"},
            ],
            selection_method="중요도 기반 상위 K + 다중공선성 제거",
            final_feature_count=30,
        ),
        eda=EDAFindings(
            charts=[
                EDAChart(
                    title_ko="계약 형태별 이탈률",
                    finding="월단위 계약의 이탈률이 42.7%로 압도적이다",
                    numbers=[
                        {"name": "월단위", "value": 42.7},
                        {"name": "1년", "value": 11.3},
                        {"name": "2년", "value": 2.8},
                    ],
                ),
                EDAChart(
                    title_ko="가입 기간별 이탈률",
                    chart_type="line",
                    finding="가입 1년 이내 고객의 이탈이 47%로 집중된다",
                    numbers=[
                        {"name": "0-12개월", "value": 47.4},
                        {"name": "13-48개월", "value": 23.0},
                        {"name": "49개월+", "value": 9.5},
                    ],
                ),
                EDAChart(
                    title_ko="결제 수단별 이탈률",
                    chart_type="hbar",
                    finding="전자수표 결제 고객의 이탈률이 45%로 가장 높다",
                    numbers=[
                        {"name": "전자수표", "value": 45.3},
                        {"name": "우편수표", "value": 19.1},
                        {"name": "자동이체", "value": 16.7},
                    ],
                ),
            ],
            data_quality_issues=[{"issue": "TotalCharges 공백 11건", "severity": "low"}],
            segment_insights=[
                {"insight": "월단위·광케이블·전자수표 결합 고객군의 이탈 위험이 가장 높다"},
                {"insight": "2년 약정 고객의 이탈은 2.8%로 가장 낮다"},
            ],
            hypothesis_tests=[{"name": "계약형태-이탈 독립성(카이제곱)", "result": "p<0.001 유의"}],
        ),
        model_selection=ModelSelection(
            chosen={
                "name": "CatBoost",
                "family": "GBM",
                "justification": "범주형 변수가 많고 클래스가 불균형한 본 데이터에 가장 적합",
            },
            candidates=[
                ModelCandidate(name="CatBoost", score=0.847, family="GBM", why_tried="범주형 자동 처리·불균형 견고성"),
                ModelCandidate(name="XGBoost", score=0.841, why_dropped="성능 근소 열위에 범주형 수동 인코딩 부담"),
                ModelCandidate(name="RandomForest", score=0.836, why_dropped="확률 보정이 약하고 고차원 상호작용 포착 열위"),
                ModelCandidate(name="LogReg", score=0.812, why_dropped="비선형 관계·변수 상호작용을 담지 못함"),
            ],
            baselines=BaselineSet(naive={"name": "무작위 기준선", "score": 0.5}),
        ),
        evaluation=Evaluation(
            primary_metric={"name": "val_roc_auc", "value": 0.847, "direction": "higher_better"},
            metrics={
                "val_roc_auc": {"value": 0.847},
                "val_pr_auc": {"value": 0.66},
                "val_f1": {"value": 0.62},
                "val_recall": {"value": 0.78},
                "val_precision": {"value": 0.52},
                "val_accuracy": {"value": 0.80},
            },
            per_segment=[
                {"segment": "월단위 계약", "size": 3875, "churn_rate": 0.427, "monthly": 74.4, "value": "이탈 42.7%"},
                {"segment": "1년 계약", "size": 1473, "churn_rate": 0.113, "monthly": 65.0, "value": "이탈 11.3%"},
                {"segment": "2년 계약", "size": 1695, "churn_rate": 0.028, "monthly": 60.8, "value": "이탈 2.8%"},
            ],
            business_kpi=[
                BusinessKPI(
                    name="고위험군 선제 대응 시 월 이탈률 감소",
                    unit="%p",
                    estimated_value=3.5,
                    assumptions=["고위험 상위 10% 캠페인 집행", "캠페인 수용률 12% 가정"],
                    confidence="low",
                )
            ],
        ),
        interpretation=Interpretation(
            global_importance=[
                GlobalImportance(feature="Contract", importance=0.28),
                GlobalImportance(feature="tenure", importance=0.22),
                GlobalImportance(feature="MonthlyCharges", importance=0.16),
                GlobalImportance(feature="InternetService", importance=0.11),
                GlobalImportance(feature="PaymentMethod", importance=0.08),
            ],
            per_feature_story={
                "Contract": "월단위 계약은 약정 잠금이 없어 이탈 장벽이 낮다",
                "tenure": "가입 초기 6개월은 관계가 얕아 이탈이 집중된다",
                "MonthlyCharges": "고요금 구간은 체감 가치 대비 부담이 커 이탈을 부른다",
            },
            segment_drivers=[{"insight": "광케이블+전자수표 결합 고객이 최고 위험군이다"}],
        ),
        limitations=Limitations(
            model_caveats=[
                "요금제 개편 등 분포 변화에 민감하다",
                "스냅샷 기준 — 시계열 이탈 동학은 미반영",
            ],
            data_gaps=[LimitationItem(description="고객 만족도·상담 이력이 미포함된다")],
        ),
        meta=Meta(
            category="tabular_ml",
            user_question="어떤 고객이 왜 이탈하며, 누구에게 무엇으로 개입해야 가장 효율적으로 막을 수 있는가?",
            user_intent="통신 고객 이탈 예측",
            business_context=(
                "이탈률 상승으로 가입자 유지 비용이 증가하고 있다. "
                "고위험 고객을 선별해 선제 유지(retention) 프로그램을 집행하는 것이 목표다."
            ),
            classification="Confidential",
            generated_at="2026-06-10T00:00:00",
        ),
    )


def _titanic_ctx():
    """타이타닉 생존 예측 ReportContext — 실 데이터(891명) 기반 통계로 구성.

    데이터 사실 (실 CSV n=891):
        - 생존률 38.4% (다수 클래스 = 사망 61.6%)
        - 성별: 여성 74.2% vs 남성 18.9% (3.9배)
        - 등급: 1등 63.0% vs 3등 24.2% (2.6배)
        - 결측: Age 19.87%, Cabin 77.10%, Embarked 0.22%
    """
    from outputs.context.schema import (
        BaselineSet,
        BusinessKPI,
        DatasetProfile,
        DomainContext,
        EDAChart,
        EDAFindings,
        Evaluation,
        FeatureEngineering,
        FeatureSpec,
        GlobalImportance,
        Interpretation,
        LimitationItem,
        Limitations,
        Meta,
        ModelCandidate,
        ModelSelection,
        PreprocessingStep,
        PreprocessingTrace,
        ReportContext,
    )

    dtypes = {
        "PassengerId": "int64",
        "Survived": "int64",
        "Pclass": "int64",
        "Name": "object",
        "Sex": "object",
        "Age": "float64",
        "SibSp": "int64",
        "Parch": "int64",
        "Ticket": "object",
        "Fare": "float64",
        "Cabin": "object",
        "Embarked": "object",
    }
    glossary = {
        "PassengerId": "승객 ID",
        "Survived": "생존 여부",
        "Pclass": "좌석 등급",
        "Name": "성명",
        "Sex": "성별",
        "Age": "나이 (세)",
        "SibSp": "형제·배우자 동승 수",
        "Parch": "부모·자녀 동승 수",
        "Ticket": "티켓 번호",
        "Fare": "운임",
        "Cabin": "객실 번호",
        "Embarked": "승선항",
    }
    return ReportContext(
        dataset=DatasetProfile(
            dataset_name="타이타닉 승객 명부",
            shape={"rows": 891, "cols": 12},
            dtypes=dtypes,
            missing_rate={
                **{c: 0.0 for c in dtypes},
                "Age": 0.1987,
                "Cabin": 0.7710,
                "Embarked": 0.0022,
            },
            cardinality={"Survived": 2, "Pclass": 3, "Sex": 2, "Embarked": 3, "Cabin": 147, "Ticket": 681},
            detected_target="Survived",
            detected_id_cols=["PassengerId", "Ticket"],
            categorical_top={
                "Survived": [
                    {"value": "0", "count": 549},
                    {"value": "1", "count": 342},
                ]
            },
            numeric_stats={
                "Age": {"min": 0.42, "max": 80.0, "mean": 29.70},
                "Fare": {"min": 0.0, "max": 512.33, "mean": 32.20},
                "Pclass": {"min": 1.0, "max": 3.0, "mean": 2.31},
            },
        ),
        domain=DomainContext(
            inferred_industry="역사 데이터 (재난·사회 분석)",
            inferred_use_case="생존 결정 요인 규명 및 예측",
            glossary=glossary,
        ),
        preprocessing=PreprocessingTrace(
            applied_steps=[
                PreprocessingStep(op="impute_numeric", scope=["Age"], rationale="결측 19.87%, 성별·등급 그룹 중앙값으로 대치"),
                PreprocessingStep(op="drop", scope=["Cabin"], rationale="결측 77.10% — 정보 손실 위험으로 제외, 등급(Pclass)이 대리 신호"),
                PreprocessingStep(op="impute_categorical", scope=["Embarked"], rationale="결측 2건 최빈값(S) 대치"),
                PreprocessingStep(op="encode_categorical", scope=["Sex", "Embarked", "Pclass"], rationale="범주형 원-핫 인코딩"),
                PreprocessingStep(op="scale_numeric", scope=["Age", "Fare"], rationale="표준화"),
                PreprocessingStep(op="drop_id", scope=["PassengerId", "Ticket", "Name"], rationale="식별자 누수 방지"),
            ],
            leakage_checks=[
                {"check": "타깃-파생 변수 상관 점검", "passed": True},
                {"check": "Name에서 호칭(Title) 추출 시 시점 누수 점검", "passed": True},
            ],
        ),
        features=FeatureEngineering(
            created=[
                FeatureSpec(name="Title", formula="Name에서 호칭 추출(Mr/Mrs/Miss/Master)", rationale="성별·연령 결합 신호로 작용"),
                FeatureSpec(name="FamilySize", formula="SibSp + Parch + 1", rationale="동승 가족 규모는 생존 동학에 영향"),
                FeatureSpec(name="IsAlone", formula="FamilySize == 1", rationale="단독 승객의 생존 패턴이 다름"),
                FeatureSpec(name="AgeBin", formula="아동(≤12)/청소년/청년/중년/노년 구간화", rationale="구간별 생존 격차 포착"),
            ],
            dropped=[
                {"name": "Cabin", "reason": "결측 77.1%"},
                {"name": "Ticket", "reason": "식별자성 — 신호 없음"},
            ],
            selection_method="중요도 기반 상위 K + 다중공선성 제거",
            final_feature_count=15,
        ),
        eda=EDAFindings(
            charts=[
                EDAChart(
                    title_ko="성별 생존률",
                    finding="여성 생존률이 74.2%로 남성(18.9%) 대비 압도적",
                    numbers=[
                        {"name": "여성", "value": 74.2},
                        {"name": "남성", "value": 18.9},
                    ],
                ),
                EDAChart(
                    title_ko="좌석 등급별 생존률",
                    finding="1등 객실 생존률이 3등(24.2%) 대비 2.6배 높다",
                    numbers=[
                        {"name": "1등", "value": 63.0},
                        {"name": "2등", "value": 47.3},
                        {"name": "3등", "value": 24.2},
                    ],
                ),
                EDAChart(
                    title_ko="나이대별 생존률",
                    chart_type="line",
                    finding="아동(≤12세) 생존률 58%, 노년(>60세) 22.7%로 단계적 감소",
                    numbers=[
                        {"name": "아동(≤12)", "value": 58.0},
                        {"name": "청소년", "value": 42.9},
                        {"name": "청년(19-35)", "value": 38.3},
                        {"name": "중년(36-60)", "value": 40.0},
                        {"name": "노년(>60)", "value": 22.7},
                    ],
                ),
                EDAChart(
                    title_ko="승선항별 생존률",
                    chart_type="hbar",
                    finding="셰르부르(C) 승선 승객의 생존률이 55.4%로 가장 높다",
                    numbers=[
                        {"name": "셰르부르(C)", "value": 55.4},
                        {"name": "퀸스타운(Q)", "value": 39.0},
                        {"name": "사우샘프턴(S)", "value": 33.7},
                    ],
                ),
            ],
            data_quality_issues=[
                {"issue": "Age 결측 177건(19.87%)"},
                {"issue": "Cabin 결측 687건(77.10%) — 컬럼 제외"},
            ],
            segment_insights=[
                {"insight": "1등 객실 여성 승객의 생존률이 96.8%로 최고치를 기록한다"},
                {"insight": "3등 객실 남성 청년(19-35세) 생존률이 12.1%로 최저, 표본 198명 중 24명만 생존"},
            ],
            hypothesis_tests=[
                {"name": "성별-생존 독립성(카이제곱)", "result": "p<0.001 유의"},
                {"name": "등급-생존 독립성(카이제곱)", "result": "p<0.001 유의"},
            ],
        ),
        model_selection=ModelSelection(
            chosen={
                "name": "CatBoost",
                "family": "GBM",
                "justification": "범주형(Sex·Embarked·Pclass) 자동 처리 + 작은 표본에서 정규화 강점",
            },
            candidates=[
                ModelCandidate(name="CatBoost", score=0.862, family="GBM", why_tried="범주형 자동 처리·소표본 안정성"),
                ModelCandidate(name="XGBoost", score=0.851, why_dropped="범주형 수동 인코딩 + 891건 규모에 약간 과적합 경향"),
                ModelCandidate(name="RandomForest", score=0.842, why_dropped="확률 보정 약하고 상호작용 포착 제한적"),
                ModelCandidate(name="LogReg", score=0.821, why_dropped="비선형(나이×등급×성별) 상호작용을 담지 못함"),
            ],
            baselines=BaselineSet(naive={"name": "다수 클래스(사망) 예측", "score": 0.616}),
        ),
        evaluation=Evaluation(
            primary_metric={"name": "val_roc_auc", "value": 0.862, "direction": "higher_better"},
            metrics={
                "val_roc_auc": {"value": 0.862},
                "val_pr_auc": {"value": 0.81},
                "val_f1": {"value": 0.78},
                "val_recall": {"value": 0.74},
                "val_precision": {"value": 0.82},
                "val_accuracy": {"value": 0.83},
            },
            per_segment=[
                {"segment": "3등 객실 남성", "size": 347, "churn_rate": 0.865, "value": "사망 86.5%"},
                {"segment": "3등 객실 여성", "size": 144, "churn_rate": 0.500, "value": "사망 50.0%"},
                {"segment": "2등 객실 남성", "size": 108, "churn_rate": 0.843, "value": "사망 84.3%"},
                {"segment": "1등 객실 여성", "size": 94, "churn_rate": 0.032, "value": "사망 3.2%"},
            ],
            business_kpi=[
                BusinessKPI(
                    name="고위험군(3등·남성·청년) 사전 식별 정확도",
                    unit="%",
                    estimated_value=82.0,
                    assumptions=["검증셋 기준 정밀도", "운영 임계값 0.5"],
                    confidence="medium",
                )
            ],
        ),
        interpretation=Interpretation(
            global_importance=[
                GlobalImportance(feature="Sex", importance=0.34),
                GlobalImportance(feature="Pclass", importance=0.22),
                GlobalImportance(feature="Age", importance=0.15),
                GlobalImportance(feature="Fare", importance=0.11),
                GlobalImportance(feature="FamilySize", importance=0.09),
                GlobalImportance(feature="Embarked", importance=0.05),
            ],
            per_feature_story={
                "Sex": "여성 우선 구조 정책('여성과 어린이 먼저')이 생존을 가른 1차 변수다",
                "Pclass": "상위 등급은 상갑판 근접 + 구명정 접근성으로 구조 기회가 구조적으로 높았다",
                "Age": "아동 우선 구조와 노년 신체 한계가 양 극단의 격차를 만들었다",
                "Fare": "운임은 등급의 대리 신호로 작동 — 독립 기여는 제한적",
            },
            segment_drivers=[
                {"insight": "3등 객실 남성 청년이 최고 위험군 — 표본 347명 중 86.5%가 사망"},
                {"insight": "1등 객실 여성·아동이 최저 위험군 — 96.8% 생존"},
            ],
        ),
        limitations=Limitations(
            model_caveats=[
                "표본 891명은 모델링 가능하나 단일 사건의 단일 시점 데이터로 시대·상황 외삽이 제한적이다",
                "Cabin 77% 결측 — 객실 위치(갑판) 신호가 모델에 미반영, 등급(Pclass)이 부분 대리만 수행",
                "당시 비상 대응 매뉴얼·구조 순서 등 외부 컨텍스트가 데이터에 없어 인과 추론은 제한된다",
            ],
            data_gaps=[
                LimitationItem(description="구명정 배정·승선 순서 등 시점 정보가 누락돼 시간 동학을 추적할 수 없다"),
                LimitationItem(description="객실 정확 위치(갑판·구역)가 결측되어 물리적 구조 기회 차이를 정량화하지 못한다"),
            ],
        ),
        meta=Meta(
            category="tabular_ml",
            user_question="누가, 왜 살아남았는가? 어떤 요인이 생존을 가장 강하게 결정했는가?",
            user_intent="타이타닉 생존 결정 요인 분석 및 예측 모델 수립",
            business_context=(
                "역사 재난 데이터 분석을 통해 사회·구조적 격차가 생존에 미친 영향을 정량화하고, "
                "현대 재난 대응의 우선순위 설계·우선 구조 의사결정 알고리즘 설계의 근거 자료로 활용한다."
            ),
            classification="Public",
            generated_at="2026-06-11T00:00:00",
        ),
    )


def main(argv: list[str]) -> str:
    import re as _re

    from outputs.architect.skeletons import report_skeleton
    from outputs.carriers.pdf_carrier import generate_pdf
    from outputs.context.schema import ReportContext

    arg1 = argv[1] if len(argv) > 1 else None
    explicit_out = argv[2] if len(argv) > 2 else None  # 사용자가 출력 경로 직접 지정 시 우선

    # ctx 선택 + 주제(topic) 결정 — 주제는 넣는 데이터에 따라 자동
    if arg1 == "titanic":
        ctx = _titanic_ctx()
        topic = "titanic"
        print("[preview] ctx ← 내장 샘플 (타이타닉 생존 예측, n=891)")
    elif arg1:
        ctx = ReportContext.from_dict(json.loads(Path(arg1).read_text(encoding="utf-8")))
        # 주제 = 덤프 안 데이터셋명 우선, 없으면 파일 이름
        try:
            _ds = getattr(getattr(ctx, "dataset", None), "dataset_name", "") or ""
        except Exception:
            _ds = ""
        topic = _ds or Path(arg1).stem
        print(f"[preview] ctx ← dump: {arg1}")
    else:
        ctx = _sample_ctx()
        topic = "telco"
        print("[preview] ctx ← 내장 샘플 (Telco 고객 이탈)")

    # 주제를 파일명에 안전하게 (공백·특수문자 → _). 기본 출력은 outputs/ 안(호스트 마운트로 바로 보임).
    safe_topic = _re.sub(r"[^0-9A-Za-z가-힣]+", "_", str(topic)).strip("_") or "preview"
    out = explicit_out or str(Path(__file__).resolve().parent / f"report_preview3_{safe_topic}.pdf")

    plan = report_skeleton.build(ctx)
    path = generate_pdf(plan, ctx, out)
    print(f"[preview] PDF → {Path(path).resolve()}")
    return path


if __name__ == "__main__":
    main(sys.argv)
