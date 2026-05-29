"""jh Day 7 — test_evaluator.py: 정형 평가 (accuracy/f1/ROC/calibration + 임계치 sweep).

DoD: ``calibration_brier`` 필드. predictions 누락 시 graceful degrade.
sklearn datasets(breast_cancer/iris/diabetes) 로 실모델 예측을 state 에 채워 검증.
"""

from __future__ import annotations

import pytest

from agents.handlers.tabular.evaluator import evaluate

REQUIRED_KEYS = {
    "passed",
    "rationale",
    "threshold_violations",
    "metrics",
    "task_type",
    "calibration_brier",
    "threshold_sweep",
    "best_threshold",
}


def _state_with_predictions(category, target_column, task, y_true, y_pred, y_prob, metrics=None, task_type=None):
    from ada.core.state import PipelineState

    best_model = {"model_name": "RF", "metrics": metrics or {}}
    if task_type is not None:
        best_model["task_type"] = task_type
    y_prob_ser = [list(r) for r in y_prob] if getattr(y_prob, "ndim", 1) == 2 else list(y_prob)
    return PipelineState(
        job_id="00000000-0000-0000-0000-0000000000e7",
        file_id="uploads/test/eval.csv",
        category=category,
        target_column=target_column,
        task=task,
        user_intent="평가 검증",
        best_model=best_model,
        category_extras={
            "tabular": {
                "predictions": {
                    "y_true": list(y_true),
                    "y_pred": list(y_pred),
                    "y_prob": y_prob_ser,
                }
            }
        },
    )


@pytest.fixture(scope="module")
def binary_preds():
    from sklearn.datasets import load_breast_cancer
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split

    X, y = load_breast_cancer(return_X_y=True)
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.3, random_state=0, stratify=y)
    clf = RandomForestClassifier(n_estimators=40, random_state=0).fit(Xtr, ytr)
    return yte, clf.predict(Xte), clf.predict_proba(Xte)[:, 1]


@pytest.fixture(scope="module")
def multi_preds():
    from sklearn.datasets import load_iris
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split

    X, y = load_iris(return_X_y=True)
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.3, random_state=0, stratify=y)
    clf = RandomForestClassifier(n_estimators=40, random_state=0).fit(Xtr, ytr)
    return yte, clf.predict(Xte), clf.predict_proba(Xte)


@pytest.fixture(scope="module")
def reg_preds():
    from sklearn.datasets import load_diabetes
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.model_selection import train_test_split

    X, y = load_diabetes(return_X_y=True)
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.3, random_state=0)
    reg = RandomForestRegressor(n_estimators=40, random_state=0).fit(Xtr, ytr)
    return yte, reg.predict(Xte)


class TestContract:
    def test_required_keys_present(self, binary_preds):
        yt, yp, pr = binary_preds
        result = evaluate(_state_with_predictions("tabular_ml", "y", "classification", yt, yp, pr))
        assert REQUIRED_KEYS.issubset(result.keys())

    def test_no_state_mutation(self, binary_preds):
        yt, yp, pr = binary_preds
        state = _state_with_predictions("tabular_ml", "y", "classification", yt, yp, pr)
        before = id(state.category_extras)
        evaluate(state)
        assert id(state.category_extras) == before
        assert "predictions" in state.category_extras["tabular"]


class TestBinary:
    def test_calibration_brier_is_float(self, binary_preds):
        """DoD: calibration_brier 필드가 0~1 사이 실수."""
        yt, yp, pr = binary_preds
        result = evaluate(_state_with_predictions("tabular_ml", "y", "classification", yt, yp, pr))
        assert result["task_type"] == "binary"
        assert isinstance(result["calibration_brier"], float)
        assert 0.0 <= result["calibration_brier"] <= 1.0
        assert result["metrics"]["calibration_brier"] == result["calibration_brier"]

    def test_core_metrics_computed(self, binary_preds):
        yt, yp, pr = binary_preds
        m = evaluate(_state_with_predictions("tabular_ml", "y", "classification", yt, yp, pr))["metrics"]
        for k in ("val_accuracy", "val_f1", "val_precision", "val_recall"):
            assert 0.0 <= m[k] <= 1.0

    def test_roc_auc_computed(self, binary_preds):
        yt, yp, pr = binary_preds
        result = evaluate(_state_with_predictions("tabular_ml", "y", "classification", yt, yp, pr))
        assert isinstance(result["roc_auc"], float)
        assert 0.5 <= result["roc_auc"] <= 1.0

    def test_threshold_sweep(self, binary_preds):
        yt, yp, pr = binary_preds
        result = evaluate(_state_with_predictions("tabular_ml", "y", "classification", yt, yp, pr))
        sweep = result["threshold_sweep"]
        assert len(sweep) == 19
        assert all({"threshold", "f1", "precision", "recall"} <= set(row) for row in sweep)
        assert result["best_threshold"] in [r["threshold"] for r in sweep]
        best_row = next(r for r in sweep if r["threshold"] == result["best_threshold"])
        assert best_row["f1"] == max(r["f1"] for r in sweep)

    def test_calibration_ece_present(self, binary_preds):
        yt, yp, pr = binary_preds
        result = evaluate(_state_with_predictions("tabular_ml", "y", "classification", yt, yp, pr))
        assert isinstance(result["calibration_ece"], float)
        assert result["calibration_ece"] >= 0.0


class TestMulticlass:
    def test_multiclass_metrics(self, multi_preds):
        yt, yp, pr = multi_preds
        result = evaluate(
            _state_with_predictions("tabular_ml", "y", "classification", yt, yp, pr, task_type="multiclass")
        )
        assert result["task_type"] == "multiclass"
        assert 0.0 <= result["metrics"]["val_f1"] <= 1.0
        assert isinstance(result["roc_auc"], float)
        assert isinstance(result["calibration_brier"], float)
        assert result["threshold_sweep"] == []


class TestRegression:
    def test_regression_metrics(self, reg_preds):
        yt, yp = reg_preds
        state = _state_with_predictions("tabular_ml", "Fare", "regression", yt, yp, yp)
        result = evaluate(state)
        assert result["task_type"] == "regression"
        assert "val_r2" in result["metrics"] and "val_rmse" in result["metrics"]
        assert result["calibration_brier"] is None
        assert result["threshold_sweep"] == []


class TestGracefulDegrade:
    def test_no_predictions_falls_back_to_threshold_check(self):
        """예측 없을 때: Day6 임계치 판정만 동작, brier=None."""
        from ada.core.state import PipelineState

        state = PipelineState(
            job_id="00000000-0000-0000-0000-0000000000e8",
            file_id="uploads/test/eval.csv",
            category="tabular_ml",
            target_column="Survived",
            user_intent="평가",
            best_model={"model_name": "XGB", "metrics": {"val_f1": 0.80, "val_accuracy": 0.82}},
        )
        result = evaluate(state)
        assert result["passed"] is True
        assert result["calibration_brier"] is None
        assert result["threshold_sweep"] == []

    def test_threshold_violation_detected(self):
        from ada.core.state import PipelineState

        state = PipelineState(
            job_id="00000000-0000-0000-0000-0000000000e9",
            file_id="uploads/test/eval.csv",
            category="tabular_ml",
            target_column="Survived",
            user_intent="평가",
            best_model={"model_name": "XGB", "metrics": {"val_f1": 0.50, "val_accuracy": 0.55}},
        )
        result = evaluate(state)
        assert result["passed"] is False
        assert len(result["threshold_violations"]) >= 1

    def test_missing_yprob_skips_roc_and_calibration(self, binary_preds):
        """y_prob 제거 -> accuracy/f1 정상, roc/brier/sweep 은 skip."""
        from ada.core.state import PipelineState

        yt, yp, _ = binary_preds
        state = PipelineState(
            job_id="00000000-0000-0000-0000-0000000000ea",
            file_id="uploads/test/eval.csv",
            category="tabular_ml",
            target_column="y",
            task="classification",
            user_intent="평가",
            best_model={"model_name": "RF"},
            category_extras={"tabular": {"predictions": {"y_true": list(yt), "y_pred": list(yp)}}},
        )
        result = evaluate(state)
        assert 0.0 <= result["metrics"]["val_f1"] <= 1.0
        assert result["calibration_brier"] is None
        assert result["roc_auc"] is None
        assert result["threshold_sweep"] == []
