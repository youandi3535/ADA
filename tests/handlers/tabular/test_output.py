"""jh Day 9 — test_output.py: tabular output_extras (OUT-04 4 차트 + 통합).

DoD: OUT-04 에 ROC/Calibration/Confusion/FeatureImportance 4 차트 추가.
fake_minio monkeypatch 로 실제 MinIO 없이 검증. sklearn datasets 로 실예측 주입.
"""

from __future__ import annotations

import pytest

from agents.handlers.tabular.output_extras import build


@pytest.fixture
def fake_minio(monkeypatch):
    """save_chart_to_minio 를 가짜 s3:// 경로 반환으로 대체 (fig 닫음)."""
    import agents.handlers.common.shared as shared

    def _fake(fig, *, kind, job_id):
        import matplotlib.pyplot as plt

        plt.close(fig)
        return f"s3://test-bucket/{kind}/{job_id}.png"

    monkeypatch.setattr(shared, "save_chart_to_minio", _fake)
    return _fake


@pytest.fixture(scope="module")
def binary_preds():
    from sklearn.datasets import load_breast_cancer
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split

    data = load_breast_cancer()
    X, y = data.data, data.target
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.3, random_state=0, stratify=y)
    clf = RandomForestClassifier(n_estimators=30, random_state=0).fit(Xtr, ytr)
    return {
        "y_true": yte.tolist(),
        "y_pred": clf.predict(Xte).tolist(),
        "y_prob": clf.predict_proba(Xte)[:, 1].tolist(),
        "fi": list(clf.feature_importances_),
        "fn": data.feature_names.tolist(),
    }


@pytest.fixture(scope="module")
def multi_preds():
    from sklearn.datasets import load_iris
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split

    data = load_iris()
    X, y = data.data, data.target
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.3, random_state=0, stratify=y)
    clf = RandomForestClassifier(n_estimators=30, random_state=0).fit(Xtr, ytr)
    return {
        "y_true": yte.tolist(),
        "y_pred": clf.predict(Xte).tolist(),
        "y_prob": [list(r) for r in clf.predict_proba(Xte)],
        "fi": list(clf.feature_importances_),
        "fn": list(data.feature_names),
    }


@pytest.fixture(scope="module")
def reg_preds():
    from sklearn.datasets import load_diabetes
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.model_selection import train_test_split

    data = load_diabetes()
    X, y = data.data, data.target
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.3, random_state=0)
    reg = RandomForestRegressor(n_estimators=30, random_state=0).fit(Xtr, ytr)
    return {
        "y_true": yte.tolist(),
        "y_pred": reg.predict(Xte).tolist(),
        "fi": list(reg.feature_importances_),
        "fn": list(data.feature_names),
    }


def _state(preds, task_type, task, with_prob=True, with_fi=True):
    from ada.core.state import PipelineState

    bm = {"model_name": "RF", "task_type": task_type, "metrics": {"val_f1": 0.9, "val_roc_auc": 0.95, "val_r2": 0.5}}
    if with_fi:
        bm["feature_importances"] = preds["fi"]
        bm["feature_names"] = preds["fn"]
    pred_dict = {"y_true": preds["y_true"], "y_pred": preds["y_pred"]}
    if with_prob and "y_prob" in preds:
        pred_dict["y_prob"] = preds["y_prob"]
    return PipelineState(
        job_id="00000000-0000-0000-0000-0000000000d9",
        file_id="uploads/test/out.csv",
        category="tabular_ml",
        target_column="y",
        task=task,
        user_intent="산출물 검증",
        best_model=bm,
        category_extras={"tabular": {"predictions": pred_dict}},
    )


# ── T1 계약 ───────────────────────────────────────────────────────────────────


def test_build_contract_keys(binary_preds, fake_minio):
    from outputs.base import OUTPUT_EXTRAS_KEYS

    result = build(_state(binary_preds, "binary", "classification"), {"output_code": "OUT-04"})
    assert set(result.keys()).issubset(set(OUTPUT_EXTRAS_KEYS))
    assert set(result.keys()) == {"charts", "tables", "text_blocks"}


# ── T2 binary 4 차트 ──────────────────────────────────────────────────────────


def test_binary_four_charts(binary_preds, fake_minio):
    result = build(_state(binary_preds, "binary", "classification"), {"output_code": "OUT-04"})
    assert len(result["charts"]) == 4
    assert all(c.startswith("s3://") for c in result["charts"])
    kinds = {c.split("/")[4] for c in result["charts"]}  # s3://bucket/tabular/<kind>/...
    assert {"roc", "calibration", "cm", "fi"} == kinds
    assert any("주요 지표" in t for t in result["text_blocks"])


# ── T3 multiclass 4 차트 ──────────────────────────────────────────────────────


def test_multiclass_four_charts(multi_preds, fake_minio):
    result = build(_state(multi_preds, "multiclass", "classification"), {"output_code": "OUT-04"})
    assert len(result["charts"]) == 4
    kinds = {c.split("/")[4] for c in result["charts"]}
    assert {"roc_ovr", "pr_ovr", "cm_norm", "fi"} == kinds


# ── T4 regression 4 차트 ──────────────────────────────────────────────────────


def test_regression_four_charts(reg_preds, fake_minio):
    result = build(_state(reg_preds, "regression", "regression", with_prob=False), {"output_code": "OUT-04"})
    assert len(result["charts"]) == 4
    kinds = {c.split("/")[4] for c in result["charts"]}
    assert {"residuals", "pva", "qq", "fi"} == kinds


# ── T5 y_prob 누락 silent skip ────────────────────────────────────────────────


def test_missing_yprob_silent_skip(binary_preds, fake_minio):
    """y_prob 없으면 ROC/Calibration skip → cm + fi 만 (2 차트)."""
    result = build(_state(binary_preds, "binary", "classification", with_prob=False), {"output_code": "OUT-04"})
    kinds = {c.split("/")[4] for c in result["charts"]}
    assert kinds == {"cm", "fi"}
    assert len(result["charts"]) == 2


# ── T6 피처 중요도 테이블 + FI 누락 폴백 ───────────────────────────────────────


def test_feature_importance_table_present(binary_preds, fake_minio):
    result = build(_state(binary_preds, "binary", "classification"), {"output_code": "OUT-04"})
    fi_tables = [t for t in result["tables"] if "피처" in t["title"]]
    assert fi_tables and len(fi_tables[0]["rows"]) <= 10
    assert fi_tables[0]["columns"] == ["피처", "중요도", "기여도"]


def test_no_feature_importance_skips_fi(binary_preds, fake_minio):
    """FI 소스 없으면 fi 차트/테이블 없음 (binary 는 roc/cal/cm 3개만)."""
    result = build(_state(binary_preds, "binary", "classification", with_fi=False), {"output_code": "OUT-04"})
    kinds = {c.split("/")[4] for c in result["charts"]}
    assert "fi" not in kinds
    assert kinds == {"roc", "calibration", "cm"}
    assert not [t for t in result["tables"] if "피처" in t["title"]]


# ── T7 _call_extras 통합 ──────────────────────────────────────────────────────


def test_call_extras_integration(binary_preds, fake_minio):
    """OutputGenerator._call_extras 가 등록된 tabular build 를 호출 → 화이트리스트 통과."""
    from outputs.base import OUTPUT_EXTRAS_KEYS, OutputGenerator

    class _Dummy(OutputGenerator):
        output_code = "OUT-04"
        extension = "html"

        def generate(self, **kwargs):
            return ""

    state = _state(binary_preds, "binary", "classification")
    gen = _Dummy(job_id=state.job_id)
    res = gen._call_extras(state, {"output_code": "OUT-04", "category": "tabular_ml"})
    assert set(res.keys()).issubset(set(OUTPUT_EXTRAS_KEYS))
    assert len(res["charts"]) == 4


# ── 부가: 상태 불변 / assets 위임 ─────────────────────────────────────────────


def test_no_state_mutation(binary_preds, fake_minio):
    state = _state(binary_preds, "binary", "classification")
    before = id(state.category_extras)
    build(state, {"output_code": "OUT-04"})
    assert id(state.category_extras) == before


def test_assets_delegates_to_build(binary_preds, fake_minio):
    from agents.handlers.tabular.output_extras import assets

    state = _state(binary_preds, "binary", "classification")
    a = assets(state, {"output_code": "OUT-04"})
    assert set(a.keys()) == {"charts", "tables", "text_blocks"}
    assert len(a["charts"]) == 4
