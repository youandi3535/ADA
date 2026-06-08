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


# ---------------------------------------------------------------------------
# Day 11 (jh) — CV stats + 통계적 유의성
# ---------------------------------------------------------------------------


class TestCvStats:
    """pipeline.evaluate_with_cv + evaluator 가 cv_stats 를 노출하는지 검증.

    실데이터 로딩 없는 단위 테스트만. 운영 경로(evaluator.evaluate 의
    _compute_cv_stats)는 load_dataframe_from_state 가 MinIO 의존이라
    별도 통합 테스트로 (E2E 에서 자연스럽게 검증됨).
    """

    @pytest.fixture
    def clf_data(self):
        rng = np.random.RandomState(42)
        X = rng.normal(size=(200, 4))
        y = (X[:, 0] + X[:, 1] > 0).astype(int)
        return X, y

    @pytest.fixture
    def reg_data(self):
        rng = np.random.RandomState(42)
        X = rng.normal(size=(200, 4))
        y = X[:, 0] * 2 + X[:, 1] + rng.normal(0, 0.1, size=200)
        return X, y

    def test_evaluate_with_cv_returns_fold_stats(self, clf_data):
        from pipelines.tabular_ml.pipeline import TabularMLPipeline

        X, y = clf_data
        pipe = TabularMLPipeline()
        result = pipe.evaluate_with_cv(
            X, y, model_name="RandomForest", params={"n_estimators": 30, "random_state": 42},
            n_splits=3, task="classification",
        )
        assert result["n_splits"] == 3
        assert len(result["fold_metrics"]) == 3
        assert result["primary_metric"] == "val_f1"
        assert "val_f1" in result["mean"]
        assert "val_f1" in result["std"]
        assert result["primary_std"] >= 0  # std 는 음수 불가

    def test_evaluate_with_cv_regression_uses_r2(self, reg_data):
        from pipelines.tabular_ml.pipeline import TabularMLPipeline

        X, y = reg_data
        pipe = TabularMLPipeline()
        result = pipe.evaluate_with_cv(
            X, y, model_name="Ridge", params={}, n_splits=3, task="regression",
        )
        assert result["primary_metric"] == "val_r2"
        # Ridge 가 진짜 선형 신호 학습 → R² > 0 평균
        assert result["primary_mean"] > 0.5

    def test_evaluate_with_cv_dummy_has_low_score(self, clf_data):
        """Dummy 의 fold 평균이 강모델보다 명확히 낮아야 baseline 의미 살아남."""
        from pipelines.tabular_ml.pipeline import TabularMLPipeline

        X, y = clf_data
        pipe = TabularMLPipeline()
        dummy = pipe.evaluate_with_cv(
            X, y, model_name="Dummy", params={}, n_splits=3, task="classification",
        )
        rf = pipe.evaluate_with_cv(
            X, y, model_name="RandomForest",
            params={"n_estimators": 30, "random_state": 42},
            n_splits=3, task="classification",
        )
        # RF 가 Dummy 보다 분명히 높아야 함 — 그렇지 않으면 baseline 비교 의미 없음
        assert rf["primary_mean"] > dummy["primary_mean"] + 0.1

    def test_evaluate_with_cv_returns_empty_on_failure(self):
        """이상한 입력엔 빈 dict 반환 (graceful)."""
        from pipelines.tabular_ml.pipeline import TabularMLPipeline

        pipe = TabularMLPipeline()
        # n=0 X, y → 실패
        import numpy as _np

        result = pipe.evaluate_with_cv(
            _np.array([]).reshape(0, 4),
            _np.array([]),
            model_name="RandomForest",
            params={},
            n_splits=3,
            task="classification",
        )
        assert result == {}

    def test_evaluator_significance_with_baseline_std(self):
        """baseline_cv_std 가 작으면 +0.1 lift 는 significant=True."""
        from agents.handlers.tabular.evaluator import _add_significance

        # baseline std = 0.02, lift = +0.1 → 5σ → significant
        imp = {"primary_metric": "val_f1", "primary_lift": 0.10}
        out = _add_significance(imp, baseline_cv_std=0.02)
        assert out["lift_significant"] is True
        assert out["baseline_cv_std"] == 0.02

    def test_evaluator_significance_with_large_baseline_std(self):
        """baseline_cv_std 가 크면 +0.05 lift 는 노이즈 → significant=False."""
        from agents.handlers.tabular.evaluator import _add_significance

        imp = {"primary_metric": "val_f1", "primary_lift": 0.05}
        out = _add_significance(imp, baseline_cv_std=0.10)
        # 0.05 < 2 * 0.10 = 0.2 → significant False
        assert out["lift_significant"] is False

    def test_evaluator_significance_unknown_when_no_baseline_std(self):
        """baseline_cv_std 없으면 lift_significant=None (판단 불가)."""
        from agents.handlers.tabular.evaluator import _add_significance

        imp = {"primary_metric": "val_f1", "primary_lift": 0.05}
        out = _add_significance(imp, baseline_cv_std=None)
        assert out["lift_significant"] is None

    def test_evaluator_should_run_cv_guards(self):
        """CV 가드 — 대용량/DL/non-tabular/단발테스트 는 skip."""
        from ada.core.state import PipelineState
        from agents.handlers.tabular.evaluator import _should_run_cv

        # 대용량 → skip
        state_big = PipelineState(
            job_id="t", file_id="m", category="tabular_ml",
            data_profile={"rows": 100000},
            trained_models=[{"model_name": "RandomForest", "metrics": {"val_f1": 0.8}}],
        )
        assert _should_run_cv(state_big) is False

        # DL → skip
        state_dl = PipelineState(
            job_id="t", file_id="m", category="tabular_dl",
            data_profile={"rows": 1000},
            trained_models=[{"model_name": "FTTransformer", "metrics": {"val_f1": 0.8}}],
        )
        assert _should_run_cv(state_dl) is False

        # trained_models 비어있음 (단발 테스트 시나리오) → skip
        state_no_trained = PipelineState(
            job_id="t", file_id="m", category="tabular_ml",
            data_profile={"rows": 500},
        )
        assert _should_run_cv(state_no_trained) is False

        # 작은 tabular_ml + trained_models 있음 (운영) → run
        state_ok = PipelineState(
            job_id="t", file_id="m", category="tabular_ml",
            data_profile={"rows": 500},
            trained_models=[{"model_name": "RandomForest", "metrics": {"val_f1": 0.8}}],
        )
        assert _should_run_cv(state_ok) is True

    def test_insight_fallback_includes_cv_band(self):
        """fallback 이 'F1 0.83 ± 0.04' 형식으로 신뢰구간 인용하는지."""
        from ada.core.state import PipelineState
        from agents.handlers.tabular.insight import fallback

        state = PipelineState(
            job_id="t",
            file_id="m",
            category="tabular_ml",
            best_model={"model_name": "XGBoost", "metrics": {"val_f1": 0.83}},
            eval_result={
                "cv_stats": {
                    "primary_metric": "val_f1",
                    "primary_mean": 0.83,
                    "primary_std": 0.04,
                },
            },
        )
        text = fallback(state)
        assert "0.83" in text and "0.04" in text
        assert "±" in text or "5-fold" in text

    def test_insight_fallback_marks_significant_lift(self):
        """significant=True 면 '통계적으로 유의' 문구 포함."""
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
                    "lift_significant": True,
                },
                "baseline_used": {"name": "Dummy"},
            },
        )
        text = fallback(state)
        assert "통계적으로 유의" in text

    def test_insight_fallback_marks_noise_lift(self):
        """significant=False 면 '노이즈 범위 내' 문구."""
        from ada.core.state import PipelineState
        from agents.handlers.tabular.insight import fallback

        state = PipelineState(
            job_id="t",
            file_id="m",
            category="tabular_ml",
            best_model={"model_name": "XGBoost", "metrics": {"val_f1": 0.51}},
            eval_result={
                "improvement_over_baseline": {
                    "primary_metric": "val_f1",
                    "primary_lift": 0.01,
                    "lift_significant": False,
                },
                "baseline_used": {"name": "Dummy"},
            },
        )
        text = fallback(state)
        assert "노이즈" in text


# ---------------------------------------------------------------------------
# Day 11 (jh) — Learning Curve (overfit/underfit 진단)
# ---------------------------------------------------------------------------


class TestLearningCurve:
    """output_extras._build_learning_curve_chart 검증.

    실제 MinIO/모델 재로드는 운영 환경 필수. 단위 테스트는 가드 로직과
    skip 조건만 검증 — 차트 자체는 helper 가 None 반환하는지로 간접 확인.
    """

    def _state(self, *, category="tabular_ml", n_rows=200, model_name="RandomForest"):
        from ada.core.state import PipelineState

        return PipelineState(
            job_id="t",
            file_id="m",
            category=category,
            target_column="y",
            data_profile={"rows": n_rows, "class_distribution": {"0": 0.5, "1": 0.5}},
            best_model={"model_name": model_name, "metrics": {"val_f1": 0.83}},
        )

    def test_skips_when_baseline_model(self):
        """baseline 모델이면 learning_curve 의미 없음 → skip."""
        from agents.handlers.tabular.output_extras import _build_learning_curve_chart

        for name in ("Dummy", "LogisticRegression", "Ridge"):
            state = self._state(model_name=name)
            assert _build_learning_curve_chart(state) is None, f"{name} 은 skip 해야 함"

    def test_skips_when_dl_category(self):
        """tabular_dl 카테고리 → skip (DL 비용)."""
        from agents.handlers.tabular.output_extras import _build_learning_curve_chart

        state = self._state(category="tabular_dl", model_name="FTTransformer")
        assert _build_learning_curve_chart(state) is None

    def test_skips_when_large_data(self):
        """n_rows > 5000 → skip (비용 폭주)."""
        from agents.handlers.tabular.output_extras import _build_learning_curve_chart

        state = self._state(n_rows=100000)
        assert _build_learning_curve_chart(state) is None

    def test_skips_when_no_best_model(self):
        """best_model 없으면 skip."""
        from ada.core.state import PipelineState
        from agents.handlers.tabular.output_extras import _build_learning_curve_chart

        state = PipelineState(
            job_id="t", file_id="m", category="tabular_ml", target_column="y",
            data_profile={"rows": 200},
        )
        assert _build_learning_curve_chart(state) is None

    def test_skips_gracefully_when_model_reload_fails(self):
        """MinIO 없는 환경에서 모델 재로드 실패 → None 반환 (예외 없음)."""
        from agents.handlers.tabular.output_extras import _build_learning_curve_chart

        # 실 데이터 없는 단위 테스트 환경 → _try_reload_model_and_data 가 실패 → None
        state = self._state(model_name="RandomForest")
        result = _build_learning_curve_chart(state)
        # 예외 없이 None 반환만 보장 (운영 환경에선 차트 생성됨)
        assert result is None

    def test_assets_includes_learning_curve_in_returned_keys(self):
        """assets() 가 charts 리스트에 learning_curve 추가 시도 (graceful skip 포함)."""
        from agents.handlers.tabular.output_extras import assets

        state = self._state()
        result = assets(state)
        # charts 키 존재 + 리스트 타입 (재로드 실패해도 다른 차트 시도)
        assert "charts" in result
        assert isinstance(result["charts"], list)


# ---------------------------------------------------------------------------
# Day 11 (jh) — selector 점수 매트릭스 (신호 기반 top3 자동 선정)
# ---------------------------------------------------------------------------


class TestSelectorScoreMatrix:
    """단순 if-else 룰 → 신호 기반 점수 매트릭스 전환 검증.

    신호 4개: n_rows, numeric_ratio, high_card_count, imbalance_ratio.
    각 시나리오에서 top1 모델이 데이터 특성에 맞는지 검증.
    """

    def _state(self, *, n_rows=1000, imbalance=2.0, dtypes=None, cardinality_levels=None):
        from ada.core.state import PipelineState

        profile = {
            "rows": n_rows,
            "class_distribution": {"0": 0.6, "1": 0.4},
            "class_imbalance_ratio": imbalance,
        }
        if dtypes is not None:
            profile["dtypes"] = dtypes
        if cardinality_levels is not None:
            profile["cardinality_levels"] = cardinality_levels
        return PipelineState(
            job_id="t",
            file_id="m",
            category="tabular_ml",
            target_column="y",
            task="classification",
            data_profile=profile,
        )

    def test_signals_extracted_correctly(self):
        from agents.handlers.tabular.selector import _extract_signals

        state = self._state(
            n_rows=10000,
            imbalance=15.0,
            dtypes={"a": "int64", "b": "float64", "c": "object"},
            cardinality_levels={"a": "low", "c": "high"},
        )
        signals = _extract_signals(state)
        assert signals["n_rows"] == 10000
        assert signals["imbalance_ratio"] == 15.0
        assert signals["numeric_ratio"] == pytest.approx(2 / 3, abs=0.01)
        assert signals["high_card_count"] == 1

    def test_small_data_prefers_random_forest(self):
        """소량 데이터(n_rows<500) → RandomForest 가 top1."""
        from agents.handlers.tabular.selector import score

        state = self._state(n_rows=200, imbalance=2.0)
        result = score(state, recipes=[])
        assert result["top3"][0] == "RandomForest"

    def test_large_balanced_prefers_xgboost(self):
        """대용량 균형 + numeric 위주 → XGBoost 가 top1."""
        from agents.handlers.tabular.selector import score

        state = self._state(
            n_rows=10000,
            imbalance=2.0,
            dtypes={"a": "int64", "b": "float64", "c": "float64"},  # 100% numeric
        )
        result = score(state, recipes=[])
        assert result["top3"][0] == "XGBoost"

    def test_imbalanced_prefers_lightgbm(self):
        """불균형(imb≥10) → LightGBM 가 top1 (class_weight 가산)."""
        from agents.handlers.tabular.selector import score

        state = self._state(n_rows=10000, imbalance=15.0)
        result = score(state, recipes=[])
        assert result["top3"][0] == "LightGBM"

    def test_high_cardinality_prefers_catboost(self):
        """고카디(hc≥2) → CatBoost 가 top1 (native categorical)."""
        from agents.handlers.tabular.selector import score

        state = self._state(
            n_rows=2000,
            imbalance=2.0,
            cardinality_levels={"a": "high", "b": "high", "c": "low"},
        )
        result = score(state, recipes=[])
        assert result["top3"][0] == "CatBoost"

    def test_top3_length_always_three(self):
        """어떤 시나리오에서도 top3 길이는 정확히 3."""
        from agents.handlers.tabular.selector import score

        scenarios = [
            self._state(n_rows=100),
            self._state(n_rows=10000, imbalance=2.0),
            self._state(n_rows=10000, imbalance=20.0),
            self._state(cardinality_levels={"a": "high", "b": "high"}),
        ]
        for state in scenarios:
            result = score(state, recipes=[])
            assert len(result["top3"]) == 3, f"top3 길이 {len(result['top3'])} != 3"
            # top3 모델은 모두 ML 4종 중에
            assert set(result["top3"]).issubset({"RandomForest", "XGBoost", "LightGBM", "CatBoost"})

    def test_model_scores_exposed_for_debugging(self):
        """model_scores 딕셔너리가 결과에 포함 (디버깅·관찰용)."""
        from agents.handlers.tabular.selector import score

        state = self._state()
        result = score(state, recipes=[])
        assert "model_scores" in result
        ms = result["model_scores"]
        assert set(ms.keys()) == {"RandomForest", "XGBoost", "LightGBM", "CatBoost"}
        # 모든 점수가 0~1 사이
        for name, sc in ms.items():
            assert 0 <= sc <= 1.0, f"{name} 점수 {sc} 가 [0,1] 밖"

    def test_dl_category_unchanged(self):
        """tabular_dl 카테고리는 기존대로 트랜스포머 3종 (점수 매트릭스 무관)."""
        from agents.handlers.tabular.selector import score

        state = self._state()
        state = state.with_update(category="tabular_dl")
        result = score(state, recipes=[])
        assert result["top3"] == ["FTTransformer", "TabTransformer", "TabPFN"]

    def test_deterministic_with_same_signals(self):
        """같은 signals → 같은 top3 (결정적)."""
        from agents.handlers.tabular.selector import score

        state = self._state(n_rows=2000, imbalance=3.0)
        r1 = score(state, recipes=[])
        r2 = score(state, recipes=[])
        assert r1["top3"] == r2["top3"]

    def test_rationale_mentions_data_characteristics(self):
        """rationale 에 데이터 특성 키워드가 포함."""
        from agents.handlers.tabular.selector import score

        # 대용량 불균형
        state = self._state(n_rows=10000, imbalance=15.0)
        result = score(state, recipes=[])
        rationale = result["rationale"]
        assert "대용량" in rationale or "불균형" in rationale


# ---------------------------------------------------------------------------
# Day 11 (jh) — 다중 지표 보강 (PR AUC / MCC / log_loss / Brier / 잔차 / val_r2 임계)
# ---------------------------------------------------------------------------


class TestExtendedMetrics:
    """pipeline.evaluate() 가 다중 지표를 반환하는지 + evaluator val_r2 게이트 검증."""

    @pytest.fixture
    def binary_clf(self):
        rng = np.random.RandomState(42)
        X = rng.normal(size=(200, 4))
        y = (X[:, 0] + X[:, 1] > 0).astype(int)
        return X, y

    @pytest.fixture
    def multi_clf(self):
        from sklearn.datasets import load_iris

        d = load_iris(as_frame=False)
        return d.data, d.target

    @pytest.fixture
    def reg_data(self):
        rng = np.random.RandomState(42)
        X = rng.normal(size=(200, 4))
        y = X[:, 0] * 2 + X[:, 1] + rng.normal(0, 0.1, size=200)
        return X, y

    def _fit_eval(self, X, y, model_name, task):
        from pipelines.tabular_ml.pipeline import TabularMLPipeline

        pipe = TabularMLPipeline()
        params = {"random_state": 42} if model_name in ("Ridge",) else {"n_estimators": 30, "random_state": 42}
        model = pipe.train(X, y, model_name, params)
        return pipe.evaluate(model, X, y, task)

    def test_binary_includes_pr_auc(self, binary_clf):
        X, y = binary_clf
        m = self._fit_eval(X, y, "RandomForest", "classification")
        assert "val_pr_auc" in m
        assert 0 <= m["val_pr_auc"] <= 1.0

    def test_binary_includes_mcc(self, binary_clf):
        X, y = binary_clf
        m = self._fit_eval(X, y, "RandomForest", "classification")
        assert "val_mcc" in m
        # MCC 범위: -1 ~ +1
        assert -1.0 <= m["val_mcc"] <= 1.0

    def test_binary_includes_log_loss(self, binary_clf):
        X, y = binary_clf
        m = self._fit_eval(X, y, "RandomForest", "classification")
        assert "val_log_loss" in m
        assert m["val_log_loss"] >= 0

    def test_binary_includes_brier(self, binary_clf):
        X, y = binary_clf
        m = self._fit_eval(X, y, "RandomForest", "classification")
        assert "val_brier" in m
        # Brier score 범위: 0 ~ 1
        assert 0 <= m["val_brier"] <= 1.0

    def test_binary_includes_optimal_threshold(self, binary_clf):
        X, y = binary_clf
        m = self._fit_eval(X, y, "RandomForest", "classification")
        assert "val_optimal_threshold" in m
        assert 0 <= m["val_optimal_threshold"] <= 1.0
        assert "val_f1_at_optimal_threshold" in m

    def test_multiclass_includes_per_class_f1(self, multi_clf):
        X, y = multi_clf
        m = self._fit_eval(X, y, "RandomForest", "classification")
        assert "val_f1_per_class" in m
        per_class = m["val_f1_per_class"]
        assert isinstance(per_class, dict)
        assert len(per_class) == 3  # Iris 3 클래스

    def test_dummy_has_lower_mcc_than_strong_model(self, binary_clf):
        """Dummy MCC 는 0 근처, 강모델은 더 높아야 함."""
        X, y = binary_clf
        dummy = self._fit_eval(X, y, "Dummy", "classification")
        rf = self._fit_eval(X, y, "RandomForest", "classification")
        # Dummy 의 MCC 는 stratified random 이라 ~0, RF 는 신호 학습 후 > 0
        assert rf["val_mcc"] > dummy["val_mcc"]

    def test_regression_includes_residual_stats(self, reg_data):
        X, y = reg_data
        m = self._fit_eval(X, y, "Ridge", "regression")
        assert "val_residual_mean" in m
        assert "val_residual_median" in m
        assert "val_residual_std" in m
        assert "val_residual_abs_max" in m
        assert m["val_residual_std"] >= 0

    def test_evaluator_val_r2_threshold_added(self):
        """C4 해소 — THRESHOLDS_BY_CAT['tabular_ml'] 에 val_r2 임계 등록."""
        from agents.handlers.tabular.evaluator import THRESHOLDS_BY_CAT

        assert "val_r2" in THRESHOLDS_BY_CAT["tabular_ml"]
        assert THRESHOLDS_BY_CAT["tabular_ml"]["val_r2"] == 0.30

    def test_evaluator_fails_when_val_r2_below_threshold(self):
        """회귀 게이트 — val_r2 가 0.30 미만이면 passed=False."""
        from ada.core.state import PipelineState
        from agents.handlers.tabular.evaluator import evaluate

        state = PipelineState(
            job_id="t",
            file_id="m",
            category="tabular_ml",
            target_column="y",
            best_model={"model_name": "Ridge", "metrics": {"val_r2": 0.10}},
        )
        result = evaluate(state)
        assert result["passed"] is False
        assert any("val_r2" in v for v in result["threshold_violations"])

    def test_evaluator_passes_when_val_r2_above_threshold(self):
        """회귀 게이트 — val_r2 >= 0.30 면 passed=True."""
        from ada.core.state import PipelineState
        from agents.handlers.tabular.evaluator import evaluate

        state = PipelineState(
            job_id="t",
            file_id="m",
            category="tabular_ml",
            target_column="y",
            best_model={"model_name": "Ridge", "metrics": {"val_r2": 0.55}},
        )
        result = evaluate(state)
        assert result["passed"] is True


# ---------------------------------------------------------------------------
# Day 11 (jh) — 잔차 차트 (회귀 진단)
# ---------------------------------------------------------------------------


class TestResidualChart:
    def _state(self, *, task="regression", model_name="Ridge", category="tabular_ml"):
        from ada.core.state import PipelineState

        return PipelineState(
            job_id="t",
            file_id="m",
            category=category,
            target_column="y",
            task=task,
            best_model={"model_name": model_name, "metrics": {"val_r2": 0.55}},
        )

    def test_skips_when_classification(self):
        """분류 task 면 residual chart skip."""
        from agents.handlers.tabular.output_extras import _build_residual_chart

        state = self._state(task="classification")
        # 분류 best_model 도 강제 — metrics 로 분류 판단
        from ada.core.state import PipelineState

        state = PipelineState(
            job_id="t", file_id="m", category="tabular_ml", target_column="y",
            task="classification",
            best_model={"model_name": "RandomForest", "metrics": {"val_f1": 0.83}},
        )
        assert _build_residual_chart(state) is None

    def test_skips_when_baseline_model(self):
        from agents.handlers.tabular.output_extras import _build_residual_chart

        for name in ("Dummy", "Ridge"):
            state = self._state(model_name=name)
            assert _build_residual_chart(state) is None, f"{name} 은 skip"

    def test_skips_gracefully_when_model_reload_fails(self):
        """MinIO 없는 환경에서 모델 재로드 실패 → None 반환."""
        from agents.handlers.tabular.output_extras import _build_residual_chart

        state = self._state(model_name="RandomForest")
        # task="regression" 인데 model_name=RandomForest → _is_classification False 되도록
        # eval_result/best_model 의 metrics 가 회귀 metric (val_r2) 만 가지면 회귀로 판단
        assert _build_residual_chart(state) is None


# ---------------------------------------------------------------------------
# Day 11 (jh) — diagnostics 모듈 (Permutation / PDP / QQ Plot)
# ---------------------------------------------------------------------------


class TestDiagnostics:
    """diagnostics 차트 3종의 가드 + 안전 동작 검증.

    실제 차트 생성은 MinIO + 모델 재로드 필요 → 운영 환경에서만.
    단위 테스트는 가드 로직과 graceful skip 만.
    """

    def _state(
        self,
        *,
        category="tabular_ml",
        n_rows=300,
        model_name="RandomForest",
        task="classification",
    ):
        from ada.core.state import PipelineState

        metrics = {"val_f1": 0.83} if task == "classification" else {"val_r2": 0.55}
        return PipelineState(
            job_id="t",
            file_id="m",
            category=category,
            target_column="y",
            task=task,
            data_profile={"rows": n_rows, "class_distribution": {"0": 0.5, "1": 0.5}},
            best_model={"model_name": model_name, "metrics": metrics},
        )

    # ───── permutation_importance_chart ─────

    def test_permutation_skips_when_baseline(self):
        from agents.handlers.tabular.diagnostics import permutation_importance_chart

        for name in ("Dummy", "LogisticRegression", "Ridge"):
            state = self._state(model_name=name)
            assert permutation_importance_chart(state) is None

    def test_permutation_skips_when_dl(self):
        from agents.handlers.tabular.diagnostics import permutation_importance_chart

        state = self._state(category="tabular_dl", model_name="FTTransformer")
        assert permutation_importance_chart(state) is None

    def test_permutation_skips_when_large_data(self):
        from agents.handlers.tabular.diagnostics import permutation_importance_chart

        state = self._state(n_rows=10000)
        assert permutation_importance_chart(state) is None

    def test_permutation_skips_gracefully_when_reload_fails(self):
        from agents.handlers.tabular.diagnostics import permutation_importance_chart

        state = self._state(model_name="RandomForest")
        # MinIO 없는 단위 환경 → 재로드 실패 → None
        assert permutation_importance_chart(state) is None

    # ───── pdp_chart ─────

    def test_pdp_skips_when_baseline(self):
        from agents.handlers.tabular.diagnostics import pdp_chart

        state = self._state(model_name="Dummy")
        assert pdp_chart(state) is None

    def test_pdp_skips_when_dl(self):
        from agents.handlers.tabular.diagnostics import pdp_chart

        state = self._state(category="tabular_dl", model_name="FTTransformer")
        assert pdp_chart(state) is None

    def test_pdp_skips_gracefully_when_reload_fails(self):
        from agents.handlers.tabular.diagnostics import pdp_chart

        state = self._state(model_name="RandomForest")
        assert pdp_chart(state) is None

    # ───── qq_plot_chart ─────

    def test_qq_plot_skips_when_classification(self):
        from agents.handlers.tabular.diagnostics import qq_plot_chart

        state = self._state(task="classification")
        assert qq_plot_chart(state) is None

    def test_qq_plot_skips_when_baseline(self):
        from agents.handlers.tabular.diagnostics import qq_plot_chart

        state = self._state(task="regression", model_name="Ridge")
        assert qq_plot_chart(state) is None

    def test_qq_plot_skips_gracefully_when_reload_fails(self):
        from agents.handlers.tabular.diagnostics import qq_plot_chart

        state = self._state(task="regression", model_name="RandomForest")
        assert qq_plot_chart(state) is None

    # ───── output_extras 통합 ─────

    def test_output_extras_assets_invokes_diagnostics_safely(self):
        """assets() 가 diagnostics 함수 호출 중 예외 일어나도 charts 리스트 반환."""
        from agents.handlers.tabular.output_extras import assets

        state = self._state()
        result = assets(state)
        # 단위 환경에선 다 None 반환 → charts 비어있을 수 있지만 dict 구조는 유지
        assert "charts" in result
        assert isinstance(result["charts"], list)


# ---------------------------------------------------------------------------
# Day 11 (jh) — EDA 보강 (id-like / target leakage / mutual_info / target↔feature)
# ---------------------------------------------------------------------------


class TestEdaEnhancement:
    """profiler 보강 3개 키 + eda 차트 4번째 검증."""

    def _state(self, target="y"):
        from ada.core.state import PipelineState

        return PipelineState(
            job_id="t",
            file_id="m",
            category="tabular_ml",
            target_column=target,
            task="classification",
        )

    def test_id_like_columns_detected(self):
        """unique_ratio ≥ 0.99 컬럼이 id_like_columns 에 잡힘."""
        from agents.handlers.tabular.profiler import profile

        df = pd.DataFrame({
            "user_id": range(100),  # 100% unique → id-like
            "age": np.random.RandomState(42).randint(20, 70, size=100),
            "y": np.random.RandomState(0).randint(0, 2, size=100),
        })
        result = profile(df, self._state())
        assert "id_like_columns" in result
        assert "user_id" in result["id_like_columns"]
        # age 는 unique_ratio 낮으니 id-like 아님
        assert "age" not in result["id_like_columns"]

    def test_target_not_flagged_as_id_like(self):
        """target 컬럼은 unique 해도 id-like 분류 제외."""
        from agents.handlers.tabular.profiler import profile

        df = pd.DataFrame({
            "x": np.random.RandomState(42).normal(size=50),
            "y": range(50),  # target 이 100% unique 라도 무시
        })
        result = profile(df, self._state())
        assert "y" not in result.get("id_like_columns", [])

    def test_target_leakage_detected_numeric_target(self):
        """target 과 |corr| ≥ 0.95 numeric 컬럼이 leakage 의심으로 잡힘."""
        from agents.handlers.tabular.profiler import profile

        rng = np.random.RandomState(42)
        y_val = rng.normal(size=200)
        df = pd.DataFrame({
            "leaky": y_val + rng.normal(0, 0.05, size=200),  # 거의 동일 → corr≈1
            "noise": rng.normal(size=200),
            "y": y_val,
        })
        state = self._state(target="y")
        state = state.with_update(task="regression")
        result = profile(df, state)
        leak = result.get("target_leakage_suspects", [])
        cols = {item["column"] for item in leak}
        assert "leaky" in cols
        assert "noise" not in cols

    def test_target_leakage_empty_when_no_strong_corr(self):
        """target 과 강한 상관 없으면 leakage 의심 빈 리스트."""
        from agents.handlers.tabular.profiler import profile

        rng = np.random.RandomState(42)
        df = pd.DataFrame({
            "a": rng.normal(size=200),
            "b": rng.normal(size=200),
            "y": rng.randint(0, 2, size=200),
        })
        result = profile(df, self._state())
        assert result.get("target_leakage_suspects", []) == []

    def test_mutual_info_top_returned_for_classification(self):
        """분류 시나리오에서 mutual_info_top 이 dict 로 반환."""
        from agents.handlers.tabular.profiler import profile

        rng = np.random.RandomState(42)
        # 신호 컬럼 (x_signal) 과 노이즈 컬럼
        n = 300
        x_signal = rng.normal(size=n)
        y_binary = (x_signal > 0).astype(int)
        df = pd.DataFrame({
            "x_signal": x_signal,
            "noise1": rng.normal(size=n),
            "noise2": rng.normal(size=n),
            "y": y_binary,
        })
        result = profile(df, self._state())
        mi_top = result.get("mutual_info_top", {})
        assert isinstance(mi_top, dict)
        if mi_top:
            # x_signal 의 MI 가 noise 들보다 커야 함
            assert mi_top.get("x_signal", 0) > mi_top.get("noise1", 0)

    def test_mutual_info_handles_categorical_features(self):
        """categorical 피처도 frequency encoding 으로 MI 계산 가능."""
        from agents.handlers.tabular.profiler import profile

        rng = np.random.RandomState(42)
        n = 200
        df = pd.DataFrame({
            "cat": rng.choice(["a", "b", "c"], size=n),
            "num": rng.normal(size=n),
            "y": rng.randint(0, 2, size=n),
        })
        result = profile(df, self._state())
        # 예외 없이 dict 반환
        assert isinstance(result.get("mutual_info_top", {}), dict)

    def test_eda_charts_include_target_feature_chart(self):
        """eda.charts() 가 4번째 차트(target↔feature) 시도 — MinIO 환경에선 실제 path 생성."""
        from agents.handlers.tabular.eda import charts

        rng = np.random.RandomState(42)
        df = pd.DataFrame({
            "age": rng.randint(20, 70, size=100),
            "income": rng.normal(50000, 10000, size=100),
            "y": rng.randint(0, 2, size=100),
        })
        # MinIO 없는 단위 환경 → save 가 실패하면 None 이 paths 에 안 들어감.
        # 함수는 예외 없이 list 반환만 보장.
        result = charts(df, self._state())
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Day 11 (jh) — insight 풀 보강 (모든 신규 메타데이터 노출 + fallback 인용)
# ---------------------------------------------------------------------------


class TestInsightFullPayload:
    """우리가 만든 모든 메타데이터가 prompt_payload 에 노출되고
    fallback 이 핵심 메타데이터를 인용하는지 검증.
    """

    def _state(self, **overrides):
        from ada.core.state import PipelineState

        defaults = dict(
            job_id="t",
            file_id="m",
            category="tabular_ml",
            target_column="y",
            best_model={"model_name": "XGBoost", "metrics": {"val_f1": 0.83}},
        )
        defaults.update(overrides)
        return PipelineState(**defaults)

    # ───── prompt_payload — 모든 키 노출 ─────

    def test_payload_includes_all_day11_keys(self):
        """우리가 추가한 모든 메타데이터 키가 payload에 노출."""
        from agents.handlers.tabular.insight import prompt_payload

        state = self._state()
        payload = prompt_payload(state)
        expected_keys = {
            "category", "user_intent", "best_model", "shap_top",
            "eval_result", "metrics_full",
            "improvement_over_baseline", "baseline_used",
            "cv_stats", "baseline_cv_stats",
            "model_scores",
            "id_like_columns", "target_leakage_suspects", "mutual_info_top",
            "optimal_threshold", "f1_at_optimal_threshold",
            "class_imbalance_ratio", "n_rows",
            "leakage_safe_split_used",
        }
        missing = expected_keys - set(payload.keys())
        assert not missing, f"payload 누락 키: {missing}"

    def test_payload_exposes_leakage_suspects(self):
        from agents.handlers.tabular.insight import prompt_payload

        state = self._state(
            data_profile={
                "target_leakage_suspects": [{"column": "leaky", "correlation": 0.97}],
                "id_like_columns": ["user_id"],
            },
        )
        payload = prompt_payload(state)
        assert payload["target_leakage_suspects"] == [{"column": "leaky", "correlation": 0.97}]
        assert payload["id_like_columns"] == ["user_id"]

    def test_payload_exposes_optimal_threshold_from_metrics(self):
        from agents.handlers.tabular.insight import prompt_payload

        state = self._state(
            best_model={
                "model_name": "XGBoost",
                "metrics": {
                    "val_f1": 0.83,
                    "val_optimal_threshold": 0.37,
                    "val_f1_at_optimal_threshold": 0.86,
                },
            },
        )
        payload = prompt_payload(state)
        assert payload["optimal_threshold"] == 0.37
        assert payload["f1_at_optimal_threshold"] == 0.86

    def test_payload_leakage_safe_split_flag(self):
        """category_extras 의 leakage_safe_split 메타 → 불린 flag 노출."""
        from agents.handlers.tabular.insight import prompt_payload

        state = self._state(
            category_extras={
                "tabular": {"leakage_safe_split": {"method": "split_first_train_fit"}}
            },
        )
        payload = prompt_payload(state)
        assert payload["leakage_safe_split_used"] is True

        state2 = self._state(category_extras={"tabular": {}})
        payload2 = prompt_payload(state2)
        assert payload2["leakage_safe_split_used"] is False

    # ───── fallback — 신규 메타데이터 인용 ─────

    def test_fallback_cites_target_leakage_warning(self):
        from agents.handlers.tabular.insight import fallback

        state = self._state(
            data_profile={
                "target_leakage_suspects": [{"column": "leaky_col", "correlation": 0.97}],
            },
        )
        text = fallback(state)
        assert "leaky_col" in text
        assert "누수" in text

    def test_fallback_cites_id_like_warning(self):
        from agents.handlers.tabular.insight import fallback

        state = self._state(
            data_profile={"id_like_columns": ["user_id", "transaction_id"]},
        )
        text = fallback(state)
        assert "user_id" in text
        assert "식별자" in text

    def test_fallback_cites_optimal_threshold(self):
        from agents.handlers.tabular.insight import fallback

        state = self._state(
            best_model={
                "model_name": "XGBoost",
                "metrics": {
                    "val_f1": 0.83,
                    "val_optimal_threshold": 0.37,
                    "val_f1_at_optimal_threshold": 0.86,
                },
            },
        )
        text = fallback(state)
        assert "0.37" in text
        assert "임계값" in text

    def test_fallback_cites_weak_class_for_multiclass(self):
        from agents.handlers.tabular.insight import fallback

        state = self._state(
            best_model={
                "model_name": "RandomForest",
                "metrics": {
                    "val_f1": 0.75,
                    "val_f1_per_class": {"0": 0.85, "1": 0.80, "2": 0.45},
                },
            },
        )
        text = fallback(state)
        # 가장 약한 클래스 '2' 가 0.45 로 언급
        assert "2" in text
        assert "0.45" in text

    def test_fallback_cites_residual_bias_for_regression(self):
        from agents.handlers.tabular.insight import fallback

        state = self._state(
            best_model={
                "model_name": "Ridge",
                "metrics": {
                    "val_r2": 0.55,
                    "val_residual_mean": 0.35,  # |0.1| 초과 → 편향 의심
                },
            },
        )
        text = fallback(state)
        assert "편향" in text
        assert "0.35" in text

    def test_fallback_no_warnings_when_clean_data(self):
        """누수/식별자 없으면 경고 문구 없음 — 깨끗한 데이터엔 깔끔한 인사이트."""
        from agents.handlers.tabular.insight import fallback

        state = self._state()  # data_profile 없음
        text = fallback(state)
        assert "누수" not in text
        assert "식별자" not in text

    def test_fallback_combines_baseline_lift_with_significance(self):
        """베이스라인 격차 + 유의성을 한 문장에 표현."""
        from agents.handlers.tabular.insight import fallback

        state = self._state(
            eval_result={
                "improvement_over_baseline": {
                    "primary_metric": "val_f1",
                    "primary_lift": 0.32,
                    "lift_significant": True,
                },
                "baseline_used": {"name": "Dummy"},
            },
        )
        text = fallback(state)
        assert "Dummy" in text
        assert "0.32" in text
        assert "통계적으로 유의" in text
