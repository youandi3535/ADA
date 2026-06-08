"""tests.handlers.tabular.test_selector — Day 11 (jh) baseline 도입 검증.

검증 범위:
  - selector.score() 가 baselines 키 반환
  - 분류/회귀별 baseline 모델 차별화
  - tabular_dl 은 baseline 비활성
  - pipeline._build_model 이 Dummy/LogisticRegression/Ridge 학습 가능
  - SUPPORTED_MODELS 에 baseline 포함
  - evaluator.improvement_over_baseline 계산 정확성
  - insight.fallback 이 baseline 격차 문장 포함
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# selector.score() — baselines 키
# ---------------------------------------------------------------------------


class TestSelectorBaselines:
    def _state(self, category="tabular_ml", task="classification", **profile_kwargs):
        from ada.core.state import PipelineState

        profile = {
            "rows": 200,
            "class_distribution": {"0": 0.7, "1": 0.3},
            "class_imbalance_ratio": 2.3,
            **profile_kwargs,
        }
        return PipelineState(
            job_id="test-sel",
            file_id="memory",
            category=category,
            target_column="y",
            task=task,
            data_profile=profile,
        )

    def test_score_returns_baselines_key(self):
        from agents.handlers.tabular.selector import score

        result = score(self._state(), recipes=[])
        assert "baselines" in result, "score() 결과에 baselines 키 누락"

    def test_classification_baselines_are_dummy_and_lr(self):
        from agents.handlers.tabular.selector import score

        result = score(self._state(task="classification"), recipes=[])
        assert result["baselines"] == ["Dummy", "LogisticRegression"]

    def test_regression_baselines_are_dummy_and_ridge(self):
        from agents.handlers.tabular.selector import score

        state = self._state(task="regression")
        # 회귀 신호: class_distribution 비우기
        state = state.with_update(data_profile={**state.data_profile, "class_distribution": {}})
        result = score(state, recipes=[])
        assert result["baselines"] == ["Dummy", "Ridge"]

    def test_tabular_dl_has_no_baselines(self):
        from agents.handlers.tabular.selector import score

        result = score(self._state(category="tabular_dl"), recipes=[])
        assert result["baselines"] == [], "tabular_dl 은 baseline 비활성"

    def test_top3_unchanged_when_baselines_added(self):
        """top3 길이는 기존대로 3 유지 — G4 UI 호환."""
        from agents.handlers.tabular.selector import score

        result = score(self._state(), recipes=[])
        assert len(result["top3"]) == 3
        # baselines 와 top3 는 서로 다른 키 (UI 노출 분리)
        assert not set(result["baselines"]) & set(result["top3"])


# ---------------------------------------------------------------------------
# pipeline._build_model — baseline 학습 가능
# ---------------------------------------------------------------------------


class TestPipelineBuildBaselines:
    @pytest.fixture
    def clf_data(self):
        rng = np.random.RandomState(42)
        X = rng.normal(size=(100, 4))
        y = (X[:, 0] + X[:, 1] > 0).astype(int)
        return X, y

    @pytest.fixture
    def reg_data(self):
        rng = np.random.RandomState(42)
        X = rng.normal(size=(100, 4))
        y = X[:, 0] * 2 + X[:, 1] + rng.normal(0, 0.1, size=100)
        return X, y

    def test_build_dummy_classifier(self, clf_data):
        from pipelines.tabular_ml.pipeline import _build_model

        X, y = clf_data
        m = _build_model("Dummy", "classification", {})
        m.fit(X, y)
        pred = m.predict(X)
        assert pred.shape[0] == len(y)

    def test_build_dummy_regressor(self, reg_data):
        from pipelines.tabular_ml.pipeline import _build_model

        X, y = reg_data
        m = _build_model("Dummy", "regression", {})
        m.fit(X, y)
        pred = m.predict(X)
        # DummyRegressor(strategy="mean") → 모든 예측이 y.mean()
        assert np.allclose(pred, y.mean())

    def test_build_logistic_regression(self, clf_data):
        from pipelines.tabular_ml.pipeline import _build_model

        X, y = clf_data
        m = _build_model("LogisticRegression", "classification", {})
        m.fit(X, y)
        # LR 은 데이터 신호 학습 → Dummy 보다 잘 맞아야 함
        from sklearn.metrics import accuracy_score

        assert accuracy_score(y, m.predict(X)) > 0.7

    def test_build_ridge(self, reg_data):
        from pipelines.tabular_ml.pipeline import _build_model

        X, y = reg_data
        m = _build_model("Ridge", "regression", {})
        m.fit(X, y)
        from sklearn.metrics import r2_score

        # Ridge 은 진짜 선형 신호 → R² 가 높아야 함
        assert r2_score(y, m.predict(X)) > 0.8

    def test_supported_models_includes_baselines(self):
        from pipelines.tabular_ml.pipeline import TabularMLPipeline

        sm = TabularMLPipeline.SUPPORTED_MODELS
        for name in ("Dummy", "LogisticRegression", "Ridge"):
            assert name in sm, f"{name} 가 SUPPORTED_MODELS 에 누락"

    def test_is_baseline_model_helper(self):
        from pipelines.tabular_ml.pipeline import is_baseline_model

        assert is_baseline_model("Dummy")
        assert is_baseline_model("LogisticRegression")
        assert is_baseline_model("Ridge")
        assert not is_baseline_model("XGBoost")
        assert not is_baseline_model("RandomForest")


# ---------------------------------------------------------------------------
# search_space — baseline 은 HPO 빈 dict
# ---------------------------------------------------------------------------


class TestSearchSpaceBaselines:
    def test_baseline_returns_empty_dict(self):
        from pipelines.tabular_ml.search_space import get_search_space

        # trial 은 None 으로 호출 가능해야 함 — baseline 분기가 먼저 catch
        for name in ("Dummy", "LogisticRegression", "Ridge"):
            assert get_search_space(name, trial=None) == {}, f"{name} 은 HPO 불필요"

    def test_non_baseline_still_works(self):
        """기존 모델은 trial 사용 — 회귀 방지."""

        class _FakeTrial:
            def suggest_int(self, name, lo, hi):
                return lo

            def suggest_float(self, name, lo, hi, log=False):
                return lo

            def suggest_categorical(self, name, choices):
                return choices[0]

        from pipelines.tabular_ml.search_space import get_search_space

        space = get_search_space("RandomForest", trial=_FakeTrial())
        assert "n_estimators" in space


# ---------------------------------------------------------------------------
# evaluator.improvement_over_baseline
# ---------------------------------------------------------------------------


class TestEvaluatorImprovementOverBaseline:
    def _state_with_models(
        self,
        *,
        category="tabular_ml",
        best_metrics: dict,
        baseline_name: str,
        baseline_metrics: dict,
    ):
        from ada.core.state import PipelineState

        return PipelineState(
            job_id="test-eval",
            file_id="memory",
            category=category,
            target_column="y",
            data_profile={"rows": 200},
            best_model={"model_name": "XGBoost", "metrics": best_metrics},
            trained_models=[
                {"model_name": baseline_name, "metrics": baseline_metrics},
                {"model_name": "XGBoost", "metrics": best_metrics},
            ],
            category_extras={"tabular": {"baseline_model_names": [baseline_name]}},
        )

    def test_lift_computed_for_classification(self):
        from agents.handlers.tabular.evaluator import evaluate

        state = self._state_with_models(
            best_metrics={"val_f1": 0.83, "val_accuracy": 0.85},
            baseline_name="Dummy",
            baseline_metrics={"val_f1": 0.51, "val_accuracy": 0.53},
        )
        result = evaluate(state)
        imp = result["improvement_over_baseline"]
        assert imp["primary_metric"] == "val_f1"
        assert imp["primary_lift"] == pytest.approx(0.32, abs=0.01)
        assert imp["lift_by_metric"]["val_f1"] == pytest.approx(0.32, abs=0.01)
        assert imp["lift_by_metric"]["val_accuracy"] == pytest.approx(0.32, abs=0.01)

    def test_lift_computed_for_regression(self):
        from agents.handlers.tabular.evaluator import evaluate

        state = self._state_with_models(
            best_metrics={"val_r2": 0.55, "val_rmse": 0.4},
            baseline_name="Dummy",
            baseline_metrics={"val_r2": 0.00, "val_rmse": 1.0},
        )
        result = evaluate(state)
        imp = result["improvement_over_baseline"]
        assert imp["primary_metric"] == "val_r2"
        assert imp["primary_lift"] == pytest.approx(0.55, abs=0.01)

    def test_no_baseline_recorded_returns_empty_improvement(self):
        """baseline_model_names 가 없으면 improvement_over_baseline 빈 dict."""
        from ada.core.state import PipelineState

        from agents.handlers.tabular.evaluator import evaluate

        state = PipelineState(
            job_id="t",
            file_id="m",
            category="tabular_ml",
            best_model={"model_name": "XGBoost", "metrics": {"val_f1": 0.83}},
            trained_models=[{"model_name": "XGBoost", "metrics": {"val_f1": 0.83}}],
        )
        result = evaluate(state)
        assert result["improvement_over_baseline"] == {}
        assert result["baseline_used"] == {}

    def test_picks_strongest_baseline_when_multiple(self):
        """Dummy 와 LR 둘 다 있으면 더 강한 LR 을 baseline 으로 선택 (보수적)."""
        from ada.core.state import PipelineState

        from agents.handlers.tabular.evaluator import evaluate

        state = PipelineState(
            job_id="t",
            file_id="m",
            category="tabular_ml",
            best_model={"model_name": "XGBoost", "metrics": {"val_f1": 0.83}},
            trained_models=[
                {"model_name": "Dummy", "metrics": {"val_f1": 0.51}},
                {"model_name": "LogisticRegression", "metrics": {"val_f1": 0.75}},
                {"model_name": "XGBoost", "metrics": {"val_f1": 0.83}},
            ],
            category_extras={
                "tabular": {"baseline_model_names": ["Dummy", "LogisticRegression"]}
            },
        )
        result = evaluate(state)
        assert result["baseline_used"]["name"] == "LogisticRegression"
        # 격차: XGB 0.83 - LR 0.75 = 0.08 (Dummy 0.51 대비 0.32 보다 보수적)
        assert result["improvement_over_baseline"]["primary_lift"] == pytest.approx(0.08, abs=0.01)


# ---------------------------------------------------------------------------
# insight.fallback — baseline 격차 문장 포함
# ---------------------------------------------------------------------------


class TestInsightBaselineCitation:
    def test_fallback_includes_baseline_lift_sentence(self):
        from ada.core.state import PipelineState

        from agents.handlers.tabular.insight import fallback

        state = PipelineState(
            job_id="t",
            file_id="m",
            category="tabular_ml",
            best_model={"model_name": "XGBoost", "metrics": {"val_f1": 0.83}},
            eval_result={
                "improvement_over_baseline": {
                    "primary_metric": "val_f1",
                    "primary_lift": 0.32,
                },
                "baseline_used": {"name": "Dummy", "metrics": {"val_f1": 0.51}},
            },
        )
        text = fallback(state)
        # "기본값" 또는 "Dummy" 문구 포함, +0.32 숫자 포함
        assert "기본값" in text or "Dummy" in text
        assert "0.32" in text

    def test_fallback_works_without_baseline(self):
        """baseline 정보 없어도 fallback 정상 동작 (회귀 방지)."""
        from ada.core.state import PipelineState

        from agents.handlers.tabular.insight import fallback

        state = PipelineState(
            job_id="t",
            file_id="m",
            category="tabular_ml",
            best_model={"model_name": "XGBoost", "metrics": {"val_f1": 0.83}},
        )
        text = fallback(state)
        # 베이스라인 문장이 없어도 기본 인사이트는 생성
        assert "XGBoost" in text
        assert len(text) > 50
