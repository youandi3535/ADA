"""jh Day 9 H2 — pipeline.collect_artifacts: 예측 + 피처중요도 수집.

차트/평가가 쓰는 y_true/y_pred/y_prob + feature_importances/feature_names/task_type 를
모델 객체에서 안전하게 뽑는다. 예외/누락은 None graceful degrade.
"""

from __future__ import annotations


def _pipe():
    from pipelines.tabular_ml.pipeline import TabularMLPipeline

    return TabularMLPipeline()


def test_binary_artifacts():
    from sklearn.datasets import load_breast_cancer
    from sklearn.ensemble import RandomForestClassifier

    data = load_breast_cancer()
    clf = RandomForestClassifier(n_estimators=20, random_state=0).fit(data.data, data.target)
    a = _pipe().collect_artifacts(clf, data.data, data.target, "classification", data.feature_names.tolist())
    assert a["task_type"] == "binary"
    assert len(a["y_true"]) == len(a["y_pred"]) == len(data.target)
    assert a["y_prob"] is not None and len(a["y_prob"]) == len(data.target)
    assert len(a["feature_importances"]) == data.data.shape[1]
    assert a["feature_names"][0] == "mean radius"


def test_multiclass_artifacts():
    from sklearn.datasets import load_iris
    from sklearn.ensemble import RandomForestClassifier

    data = load_iris()
    clf = RandomForestClassifier(n_estimators=20, random_state=0).fit(data.data, data.target)
    a = _pipe().collect_artifacts(clf, data.data, data.target, "classification", list(data.feature_names))
    assert a["task_type"] == "multiclass"
    # 다중분류 y_prob 는 2D (행마다 클래스 확률)
    assert isinstance(a["y_prob"][0], list) and len(a["y_prob"][0]) == 3


def test_regression_artifacts():
    from sklearn.datasets import load_diabetes
    from sklearn.ensemble import RandomForestRegressor

    data = load_diabetes()
    reg = RandomForestRegressor(n_estimators=20, random_state=0).fit(data.data, data.target)
    a = _pipe().collect_artifacts(reg, data.data, data.target, "regression", list(data.feature_names))
    assert a["task_type"] == "regression"
    assert a["y_prob"] is None
    assert len(a["feature_importances"]) == data.data.shape[1]


def test_coef_fallback_for_linear():
    from sklearn.datasets import load_breast_cancer
    from sklearn.linear_model import LogisticRegression

    data = load_breast_cancer()
    clf = LogisticRegression(max_iter=500).fit(data.data, data.target)
    a = _pipe().collect_artifacts(clf, data.data, data.target, "classification", data.feature_names.tolist())
    # LogisticRegression 은 feature_importances_ 없음 → coef_ 폴백
    assert a["feature_importances"] is not None
    assert len(a["feature_importances"]) == data.data.shape[1]


def test_feature_names_length_mismatch_fallback():
    from sklearn.datasets import load_iris
    from sklearn.ensemble import RandomForestClassifier

    data = load_iris()
    clf = RandomForestClassifier(n_estimators=10, random_state=0).fit(data.data, data.target)
    a = _pipe().collect_artifacts(clf, data.data, data.target, "classification", ["only_one_name"])
    assert a["feature_names"] == [f"f{i}" for i in range(data.data.shape[1])]


def test_bad_model_graceful():
    class _Bad:
        def predict(self, X):
            raise RuntimeError("boom")

    a = _pipe().collect_artifacts(_Bad(), [[1, 2]], [0], "classification", ["a", "b"])
    assert a["y_true"] is None and a["y_pred"] is None and a["feature_importances"] is None
