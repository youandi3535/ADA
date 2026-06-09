"""tests.handlers.tabular.test_honest_gap — 약속 ↔ 행동 일치 검증 (jh, Day 11++).

honest gap closure 검증:
  Gap 1: calibration 이 측정만 하고 실제 serving 에 적용 안 되던 거짓말 해소
    - apply_calibration(state, raw_proba) 가 보정된 확률 반환
    - pipeline.predict_proba_calibrated(model, X, state) 가 보정 결과 반환

  Gap 2: archetype 의 preprocessing_must/should_not 룰이 plan 에 반영 안 되던
    상태 해소
    - preprocessor.plan(state) 이 forbid 룰로 step 제거
    - preprocessor.plan(state) 이 must 룰로 step 강제 추가
    - confidence < 0.5 인 경계선 매칭은 룰 무시 (cliff 회피)
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from agents.handlers.tabular import calibration as cal_mod, preprocessor as prep_mod

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


class _SimpleState:
    def __init__(self, **kwargs):
        self.category = kwargs.get("category", "tabular_ml")
        self.task = kwargs.get("task", "classification")
        self.best_model = kwargs.get("best_model")
        self.data_profile = kwargs.get("data_profile") or {}
        self.target_column = kwargs.get("target_column", "y")
        self.category_extras = kwargs.get("category_extras") or {}
        self.job_id = kwargs.get("job_id", "test-honest")


# ──────────────────────────────────────────────────────────────────────────────
# Gap 1: calibration 적용
# ──────────────────────────────────────────────────────────────────────────────


class TestApplyCalibration:
    """apply_calibration 이 honest 보정 확률 반환."""

    def test_returns_raw_when_no_method(self):
        """calibration.method 없으면 raw 그대로."""
        state = _SimpleState(category_extras={})
        raw = np.array([0.1, 0.5, 0.9])
        out = cal_mod.apply_calibration(state, raw)
        assert np.allclose(out, raw), "method 없는데 보정됨 — 기대 raw"

    def test_returns_raw_when_no_calibrator_path_and_no_reload(self):
        """method 만 있고 calibrator 도 없고 모델 reload 도 실패 → raw 그대로 (graceful)."""
        state = _SimpleState(
            best_model=None,
            category_extras={"tabular": {"calibration": {"method": "platt"}}},
        )
        raw = np.array([0.1, 0.5, 0.9])
        out = cal_mod.apply_calibration(state, raw)
        # graceful — exception 안 나고 raw 반환
        assert np.allclose(out, raw)

    def test_calibrator_serialization_round_trip(self):
        """직렬화·복원이 동일 결과 반환 (apply_calibration 의 핵심 가정)."""
        import io

        import joblib

        # 보정기 학습
        rng = np.random.default_rng(42)
        n = 200
        y_proba = rng.uniform(0, 1, n)
        y_true = (rng.uniform(0, 1, n) < y_proba).astype(int)
        calibrator = cal_mod.fit_platt(y_true, y_proba)

        # 직렬화 → 복원
        buf = io.BytesIO()
        joblib.dump({"calibrator": calibrator, "method": "platt"}, buf)
        buf.seek(0)
        loaded = joblib.load(buf)

        # 동일 결과
        test_proba = np.array([0.2, 0.5, 0.8])
        out_original = calibrator(test_proba)
        out_loaded = loaded["calibrator"](test_proba)
        assert np.allclose(out_original, out_loaded)


class TestPredictProbaCalibrated:
    """pipeline.predict_proba_calibrated 가 honest 확률 반환."""

    def test_returns_raw_for_no_predict_proba(self):
        """predict_proba 없는 모델은 predict() 결과 반환."""
        from pipelines.tabular_ml.pipeline import TabularMLPipeline

        class _NoProbaModel:
            def predict(self, X):
                return np.zeros(len(X))

        pipe = TabularMLPipeline()
        state = _SimpleState()
        X = np.array([[0.1], [0.5], [0.9]])
        result = pipe.predict_proba_calibrated(_NoProbaModel(), X, state)
        assert len(result) == 3

    def test_returns_raw_when_calibration_skip(self):
        """calibration.method 없으면 model.predict_proba 그대로."""
        from sklearn.ensemble import RandomForestClassifier

        from pipelines.tabular_ml.pipeline import TabularMLPipeline

        rng = np.random.default_rng(7)
        X = rng.normal(0, 1, (100, 3))
        y = (X[:, 0] > 0).astype(int)
        model = RandomForestClassifier(n_estimators=10, random_state=7)
        model.fit(X, y)

        pipe = TabularMLPipeline()
        state = _SimpleState(category_extras={"tabular": {}})

        # 보정 정보 없으면 raw 양성 클래스 컬럼 반환
        result = pipe.predict_proba_calibrated(model, X, state)
        raw = model.predict_proba(X)[:, 1]
        assert np.allclose(result, raw), "보정 정보 없는데 결과 변경됨"

    def test_multiclass_returns_full_matrix(self):
        """다중분류는 보정 안 적용 (현재 구현은 이진만), 전체 행렬 반환."""
        from sklearn.ensemble import RandomForestClassifier

        from pipelines.tabular_ml.pipeline import TabularMLPipeline

        rng = np.random.default_rng(11)
        X = rng.normal(0, 1, (150, 3))
        y = rng.integers(0, 3, 150)  # 3 class
        model = RandomForestClassifier(n_estimators=10, random_state=11)
        model.fit(X, y)

        pipe = TabularMLPipeline()
        state = _SimpleState()
        result = pipe.predict_proba_calibrated(model, X, state)
        # multi-class 면 (n, n_classes) 그대로 반환
        assert result.ndim == 2
        assert result.shape[1] == 3


# ──────────────────────────────────────────────────────────────────────────────
# Gap 2: preprocessor 가 archetype 룰 반영
# ──────────────────────────────────────────────────────────────────────────────


class TestPreprocessorArchetypeRules:
    """preprocessor.plan() 이 archetype.EXPECTED_DECISIONS 의 must/should_not 반영."""

    def test_forbid_rule_removes_step_from_plan(self):
        """preprocessing_should_not 에 있는 transform 은 plan 에서 제거."""
        steps_before = [
            {"name": "smote_resample", "params": {}, "needs_review": False},
            {"name": "scale_numeric", "method": "robust", "params": {}, "needs_review": False},
        ]
        profile_with_forbid = {
            "archetype": {
                "primary": "extreme_imbalance",
                "primary_confidence": 0.95,
                "expected": {
                    "preprocessing_should_not": ["smote_resample"],
                },
            },
        }

        steps_after = prep_mod._apply_archetype_rules_to_plan(steps_before, profile_with_forbid)
        names_after = {s["name"] for s in steps_after}
        assert "smote_resample" not in names_after, (
            f"extreme_imbalance 에서 smote_resample 차단 실패: {names_after}"
        )
        # 다른 step 은 보존
        assert "scale_numeric" in names_after

    def test_must_rule_adds_step_to_plan(self):
        """preprocessing_must 에 있는 transform 이 plan 에 없으면 강제 추가."""
        steps_before = [
            {"name": "scale_numeric", "method": "robust", "params": {}, "needs_review": False},
        ]
        profile_with_must = {
            "archetype": {
                "primary": "target_leakage_suspected",
                "primary_confidence": 0.9,
                "expected": {
                    "preprocessing_must": ["leakage_column_drop"],
                },
            },
        }

        steps_after = prep_mod._apply_archetype_rules_to_plan(steps_before, profile_with_must)
        names_after = {s["name"] for s in steps_after}
        assert "leakage_column_drop" in names_after, (
            f"target_leakage_suspected 에서 leakage_column_drop 강제 추가 실패: {names_after}"
        )

    def test_must_added_step_has_needs_review(self):
        """archetype 룰로 강제 추가된 step 은 needs_review=True (사용자 검토 요청)."""
        steps_before = []
        profile = {
            "archetype": {
                "primary": "target_leakage_suspected",
                "primary_confidence": 0.9,
                "expected": {"preprocessing_must": ["leakage_column_drop"]},
            },
        }
        steps_after = prep_mod._apply_archetype_rules_to_plan(steps_before, profile)
        added = next((s for s in steps_after if s["name"] == "leakage_column_drop"), None)
        assert added is not None
        assert added["needs_review"] is True
        assert added.get("source", "").startswith("archetype:")

    def test_low_confidence_ignores_rules(self):
        """primary_confidence < 0.5 이면 룰 무시 (경계선 매칭 cliff 회피)."""
        steps_before = [
            {"name": "smote_resample", "params": {}, "needs_review": False},
        ]
        profile_low_conf = {
            "archetype": {
                "primary": "extreme_imbalance",
                "primary_confidence": 0.3,  # 경계선 미만
                "expected": {"preprocessing_should_not": ["smote_resample"]},
            },
        }
        steps_after = prep_mod._apply_archetype_rules_to_plan(steps_before, profile_low_conf)
        names_after = {s["name"] for s in steps_after}
        # confidence 너무 낮으면 룰 무시 → smote 그대로
        assert "smote_resample" in names_after, (
            "confidence 0.3 인데 룰이 적용됨 — cliff 회피 룰 위반"
        )

    def test_clean_balanced_no_rules_no_change(self):
        """clean_balanced archetype 은 룰 비어있어 plan 변경 없음."""
        steps_before = [
            {"name": "scale_numeric", "method": "robust", "params": {}, "needs_review": False},
            {"name": "impute_numeric", "strategy": "median", "params": {}, "needs_review": False},
        ]
        profile_clean = {
            "archetype": {
                "primary": "clean_balanced",
                "primary_confidence": 1.0,
                "expected": {"threshold_strategy": "f1_max"},  # must/forbid 없음
            },
        }
        steps_after = prep_mod._apply_archetype_rules_to_plan(steps_before, profile_clean)
        names_before = {s["name"] for s in steps_before}
        names_after = {s["name"] for s in steps_after}
        assert names_before == names_after, (
            "clean_balanced 인데 plan 변경됨"
        )

    def test_no_archetype_no_change(self):
        """archetype 정보 없는 profile 은 plan 그대로."""
        steps_before = [{"name": "scale_numeric", "params": {}}]
        steps_after = prep_mod._apply_archetype_rules_to_plan(steps_before, {})
        assert steps_after == steps_before


# ──────────────────────────────────────────────────────────────────────────────
# Gap 2 통합 — plan() 진입점에서 실제 동작 검증
# ──────────────────────────────────────────────────────────────────────────────


class TestPlanIntegrationWithArchetype:
    """preprocessor.plan() 진입점에서 archetype 룰이 실제로 작동."""

    def test_plan_with_leakage_archetype_includes_drop(self):
        """target_leakage_suspected archetype 이 있으면 plan 에 leakage_column_drop 포함."""
        state = _SimpleState(
            data_profile={
                "rows": 500,
                "cols": 6,
                "n_numeric": 5,
                "dtypes": {"x1": "float64", "x2": "float64", "x3": "float64",
                          "x4": "float64", "x5": "float64", "y": "int64"},
                "missing": {},
                "class_imbalance_ratio": 1.5,
                "cardinality_levels": {},
                "archetype": {
                    "primary": "target_leakage_suspected",
                    "primary_confidence": 0.95,
                    "expected": {
                        "preprocessing_must": ["leakage_column_drop"],
                        "selector_top1_in": {"RandomForest"},
                    },
                },
            },
        )
        plan = prep_mod.plan(state)
        names = {s["name"] for s in plan}
        assert "leakage_column_drop" in names, (
            f"target_leakage archetype 에서 plan 에 leakage_column_drop 없음: {names}"
        )
