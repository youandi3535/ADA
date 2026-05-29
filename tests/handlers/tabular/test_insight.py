"""jh Day 8 — test_insight.py: 정형 인사이트 (top3 피처 기여도 + 비즈니스 권고).

DoD: "X 피처가 결과의 32% 설명" 형식. fallback 은 HJ Day8 가드(insight_must_cite) 통과.
"""

from __future__ import annotations

import re

import pytest

from agents.handlers.tabular.insight import fallback, prompt_payload, top_features


def _state(best_model=None, explanations=None, eval_result=None, **kw):
    from ada.core.state import PipelineState

    return PipelineState(
        job_id="00000000-0000-0000-0000-0000000000f8",
        file_id="uploads/test/insight.csv",
        category="tabular_ml",
        target_column="Survived",
        user_intent="고객 생존 예측 및 해석",
        best_model=best_model,
        explanations=explanations,
        eval_result=eval_result,
        **kw,
    )


_FULL_MODEL = {
    "model_name": "XGBoost",
    "metrics": {"val_f1": 0.82, "val_roc_auc": 0.90, "val_accuracy": 0.85},
    "feature_importances": [0.5, 0.3, 0.15, 0.05],
    "feature_names": ["Fare", "Sex", "Pclass", "Age"],
}


# ── TestTopFeatures ───────────────────────────────────────────────────────────


class TestTopFeatures:
    def test_from_best_model_importances(self):
        feats = top_features(_state(best_model=_FULL_MODEL))
        assert [f["name"] for f in feats] == ["Fare", "Sex", "Pclass"]
        assert feats[0]["contribution_pct"] == 50.0
        assert feats[1]["contribution_pct"] == 30.0

    def test_contribution_pct_descending(self):
        feats = top_features(_state(best_model=_FULL_MODEL))
        pcts = [f["contribution_pct"] for f in feats]
        assert pcts == sorted(pcts, reverse=True)

    def test_from_explanations_shap_dict(self):
        state = _state(
            best_model={"model_name": "RF", "metrics": {}},
            explanations={"shap_top_features": {"Age": 0.4, "Fare": 0.6}},
        )
        feats = top_features(state)
        assert feats[0]["name"] == "Fare"
        assert feats[0]["contribution_pct"] == 60.0

    def test_from_explanations_shap_pairs(self):
        state = _state(
            best_model={"model_name": "RF", "metrics": {}},
            explanations={"shap_top_features": [["Sex", 0.7], ["Age", 0.3]]},
        )
        feats = top_features(state)
        assert feats[0]["name"] == "Sex"
        assert feats[0]["contribution_pct"] == 70.0

    def test_from_eval_result(self):
        state = _state(
            best_model={"model_name": "RF", "metrics": {}},
            eval_result={"feature_importance": {"A": 1.0, "B": 3.0}},
        )
        feats = top_features(state)
        assert feats[0]["name"] == "B"
        assert feats[0]["contribution_pct"] == 75.0

    def test_empty_when_no_source(self):
        assert top_features(_state(best_model={"model_name": "RF", "metrics": {}})) == []

    def test_k_limit(self):
        assert len(top_features(_state(best_model=_FULL_MODEL), k=2)) == 2


# ── TestFallbackFormat (DoD) ──────────────────────────────────────────────────


class TestFallbackFormat:
    def test_dod_contribution_percent_format(self):
        """DoD: 'X 피처가 결과의 NN% 설명' 형식 포함."""
        text = fallback(_state(best_model=_FULL_MODEL))
        assert re.search(r"결과의 \d+%를 설명", text)
        assert "Fare" in text  # top1 피처명

    def test_business_recommendation_present(self):
        text = fallback(_state(best_model=_FULL_MODEL))
        assert "권장" in text

    def test_metric_number_cited(self):
        text = fallback(_state(best_model=_FULL_MODEL))
        assert re.search(r"\d+\.\d+", text)  # 0.82 등

    def test_graceful_without_features(self):
        text = fallback(_state(best_model={"model_name": "RF", "metrics": {"val_f1": 0.7}}))
        assert "권장" in text
        assert len(text) > 0


# ── TestGuardCompatibility (HJ Day8 insight_must_cite 통과) ────────────────────


class TestGuardCompatibility:
    def test_fallback_passes_hj_guard(self):
        from ada.security.guardrails import insight_must_cite

        state = _state(best_model=_FULL_MODEL)
        text = fallback(state)
        feats = [f["name"] for f in top_features(state)]
        metric_names = list(_FULL_MODEL["metrics"].keys())
        verdict = insight_must_cite(text, metric_names=metric_names, top_features=feats)
        assert verdict["passed"], verdict["violations"]
        assert 3 <= verdict["n_sentences"] <= 5


# ── TestPromptPayload ─────────────────────────────────────────────────────────


class TestPromptPayload:
    def test_payload_includes_top_features(self):
        payload = prompt_payload(_state(best_model=_FULL_MODEL))
        assert "top_features" in payload and "top_feature_names" in payload
        assert payload["top_feature_names"][0] == "Fare"
        assert payload["category"] == "tabular_ml"

    def test_no_state_mutation(self):
        state = _state(best_model=_FULL_MODEL)
        before = id(state.best_model)
        fallback(state)
        prompt_payload(state)
        assert id(state.best_model) == before
