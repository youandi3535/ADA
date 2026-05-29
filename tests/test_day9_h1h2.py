"""Day 9 H1+H2 (HJ approved) — 예측값 공급(H2) + carrier extras 배선(H1).

H2: training_executor 가 모은 predictions_by_model 에서 metrics_aggregator 가
    best 모델 예측을 category_extras['tabular']['predictions'] 로 승격.
H1: OUT-04(html_dashboard) 가 _call_extras 로 핸들러 차트/테이블/텍스트를 임베드.

MinIO/boto3 는 fake 모듈 주입으로 우회 (샌드박스 boto3 미가용).
"""

from __future__ import annotations

import asyncio
import sys
import types

import pytest

from ada.core.state import PipelineState

# ── H2: metrics_aggregator 예측 승격 ──────────────────────────────────────────


def test_aggregator_lifts_best_predictions():
    from agents.metrics_aggregator import MetricsAggregatorAgent

    state = PipelineState(
        job_id="00000000-0000-0000-0000-0000000000a1",
        file_id="f.csv",
        category="tabular_ml",
        target_column="y",
        trained_models=[
            {"model_name": "RF", "metrics": {"val_f1": 0.91}, "feature_importances": [0.6, 0.4],
             "feature_names": ["a", "b"], "task_type": "binary"},
            {"model_name": "XGB", "metrics": {"val_f1": 0.80}},
        ],
        category_extras={"tabular": {"predictions_by_model": {
            "RF": {"y_true": [0, 1, 1], "y_pred": [0, 1, 0], "y_prob": [0.1, 0.9, 0.4]},
            "XGB": {"y_true": [0, 1, 1], "y_pred": [0, 0, 1], "y_prob": [0.2, 0.3, 0.8]},
        }}},
    )
    out = asyncio.run(MetricsAggregatorAgent()(state))
    assert out.best_model["model_name"] == "RF"
    assert out.best_model["feature_importances"] == [0.6, 0.4]
    assert out.category_extras["tabular"]["predictions"]["y_prob"] == [0.1, 0.9, 0.4]
    assert out.next_agent == "gate_best_model"


def test_aggregator_without_predictions_is_safe():
    from agents.metrics_aggregator import MetricsAggregatorAgent

    state = PipelineState(
        job_id="00000000-0000-0000-0000-0000000000a2",
        file_id="f.csv",
        category="tabular_ml",
        target_column="y",
        trained_models=[{"model_name": "RF", "metrics": {"val_f1": 0.7}}],
    )
    out = asyncio.run(MetricsAggregatorAgent()(state))
    assert out.best_model["model_name"] == "RF"
    assert "predictions" not in (out.category_extras.get("tabular", {}) or {})


# ── H1: html_dashboard extras 임베드 ──────────────────────────────────────────


@pytest.fixture
def fake_minio_and_charts(monkeypatch):
    """boto3 우회 fake minio + save_chart_to_minio 가짜 s3 경로."""
    fake_mod = types.ModuleType("tools.minio_tool")

    class _FakeMC:
        bucket = "test-bucket"

        def download_bytes(self, key):
            return b"\x89PNG\r\n\x1a\nFAKE"

        def save_artifact(self, local, prefix, job_id):
            return f"s3://test-bucket/{prefix}/{job_id}"

    fake_mod.get_minio_client = lambda: _FakeMC()
    monkeypatch.setitem(sys.modules, "tools.minio_tool", fake_mod)

    import agents.handlers.common.shared as shared
    import agents.handlers.tabular  # noqa: F401  (build 핸들러 등록)

    monkeypatch.setattr(
        shared,
        "save_chart_to_minio",
        lambda fig, *, kind, job_id: (__import__("matplotlib.pyplot", fromlist=["close"]).close(fig)
                                      or f"s3://test-bucket/{kind}/{job_id}.png"),
    )
    return _FakeMC()


def _binary_state():
    from sklearn.datasets import load_breast_cancer
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split

    data = load_breast_cancer()
    Xtr, Xte, ytr, yte = train_test_split(data.data, data.target, test_size=0.3, random_state=0, stratify=data.target)
    clf = RandomForestClassifier(n_estimators=20, random_state=0).fit(Xtr, ytr)
    return PipelineState(
        job_id="00000000-0000-0000-0000-0000000000a3",
        file_id="f.csv",
        category="tabular_ml",
        target_column="y",
        task="classification",
        best_model={"model_name": "RF", "task_type": "binary",
                    "metrics": {"val_f1": 0.95, "val_roc_auc": 0.99},
                    "feature_importances": list(clf.feature_importances_),
                    "feature_names": data.feature_names.tolist()},
        category_extras={"tabular": {"predictions": {
            "y_true": yte.tolist(), "y_pred": clf.predict(Xte).tolist(),
            "y_prob": clf.predict_proba(Xte)[:, 1].tolist()}}},
    )


def _render_html(state):
    from outputs.html_dashboard import DashboardArtifactGenerator

    gen = DashboardArtifactGenerator(job_id=state.job_id)
    captured = {}
    gen._upload = lambda local: (captured.__setitem__("html", open(local, encoding="utf-8").read()) or "s3://x")
    gen.generate(
        insights="테스트 인사이트", best_model=state.best_model, eda_charts=[],
        category="tabular_ml", user_intent="생존 예측",
        eval_result={"passed": True, "rationale": "ok"}, state=state,
    )
    return captured["html"]


def test_html_dashboard_embeds_extras(fake_minio_and_charts):
    html = _render_html(_binary_state())
    assert "모델 분석 차트" in html
    after = html.split("모델 분석 차트", 1)[1]
    assert after.count("<img") == 4  # ROC/Calibration/Confusion/FI
    assert "Top-10 피처 중요도" in html
    assert "주요 지표" in html


def test_html_dashboard_no_state_safe(fake_minio_and_charts):
    """state=None 이면 _call_extras={} → 빈 안내 문구, 크래시 없음."""
    from outputs.html_dashboard import DashboardArtifactGenerator

    gen = DashboardArtifactGenerator(job_id="00000000-0000-0000-0000-0000000000a4")
    captured = {}
    gen._upload = lambda local: (captured.__setitem__("html", open(local, encoding="utf-8").read()) or "s3://x")
    gen.generate(insights="x", best_model={"model_name": "RF", "metrics": {}}, eda_charts=[],
                 category="tabular_ml", user_intent="t", eval_result=None, state=None)
    assert "모델 분석 차트" in captured["html"]
    assert "표시할 분석 차트가 없습니다" in captured["html"]
