"""tests.integration._skeleton_ctx_factory — 4 카테고리 skeleton 회귀 테스트용 ctx 픽스처.

ml/dl/timeseries/anomaly 4 카테고리 skeleton 의 ``build()`` 회귀 테스트에서 단일
진실원으로 사용할 ctx 생성 헬퍼.

* ``make_empty_ctx(category)`` — 최소 필드만 가진 ctx (placeholder 빌더 경로 검증)
* ``make_rich_ctx(category, verdict)`` — 풍부 ctx + verdict 분기 (어조 분기 검증)

설계 원칙:
    - 카테고리별 *고유* 파라미터 (timeseries 의 freq, anomaly 의 contamination 등) 는
      ``_CATEGORY_DEFAULTS`` 에 캡슐화.
    - verdict 는 evaluation.verdict 에만 영향 — 다른 필드는 동일.
    - schema 변경 시 본 파일 한 곳만 손보면 4 카테고리 모두 자동 반영.
"""

from __future__ import annotations

from typing import Any

from outputs.context.schema import (
    BaselineSet,
    BusinessKPI,
    CodeArtifacts,
    DatasetProfile,
    DomainContext,
    EDAChart,
    EDAFindings,
    Evaluation,
    FeatureEngineering,
    FeatureSpec,
    GlobalImportance,
    Interpretation,
    Limitations,
    Meta,
    ModelSelection,
    PreprocessingStep,
    PreprocessingTrace,
    ReportContext,
    Training,
    TrainingRun,
)

# ==============================================================
# 카테고리별 디폴트 (모델 / 메트릭 / 하이퍼파라미터)
# ==============================================================


_CATEGORY_DEFAULTS: dict[str, dict[str, Any]] = {
    "tabular_ml": {
        "chosen": {"name": "CatBoost", "family": "GBM"},
        "primary_metric": {"name": "accuracy", "value": 0.87, "direction": "maximize", "ref_id": "pm_ml"},
        "extra_metrics": {"f1": {"value": 0.83}, "roc_auc": {"value": 0.91}, "recall": {"value": 0.80}},
        "hyperparameters": {"n_estimators": 500, "depth": 6, "learning_rate": 0.05},
        "naive_baseline": {"name": "Majority Class", "score": 0.62},
        "user_intent": "고객 이탈 예측",
        "industry": "Telecom",
        "use_case": "Churn prediction",
    },
    "tabular_dl": {
        "chosen": {"name": "TabNet", "family": "DL"},
        "primary_metric": {"name": "f1", "value": 0.79, "direction": "maximize", "ref_id": "pm_dl"},
        "extra_metrics": {"accuracy": {"value": 0.85}, "roc_auc": {"value": 0.88}, "recall": {"value": 0.77}},
        "hyperparameters": {
            "n_layers": 6, "hidden_dim": 64, "n_heads": 4,
            "embedding_dim": 32, "n_params": 142_000, "learning_rate": 0.001, "batch_size": 256,
        },
        "naive_baseline": {"name": "CatBoost ML Best", "score": 0.72},
        "user_intent": "고차원 categorical 분류",
        "industry": "FinTech",
        "use_case": "Default risk classification",
    },
    "timeseries": {
        "chosen": {"name": "Prophet", "family": "TS"},
        "primary_metric": {"name": "mape", "value": 0.09, "direction": "minimize", "ref_id": "pm_ts"},
        "extra_metrics": {"mae": {"value": 12.5}, "rmse": {"value": 18.3}, "coverage": {"value": 0.93}},
        "hyperparameters": {"seasonality_mode": "multiplicative", "changepoint_prior_scale": 0.05},
        "naive_baseline": {"name": "Seasonal Naive", "score": 0.18},
        "user_intent": "월간 매출 예측",
        "industry": "Retail",
        "use_case": "Monthly sales forecasting",
    },
    "anomaly_detection": {
        "chosen": {"name": "IsolationForest", "family": "Tree"},
        "primary_metric": {"name": "pr_auc", "value": 0.82, "direction": "maximize", "ref_id": "pm_an"},
        "extra_metrics": {"roc_auc": {"value": 0.97}, "recall_at_k": {"value": 0.78}, "precision_at_k": {"value": 0.66}},
        "hyperparameters": {"n_estimators": 200, "max_samples": "auto", "contamination": 0.001},
        "naive_baseline": {"name": "Z-score 룰", "score": 0.15},
        "user_intent": "신용카드 사기 탐지",
        "industry": "Finance",
        "use_case": "Credit card fraud detection",
        # anomaly 만 categorical_top (이상 비율 추출용) 추가
        "categorical_top": {"Class": [{"value": 0, "count": 284315}, {"value": 1, "count": 492}]},
        "calibration": {
            "normal_peak": 0.05, "anomaly_peak": 0.72, "bhattacharyya": 0.84,
            "thresholds": {"kde_crossing": 0.45, "cost_optimal": 0.42, "auto_block": 0.65},
        },
    },
}


# ==============================================================
# 공개 API
# ==============================================================


def make_empty_ctx(category: str) -> ReportContext:
    """최소 필드만 — placeholder 경로 검증용."""
    return ReportContext(
        meta=Meta(
            category=category,
            classification="internal",
            user_intent=f"{category} 회귀 테스트",
        )
    )


def make_rich_ctx(category: str, verdict: str = "adopt") -> ReportContext:
    """풍부 ctx — verdict 분기 + 모든 슬라이드의 동적 경로 검증.

    Args:
        category: tabular_ml | tabular_dl | timeseries | anomaly_detection
        verdict: adopt | iterate | reject
    """
    if category not in _CATEGORY_DEFAULTS:
        raise ValueError(f"unsupported category: {category}")
    cfg = _CATEGORY_DEFAULTS[category]

    # Dataset (anomaly 만 categorical_top 채움)
    dataset = DatasetProfile(
        dataset_name=f"{category}_sample.csv",
        shape={"rows": 10_000, "cols": 12},
        detected_target=("Class" if category == "anomaly_detection" else "target"),
        dtypes={f"feat_{i}": ("float64" if i % 2 == 0 else "object") for i in range(12)},
        cardinality={f"feat_{i}": (i + 1) * 100 for i in range(12)},
        numeric_stats={"feat_0": {"mean": 1.5, "std": 0.4}, "feat_2": {"mean": 8.0, "std": 2.1}},
        categorical_top=cfg.get("categorical_top", {}),
    )

    # Domain (user-provided)
    domain = DomainContext(
        inferred_industry=cfg["industry"],
        inferred_use_case=cfg["use_case"],
        domain_source="user",
    )

    # Preprocessing 1단계
    preprocessing = PreprocessingTrace(
        applied_steps=[
            PreprocessingStep(
                op="impute_median",
                scope=["feat_0", "feat_2"],
                rationale="결측 < 5% — 중앙값 대치로 분포 보강",
                before_stats={"missing_rate": 0.04},
                after_stats={"missing_rate": 0.0},
            ),
        ],
    )

    # Features 2개 (파생 피처)
    features = FeatureEngineering(
        created=[
            FeatureSpec(
                name="feat_ratio",
                formula="feat_0 / (feat_2 + 1)",
                rationale="비율 변수 — 비선형 신호 포착",
                importance=0.12,
            ),
            FeatureSpec(
                name="feat_log",
                formula="log1p(feat_0)",
                rationale="스케일 보정",
                importance=0.08,
            ),
        ],
        final_feature_count=14,
        selection_method="recursive_feature_elimination",
    )

    # EDA 차트 2개
    eda = EDAFindings(
        charts=[
            EDAChart(
                path="charts/eda_0.png",
                chart_type="hist",
                x="feat_0",
                title_ko="feat_0 분포",
                finding="feat_0 이 타겟과 강한 양의 상관 (r=0.62)",
                severity="important",
                numbers=[{"name": "r", "value": 0.62}],
                callouts=[{"position": "top", "text": "r=0.62 - 강한 양의 상관"}],
                ref_id="ed_0",
            ),
            EDAChart(
                path="charts/eda_1.png",
                chart_type="corr_heatmap",
                title_ko="변수 상관",
                finding="feat_0 / feat_2 다중공선 r=0.78",
                severity="info",
                ref_id="ed_1",
            ),
        ],
    )

    # Model selection
    model_selection = ModelSelection(
        chosen=cfg["chosen"],
        candidates=[],
        baselines=BaselineSet(naive=cfg["naive_baseline"]),
    )

    # Training
    training = Training(
        runs=[
            TrainingRun(
                run_id="run_001",
                model_name=cfg["chosen"]["name"],
                hyperparameters=cfg["hyperparameters"],
                best_iteration=200,
                duration_sec=120.0,
                resource={"device": "cpu"},
                train_curves={"epoch": [1, 2, 3], "train_loss": [0.5, 0.3, 0.2], "val_loss": [0.6, 0.4, 0.3]},
            ),
        ],
    )

    # Evaluation + verdict
    evaluation = Evaluation(
        primary_metric=cfg["primary_metric"],
        metrics=cfg["extra_metrics"],
        per_segment=[
            {"segment": "A", "metric": cfg["primary_metric"]["name"], "value": cfg["primary_metric"]["value"] + 0.02},
            {"segment": "B", "metric": cfg["primary_metric"]["name"], "value": cfg["primary_metric"]["value"] - 0.02},
        ],
        confusion_matrix={"tp": 380, "fp": 90, "fn": 112, "tn": 8000},
        calibration=cfg.get("calibration") or {"ece": 0.04},
        business_kpi=[BusinessKPI(name="예상 효과", unit="원/년", estimated_value=120_000_000)],
        gate_passed=(verdict == "adopt"),
        gate_rationale=(
            f"{cfg['primary_metric']['name']} {cfg['primary_metric']['value']} - 기준 충족"
            if verdict == "adopt"
            else "운영 임계 미달"
        ),
        verdict=verdict,
        verdict_rationale=f"{verdict} 판정",
    )

    # Interpretation
    interpretation = Interpretation(
        global_importance=[
            GlobalImportance(feature="feat_0", importance=0.32, method="shap", ref_id="imp_0"),
            GlobalImportance(feature="feat_ratio", importance=0.24, method="shap", ref_id="imp_1"),
            GlobalImportance(feature="feat_2", importance=0.18, method="shap"),
            GlobalImportance(feature="feat_log", importance=0.12, method="shap"),
            GlobalImportance(feature="feat_4", importance=0.08, method="shap"),
        ],
        local_examples=[
            {"prediction": 1, "true": 1, "anomaly_score": 0.91,
             "contributions": [{"feature": "feat_0", "value": 1.2}]},
            {"prediction": 0, "true": 0, "anomaly_score": 0.05,
             "contributions": [{"feature": "feat_2", "value": -0.4}]},
            {"prediction": 1, "true": 0, "anomaly_score": 0.78,
             "contributions": [{"feature": "feat_ratio", "value": 0.9}]},
        ],
        per_feature_story={"feat_0": "feat_0 이 가장 강한 신호"},
    )

    # Limitations
    limitations = Limitations(
        revalidation_window="3개월",
        model_caveats=["학습 데이터 외 분포는 모름"],
        distribution_shift_risk={"detected": False, "evidence": None},
    )

    # Code (Tech Stack 의 env 자동 부착용)
    code = CodeArtifacts(
        environment={
            "python": "3.11",
            "key_packages": _category_env_packages(category),
        },
    )

    return ReportContext(
        meta=Meta(
            category=category,
            classification="internal",
            user_intent=cfg["user_intent"],
            audience="external_client",
        ),
        dataset=dataset,
        domain=domain,
        preprocessing=preprocessing,
        features=features,
        eda=eda,
        model_selection=model_selection,
        training=training,
        evaluation=evaluation,
        interpretation=interpretation,
        limitations=limitations,
        code=code,
    )


def _category_env_packages(category: str) -> dict[str, str]:
    """카테고리별 핵심 패키지 버전 — Tech Stack 의 ``v{ver}`` 부착 검증용."""
    if category == "tabular_ml":
        return {"scikit-learn": "1.4.0", "catboost": "1.2.0"}
    if category == "tabular_dl":
        return {"pytorch": "2.1.0", "tabnet": "4.0.0"}
    if category == "timeseries":
        return {"statsmodels": "0.14.0", "prophet": "1.1.5"}
    if category == "anomaly_detection":
        return {"scikit-learn": "1.4.0", "pyod": "1.1.0"}
    return {}


__all__ = ["make_empty_ctx", "make_rich_ctx"]

