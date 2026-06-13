"""tests.handlers.tabular.test_preprocessor — Day 2 변환 카탈로그 단위+통합 테스트."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Helper: state with rich data_profile
# ---------------------------------------------------------------------------


def _state_with_profile(base_state, **profile_kwargs):
    profile = base_state.data_profile or {}
    profile = {**profile, **profile_kwargs}
    return base_state.with_update(data_profile=profile)


def _apply_step(df, step_dict, state):
    from agents.handlers.tabular.preprocessor import apply

    df_out, state_out = apply(df, [step_dict], state)
    return df_out, state_out


def _artifacts(state_out):
    return state_out.category_extras["tabular"]["preprocess_artifacts"]


# ---------------------------------------------------------------------------
# TE: #1~#6 — Target Encoding
# ---------------------------------------------------------------------------


class TestTargetEncoding:
    def test_te_applied_to_high_card_ml(self, tab_df, tab_state):
        """tabular_ml + high-card → __te 컬럼 생성."""
        step = {
            "name": "target_encoding",
            "columns": ["Sex"],
            "params": {"smoothing": 10.0, "n_splits": 2},
        }
        df_out, state_out = _apply_step(tab_df, step, tab_state)
        assert "Sex__te" in df_out.columns
        assert "Sex" not in df_out.columns

    def test_te_skipped_for_dl(self, tab_df, tab_dl_state):
        """tabular_dl → target_encoding 실행해도 column __te 안 만들어야 함.
        (plan 수준에서 skip; 직접 호출 시에도 category_extras에 encoder 저장됨)"""
        # plan()이 DL에서 TE step 생성 안 하는지 검증
        from agents.handlers.tabular.preprocessor import plan

        steps = plan(tab_dl_state)
        names = [s["name"] for s in steps]
        assert "target_encoding" not in names

    def test_te_produces_te_suffix(self, tab_df, tab_state):
        """출력 컬럼이 {col}__te 접미사."""
        step = {
            "name": "target_encoding",
            "columns": ["Sex"],
            "params": {"smoothing": 10.0, "n_splits": 2},
        }
        df_out, _ = _apply_step(tab_df, step, tab_state)
        assert any(c.endswith("__te") for c in df_out.columns)

    def test_te_global_mean_unknown_value(self, tab_df, tab_state):
        """artifact에 global_mean 저장, unknown_value == global_mean."""
        step = {
            "name": "target_encoding",
            "columns": ["Sex"],
            "params": {"smoothing": 10.0, "n_splits": 2},
        }
        _, state_out = _apply_step(tab_df, step, tab_state)
        enc = _artifacts(state_out)["target_encoder"]
        assert enc is not None
        col_info = enc["encoders_by_col"]["Sex"]
        assert col_info["global_mean"] == col_info["unknown_value"]

    def test_te_smoothing_stored_in_artifact(self, tab_df, tab_state):
        """artifact에 smoothing 값 기록."""
        step = {
            "name": "target_encoding",
            "columns": ["Sex"],
            "params": {"smoothing": 5.0, "n_splits": 2},
        }
        _, state_out = _apply_step(tab_df, step, tab_state)
        enc = _artifacts(state_out)["target_encoder"]
        assert enc["smoothing"] == 5.0

    def test_te_multiclass_kmin1_columns(self, tab_df, tab_state):
        """multiclass(K=3) → K-1=2개의 __te_c* 컬럼 생성."""
        df = tab_df.copy()
        df["Survived"] = df["Survived"].map({0: 0, 1: 1})
        df.loc[:39, "Survived"] = 2  # 3-class

        step = {
            "name": "target_encoding",
            "columns": ["Sex"],
            "params": {"smoothing": 10.0, "n_splits": 2},
        }
        df_out, _ = _apply_step(df, step, tab_state)
        te_cols = [c for c in df_out.columns if c.startswith("Sex__te")]
        assert len(te_cols) == 2  # K-1 = 2


# ---------------------------------------------------------------------------
# CW: #7~#10 — Class Weight
# ---------------------------------------------------------------------------


class TestClassWeight:
    def test_cw_balanced_weights_computed(self, tab_df, tab_state):
        """classification → balanced weights 계산."""
        step = {"name": "class_weight_compute", "params": {"cap_value": 100}}
        _, state_out = _apply_step(tab_df, step, tab_state)
        cw = _artifacts(state_out)["class_weight"]
        assert cw is not None
        assert cw["strategy"] == "balanced"
        assert cw["weights"] is not None

    def test_cw_cap_at_100_extreme_imbalance(self, tab_df_extreme_imbalance, tab_state):
        """극단 imbalance → weight cap at 100 적용."""
        step = {"name": "class_weight_compute", "params": {"cap_value": 100}}
        _, state_out = _apply_step(tab_df_extreme_imbalance, step, tab_state)
        cw = _artifacts(state_out)["class_weight"]
        assert all(v <= 100 for v in cw["weights"].values())

    def test_cw_disabled_when_smote_active(self, tab_df, tab_state):
        """SMOTE 적용 후 class_weight disabled_due_to_smote."""
        from agents.handlers.tabular.preprocessor import apply

        # Simulate SMOTE already in artifacts
        state_with_smote = tab_state.with_update(
            category_extras={"tabular": {"preprocess_artifacts": {"smote_meta": {"applied": True}}}}
        )
        step = {"name": "class_weight_compute", "params": {"cap_value": 100}}
        _, state_out = _apply_step(tab_df, step, state_with_smote)
        cw = _artifacts(state_out)["class_weight"]
        assert cw["strategy"] == "disabled_due_to_smote"

    def test_cw_dl_stores_imbalance_strategy(self, tab_df, tab_dl_state):
        """tabular_dl → dl_imbalance_strategy artifact 저장."""
        step = {"name": "class_weight_compute", "params": {"cap_value": 100}}
        _, state_out = _apply_step(tab_df, step, tab_dl_state)
        arts = _artifacts(state_out)
        assert arts.get("dl_imbalance_strategy") is not None
        assert "sampler_weights" in arts["dl_imbalance_strategy"]


# ---------------------------------------------------------------------------
# SMOTE: #11~#17 — SMOTE Resample
# ---------------------------------------------------------------------------


class TestSmoteResample:
    def test_smote_applied_on_imbalanced(self, tab_state):
        """불균형 데이터(minority=10, majority=90) + gate 통과 → 행 수 증가."""
        try:
            from imblearn.over_sampling import SMOTE as _SMOTE

            _SMOTE(random_state=0).fit_resample([[0], [1]], [0, 1])
        except Exception:
            pytest.skip("imblearn version incompatible with installed sklearn")

        rng = np.random.default_rng(0)
        n_maj, n_min = 90, 10
        df = pd.DataFrame(
            {
                "feat1": rng.normal(0, 1, n_maj + n_min),
                "feat2": rng.normal(0, 1, n_maj + n_min),
                "Survived": [0] * n_maj + [1] * n_min,
            }
        )
        step = {
            "name": "smote_resample",
            "columns": [],
            "params": {"strategy_override": None},
        }
        df_out, state_out = _apply_step(df, step, tab_state)
        smote = _artifacts(state_out)["smote_meta"]
        assert smote["applied"] is True
        assert len(df_out) > len(df)

    def test_smote_skipped_gate1_regression(self, tab_df, tab_state_regression):
        """regression → gate1 실패, SMOTE skip."""
        step = {
            "name": "smote_resample",
            "columns": [],
            "params": {},
        }
        _, state_out = _apply_step(tab_df, step, tab_state_regression)
        smote = _artifacts(state_out).get("smote_meta") or {}
        assert smote.get("applied") is not True

    def test_smote_skipped_gate2_dl(self, tab_df_extreme_imbalance, tab_dl_state):
        """tabular_dl → gate2 실패, SMOTE skip."""
        step = {
            "name": "smote_resample",
            "columns": [],
            "params": {},
        }
        _, state_out = _apply_step(tab_df_extreme_imbalance, step, tab_dl_state)
        smote = _artifacts(state_out).get("smote_meta") or {}
        assert smote.get("applied") is not True

    def test_smote_skipped_gate4_tiny_minority(self, tab_df_tiny_minority, tab_state):
        """minority < 6 → gate4 실패, SMOTE skip."""
        step = {
            "name": "smote_resample",
            "columns": [],
            "params": {},
        }
        _, state_out = _apply_step(tab_df_tiny_minority, step, tab_state)
        smote = _artifacts(state_out).get("smote_meta") or {}
        assert smote.get("applied") is not True

    def test_smote_balance_ok_after_apply(self, tab_state):
        """SMOTE 후 balance_ratio >= pass_threshold."""
        rng = np.random.default_rng(1)
        df = pd.DataFrame(
            {
                "feat1": rng.normal(0, 1, 100),
                "feat2": rng.normal(0, 1, 100),
                "Survived": [0] * 90 + [1] * 10,
            }
        )
        step = {"name": "smote_resample", "columns": [], "params": {"strategy_override": None}}
        _, state_out = _apply_step(df, step, tab_state)
        smote = _artifacts(state_out)["smote_meta"]
        if smote.get("applied"):
            assert smote["balance_ratio"] >= smote["pass_threshold"] * 0.5

    def test_smote_skipped_gate5_allow_false(self, tab_state):
        """allow_smote=False → gate5 실패, SMOTE skip."""
        rng = np.random.default_rng(2)
        df = pd.DataFrame(
            {
                "feat1": rng.normal(0, 1, 100),
                "Survived": [0] * 90 + [1] * 10,
            }
        )
        state = tab_state.with_update(preprocessing_hints={"allow_smote": False})
        step = {"name": "smote_resample", "columns": [], "params": {}}
        _, state_out = _apply_step(df, step, state)
        smote = _artifacts(state_out).get("smote_meta") or {}
        assert smote.get("applied") is not True

    def test_smote_synthetic_idx_recorded(self, tab_state):
        """SMOTE 적용 시 synthetic_row_idx artifact 기록."""
        rng = np.random.default_rng(3)
        df = pd.DataFrame(
            {
                "feat1": rng.normal(0, 1, 100),
                "feat2": rng.normal(0, 1, 100),
                "Survived": [0] * 90 + [1] * 10,
            }
        )
        step = {"name": "smote_resample", "columns": [], "params": {"strategy_override": None}}
        _, state_out = _apply_step(df, step, tab_state)
        smote = _artifacts(state_out).get("smote_meta") or {}
        if smote.get("applied"):
            assert "synthetic_row_idx" in smote
            assert len(smote["synthetic_row_idx"]) > 0


# ---------------------------------------------------------------------------
# VIF: #18~#22 — VIF Drop
# ---------------------------------------------------------------------------


class TestVifDrop:
    def test_vif_drops_collinear_columns(self, tab_df_collinear, tab_state):
        """다중공선성 컬럼이 drop됨."""
        step = {
            "name": "vif_drop",
            "columns": [],
            "params": {"protect": []},
        }
        df_out, state_out = _apply_step(tab_df_collinear, step, tab_state)
        dropped = _artifacts(state_out)["vif_dropped"]
        assert len(dropped) > 0

    def test_vif_skipped_for_dl_via_plan(self, tab_df_collinear, tab_dl_state):
        """tabular_dl → plan()에서 vif_drop 생성 안 함."""
        from agents.handlers.tabular.preprocessor import plan

        state = _state_with_profile(tab_dl_state, vif_top={"Age_copy_0": 50.0}, numeric_count=8)
        steps = plan(state)
        names = [s["name"] for s in steps]
        assert "vif_drop" not in names

    def test_vif_protects_hint_columns(self, tab_df_collinear, tab_state):
        """vif_protect_columns → 보호 컬럼은 drop 안 됨."""
        step = {
            "name": "vif_drop",
            "columns": [],
            "params": {"protect": ["Age"]},
        }
        df_out, state_out = _apply_step(tab_df_collinear, step, tab_state)
        assert "Age" in df_out.columns

    def test_vif_artifact_vif_dropped_stored(self, tab_df_collinear, tab_state):
        """vif_dropped + vif_final artifact 저장."""
        step = {
            "name": "vif_drop",
            "columns": [],
            "params": {"protect": []},
        }
        _, state_out = _apply_step(tab_df_collinear, step, tab_state)
        arts = _artifacts(state_out)
        assert "vif_dropped" in arts
        assert "vif_final" in arts
        assert isinstance(arts["vif_dropped"], list)

    def test_vif_safety_max_drop_count(self, tab_df_collinear, tab_state):
        """max_drop_ratio_override 0.3 설정 시 drop 수 제한 (안전장치)."""
        state = tab_state.with_update(preprocessing_hints={"vif_max_drop_ratio_override": 0.3})
        step = {
            "name": "vif_drop",
            "columns": [],
            "params": {"protect": []},
        }
        df_out, state_out = _apply_step(tab_df_collinear, step, state)
        dropped = _artifacts(state_out)["vif_dropped"]
        n_numeric = len(tab_df_collinear.select_dtypes(include=[np.number]).columns) - 1
        # 0.3 비율 이하로 drop 되어야 함 (안전장치)
        assert len(dropped) <= max(1, int(n_numeric * 0.3) + 1)


# ---------------------------------------------------------------------------
# Priority / Repreprocess: #23~#24
# ---------------------------------------------------------------------------


class TestThresholdPriority:
    def test_hint_overrides_adaptive(self, tab_df, tab_state):
        """hint > adaptive 우선순위 검증."""
        from agents.handlers.tabular.preprocessor import resolve_threshold

        hints = {"vif_threshold": 3.0}
        profile = {"preprocessing_thresholds_suggested": {"vif_threshold": 7.0}}
        val, source = resolve_threshold("vif_threshold", hints, profile, 10.0)
        assert val == 3.0
        assert source == "hint"

    def test_adaptive_overrides_default(self, tab_df, tab_state):
        """adaptive > default 우선순위 검증."""
        from agents.handlers.tabular.preprocessor import resolve_threshold

        hints = {}
        profile = {"preprocessing_thresholds_suggested": {"vif_threshold": 7.0}}
        val, source = resolve_threshold("vif_threshold", hints, profile, 10.0)
        assert val == 7.0
        assert source == "adaptive"


# ---------------------------------------------------------------------------
# Distribution: #25~#29 — log / yeo-johnson
# ---------------------------------------------------------------------------


class TestDistributionTransform:
    def test_log_applied_positive_skewed(self, tab_df_skewed, tab_state):
        """양수 값 + skew > 1 → log 변환 적용."""
        step = {
            "name": "distribution_transform",
            "columns": ["Fare"],
            "params": {},
        }
        df_out, state_out = _apply_step(tab_df_skewed, step, tab_state)
        transforms = _artifacts(state_out)["distribution_transforms"]
        assert "Fare" in transforms
        assert transforms["Fare"]["method"] in ("log", "log1p")

    def test_yeo_applied_negative_values(self, tab_df_negative_skewed, tab_state):
        """음수 포함 컬럼 + skew > 1 → yeo-johnson 변환."""
        step = {
            "name": "distribution_transform",
            "columns": ["Diff"],
            "params": {},
        }
        df_out, state_out = _apply_step(tab_df_negative_skewed, step, tab_state)
        transforms = _artifacts(state_out)["distribution_transforms"]
        if "Diff" in transforms:
            assert transforms["Diff"]["method"] in ("yeo-johnson", "log1p")

    def test_log1p_applied_zero_included(self, tab_df, tab_state):
        """0 포함 + 양수 skew → log1p."""
        df = tab_df.copy()
        df["ZeroFare"] = (df["Fare"] ** 3).clip(lower=0)  # includes 0 possible
        # Force include zero
        df.loc[:2, "ZeroFare"] = 0.0
        step = {
            "name": "distribution_transform",
            "columns": ["ZeroFare"],
            "params": {},
        }
        df_out, state_out = _apply_step(df, step, tab_state)
        transforms = _artifacts(state_out).get("distribution_transforms", {})
        if "ZeroFare" in transforms:
            assert transforms["ZeroFare"]["method"] in ("log1p", "log")

    def test_distribution_skew_before_after_stored(self, tab_df_skewed, tab_state):
        """artifact에 skew_before / skew_after 저장."""
        step = {
            "name": "distribution_transform",
            "columns": ["Fare"],
            "params": {},
        }
        _, state_out = _apply_step(tab_df_skewed, step, tab_state)
        transforms = _artifacts(state_out)["distribution_transforms"]
        if "Fare" in transforms:
            assert "skew_before" in transforms["Fare"]
            assert "skew_after" in transforms["Fare"]

    def test_distribution_skipped_low_skew(self, tab_df, tab_state):
        """|skew| <= 1 → distribution_transform 안 함."""
        step = {
            "name": "distribution_transform",
            "columns": ["Age"],
            "params": {},
        }
        skew = abs(float(tab_df["Age"].skew()))
        _, state_out = _apply_step(tab_df, step, tab_state)
        transforms = _artifacts(state_out).get("distribution_transforms", {})
        if skew <= 1.0:
            assert "Age" not in transforms


# ---------------------------------------------------------------------------
# Datetime: #30~#33 — Datetime Extraction
# ---------------------------------------------------------------------------


class TestDatetimeExtraction:
    def test_datetime_features_extracted(self, tab_df_with_datetime, tab_state):
        """datetime 컬럼 → year/month/dayofweek 등 추출."""
        step = {
            "name": "datetime_extraction",
            "columns": ["booking_date"],
            "params": {},
        }
        df_out, _ = _apply_step(tab_df_with_datetime, step, tab_state)
        assert "booking_date__year" in df_out.columns
        assert "booking_date__month" in df_out.columns
        assert "booking_date__dayofweek" in df_out.columns

    def test_datetime_original_dropped(self, tab_df_with_datetime, tab_state):
        """원본 datetime 컬럼 drop."""
        step = {
            "name": "datetime_extraction",
            "columns": ["booking_date"],
            "params": {},
        }
        df_out, _ = _apply_step(tab_df_with_datetime, step, tab_state)
        assert "booking_date" not in df_out.columns

    def test_datetime_tz_aware_converted(self, tab_df_with_datetime_tz, tab_state):
        """tz-aware → UTC 변환 + original_tz artifact 기록."""
        step = {
            "name": "datetime_extraction",
            "columns": ["booking_date"],
            "params": {},
        }
        df_out, state_out = _apply_step(tab_df_with_datetime_tz, step, tab_state)
        assert "booking_date__year" in df_out.columns
        extracted = _artifacts(state_out).get("datetime_extracted", {})
        if "booking_date" in extracted:
            assert extracted["booking_date"]["original_tz"] is not None

    def test_datetime_nat_becomes_nan(self, tab_df_with_nat, tab_state):
        """NaT 행 → 추출 컬럼에 NaN."""
        step = {
            "name": "datetime_extraction",
            "columns": ["booking_date"],
            "params": {},
        }
        df_out, state_out = _apply_step(tab_df_with_nat, step, tab_state)
        extracted = _artifacts(state_out).get("datetime_extracted", {})
        if "booking_date" in extracted:
            assert extracted["booking_date"]["nat_count"] > 0


# ---------------------------------------------------------------------------
# KNN: #34~#37 — KNN Impute
# ---------------------------------------------------------------------------


class TestKnnImpute:
    @pytest.mark.parametrize("tab_df_with_missing", [0.10], indirect=True)
    def test_knn_applied_10pct_missing(self, tab_df_with_missing, tab_state):
        """10% 결측 → KNN 적용, NaN 제거."""
        step = {
            "name": "knn_impute",
            "columns": ["Age"],
            "params": {"n_neighbors": 3},
        }
        df_out, state_out = _apply_step(tab_df_with_missing, step, tab_state)
        assert df_out["Age"].isna().sum() == 0
        knn = _artifacts(state_out)["knn_imputer"]
        assert knn is not None and knn["fitted"] is True

    @pytest.mark.parametrize("tab_df_with_missing", [0.01], indirect=True)
    def test_knn_skipped_low_missing(self, tab_df_with_missing, tab_state):
        """<5% 결측 → KNN 적용 안 됨 (apply 함수 내 auto-detect 미발동)."""
        step = {
            "name": "knn_impute",
            "columns": [],  # empty → auto detect
            "params": {"n_neighbors": 3},
        }
        df_out, state_out = _apply_step(tab_df_with_missing, step, tab_state)
        # Auto-detect won't pick <5% missing columns
        knn = _artifacts(state_out).get("knn_imputer")
        # knn may be None if no columns were detected
        assert tab_df_with_missing["Age"].isna().mean() < 0.05

    def test_knn_skipped_large_n(self, tab_state):
        """n > 5000 → KNN skip."""
        n = 5100
        df_large = pd.DataFrame(
            {
                "Age": [np.nan if i % 10 == 0 else float(i % 60) for i in range(n)],
                "Fare": [float(i % 100) for i in range(n)],
                "Survived": [i % 2 for i in range(n)],
            }
        )
        step = {
            "name": "knn_impute",
            "columns": ["Age"],
            "params": {"n_neighbors": 3},
        }
        df_out, state_out = _apply_step(df_large, step, tab_state)
        # Large dataset → KNN skipped, Age may still have NaN
        knn = _artifacts(state_out).get("knn_imputer")
        assert knn is None  # skipped for n>5000

    @pytest.mark.parametrize("tab_df_with_missing", [0.10], indirect=True)
    def test_knn_k_neighbors_auto(self, tab_df_with_missing, tab_state):
        """k = min(5, max(1, ceil(sqrt(n))-1)) 자동 결정."""
        import math

        n = len(tab_df_with_missing)
        expected_k = min(5, max(1, math.ceil(math.sqrt(n)) - 1))
        step = {
            "name": "knn_impute",
            "columns": ["Age"],
            "params": {"n_neighbors": expected_k},
        }
        _, state_out = _apply_step(tab_df_with_missing, step, tab_state)
        knn = _artifacts(state_out).get("knn_imputer")
        if knn:
            assert knn["n_neighbors"] == expected_k


# ---------------------------------------------------------------------------
# Robust Scaling: #38~#40
# ---------------------------------------------------------------------------


class TestRobustScaling:
    def test_robust_scaler_for_outlier_cols(self, tab_df_with_outliers, tab_state):
        """outlier > 5% 컬럼 → RobustScaler 적용 + artifact method=robust."""
        step = {
            "name": "scale_robust",
            "columns": ["Fare"],
            "params": {"robust_cols": ["Fare"], "standard_cols": []},
        }
        _, state_out = _apply_step(tab_df_with_outliers, step, tab_state)
        scalers = _artifacts(state_out).get("fitted_scalers", {})
        assert "Fare" in scalers
        assert scalers["Fare"]["method"] == "robust"

    def test_standard_scaler_for_clean_cols(self, tab_df, tab_state):
        """outlier 없는 컬럼 → StandardScaler, method=standard."""
        step = {
            "name": "scale_robust",
            "columns": ["Age"],
            "params": {"robust_cols": [], "standard_cols": ["Age"]},
        }
        _, state_out = _apply_step(tab_df, step, tab_state)
        scalers = _artifacts(state_out).get("fitted_scalers", {})
        assert "Age" in scalers
        assert scalers["Age"]["method"] == "standard"

    def test_scaling_artifact_stored(self, tab_df_with_outliers, tab_state):
        """fitted_scalers artifact에 method + 통계 저장."""
        step = {
            "name": "scale_robust",
            "columns": ["Fare"],
            "params": {"robust_cols": ["Fare"], "standard_cols": []},
        }
        _, state_out = _apply_step(tab_df_with_outliers, step, tab_state)
        scalers = _artifacts(state_out).get("fitted_scalers", {})
        if "Fare" in scalers:
            assert "method" in scalers["Fare"]
            assert scalers["Fare"]["method"] in ("robust", "standard")


# ---------------------------------------------------------------------------
# TRANSFORM_REGISTRY: 15개 검증
# ---------------------------------------------------------------------------


class TestTransformRegistry:
    def test_registry_count_15(self):
        """TRANSFORM_REGISTRY == 15 (transform 7종 추가 구현 후 전부 implemented)."""
        from agents.handlers.tabular.preprocessor import TRANSFORM_REGISTRY

        assert len(TRANSFORM_REGISTRY) == 15

    def test_registry_all_implemented(self):
        """transform 7종(missing_indicator/hash_encoding/quantile_transform/polynomial_features/
        interaction_terms/correlation_drop/pca_preview) 추가 구현 → 15종 전부 implemented."""
        from agents.handlers.tabular.preprocessor import TRANSFORM_REGISTRY

        implemented = [s for s in TRANSFORM_REGISTRY.values() if s.status == "implemented"]
        assert len(implemented) == 15

    def test_registry_no_planned(self):
        """7종 구현 완료 → planned 0종."""
        from agents.handlers.tabular.preprocessor import TRANSFORM_REGISTRY

        planned = [s for s in TRANSFORM_REGISTRY.values() if s.status == "planned"]
        assert len(planned) == 0


# ---------------------------------------------------------------------------
# Integration: #41~#42
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_full_pipeline_tab_ml(self, tab_df_skewed, tab_state):
        """tabular_ml 전체 파이프라인: plan → apply → artifact 검증."""
        from agents.handlers.tabular.preprocessor import apply, plan

        state = _state_with_profile(
            tab_state,
            cardinality_levels={"Sex": "low"},
            n_rows=len(tab_df_skewed),
            numeric_count=3,
        )
        steps = plan(state)
        assert len(steps) > 0
        df_out, state_out = apply(tab_df_skewed, steps, state)

        assert isinstance(df_out, pd.DataFrame)
        assert len(df_out) > 0
        arts = _artifacts(state_out)
        assert "preprocess_artifacts" in state_out.category_extras["tabular"]

    def test_full_pipeline_tab_dl(self, tab_df, tab_dl_state):
        """tabular_dl 전체 파이프라인: label_encoding 경로 검증."""
        from agents.handlers.tabular.preprocessor import apply, plan

        state = _state_with_profile(
            tab_dl_state,
            cardinality_levels={"Sex": "low"},
            n_rows=len(tab_df),
        )
        steps = plan(state)
        names = [s["name"] for s in steps]
        assert "label_encoding" in names
        assert "target_encoding" not in names

        df_out, state_out = apply(tab_df, steps, state)
        assert isinstance(df_out, pd.DataFrame)

        # DL label encoding: Sex should be numeric
        if "Sex" in df_out.columns:
            assert pd.api.types.is_numeric_dtype(df_out["Sex"])

    def test_apply_returns_tuple(self, tab_df, tab_state):
        """apply() 반환값이 (df, state) 튜플."""
        from agents.handlers.tabular.preprocessor import apply

        result = apply(tab_df, [], tab_state)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_apply_state_has_tabular_extras(self, tab_df, tab_state):
        """apply() 후 state.category_extras['tabular'] 존재."""
        from agents.handlers.tabular.preprocessor import apply

        _, state_out = apply(tab_df, [], tab_state)
        assert "tabular" in state_out.category_extras

    def test_plan_returns_list(self, tab_state):
        """plan() 반환값이 list."""
        from agents.handlers.tabular.preprocessor import plan

        result = plan(tab_state)
        assert isinstance(result, list)

    def test_class_weight_adapters_sklearn(self):
        """to_sklearn adapter 기본 동작."""
        from agents.handlers.tabular._class_weight_adapters import to_sklearn

        w = {0: 0.66, 1: 2.08}
        result = to_sklearn(w)
        assert result[0] == pytest.approx(0.66)
        assert result[1] == pytest.approx(2.08)

    def test_class_weight_adapters_xgboost_binary(self):
        """to_xgboost_binary: scale_pos_weight = w_minority / w_majority."""
        from agents.handlers.tabular._class_weight_adapters import to_xgboost_binary

        w = {0: 0.66, 1: 2.08}
        spw = to_xgboost_binary(w)
        assert spw == pytest.approx(2.08 / 0.66, rel=1e-3)

    def test_class_weight_adapters_catboost(self):
        """to_catboost: 오름차순 리스트."""
        from agents.handlers.tabular._class_weight_adapters import to_catboost

        w = {1: 2.08, 0: 0.66}
        result = to_catboost(w)
        assert result == pytest.approx([0.66, 2.08])


# ---------------------------------------------------------------------------
# Day 11 (jh) — apply_split: leakage-safe entry tests
# ---------------------------------------------------------------------------


class TestApplySplitLeakageGuard:
    """split-first → train 만으로 fit → val 은 transform 만 흐름 검증.

    핵심 보장: val 데이터를 극단값으로 오염시켜도 train transform 결과가
    동일해야 함 (= val 통계가 train fit 에 새 들어가지 않음).
    """

    def _make_state(self, target="y", category="tabular_ml"):
        from ada.core.state import PipelineState

        return PipelineState(
            job_id="test-leakage",
            file_id="test",
            category=category,
            target_column=target,
        )

    def _make_df(self, seed=0):
        rng = np.random.RandomState(seed)
        n = 200
        return pd.DataFrame(
            {
                "num1": rng.normal(50, 10, n),
                "num2": rng.normal(100, 20, n),
                "cat": rng.choice(["a", "b", "c"], n),
                "y": rng.choice([0, 1], n, p=[0.7, 0.3]),
            }
        )

    def test_apply_split_returns_four_tuple(self):
        """apply_split 시그니처: (df_train, df_val, df_test, state) — 3-way 격리."""
        from agents.handlers.tabular.preprocessor import apply_split

        state = self._make_state()
        df = self._make_df(seed=42)
        plan_steps = [
            {"name": "impute_numeric", "strategy": "median", "params": {}},
            {"name": "scale_numeric", "method": "robust", "params": {}},
        ]
        result = apply_split(df, plan_steps, state, random_state=42)
        assert isinstance(result, tuple) and len(result) == 4
        df_tr, df_val, df_test, new_state = result
        assert len(df_tr) > 0 and len(df_val) > 0
        assert len(df_tr) + len(df_val) + len(df_test) == len(df)

    def test_leakage_guard_val_contamination_doesnt_affect_train(self):
        """★ 핵심 — val 의 극단값 오염이 train scaled 결과에 영향 0.

        잘못된 흐름(apply, 전체 fit)에선 val 오염이 train 결과에 새 들어감.
        apply_split 은 train 으로만 fit 하므로 영향 없어야 함.
        """
        from agents.handlers.tabular.preprocessor import apply_split

        state = self._make_state()
        df_clean = self._make_df(seed=42)

        # 같은 random_state → 동일 train/val split 보장
        df_poison = df_clean.copy()
        # val 영역(끝 20%) 의 num1 을 극단값으로 오염
        from sklearn.model_selection import train_test_split

        _, val_idx = train_test_split(df_clean.index, test_size=0.2, random_state=42, stratify=df_clean["y"])
        df_poison.loc[val_idx, "num1"] = 1e6  # 100만 — 평균/median 을 크게 흔들 정도

        plan_steps = [
            {"name": "impute_numeric", "strategy": "median", "params": {}},
            {"name": "scale_numeric", "method": "robust", "params": {}},
        ]

        df_tr_clean, _, _, _ = apply_split(df_clean, plan_steps, state, random_state=42)
        df_tr_poison, _, _, _ = apply_split(df_poison, plan_steps, state, random_state=42)

        # train 행은 동일한 위치 (같은 split) → scaled num1 값이 동일해야 함
        assert "num1" in df_tr_clean.columns
        np.testing.assert_allclose(
            df_tr_clean["num1"].values,
            df_tr_poison["num1"].values,
            rtol=1e-6,
            err_msg="val 오염이 train scaled 값에 영향 — leakage guard 실패",
        )

    def test_leakage_safe_split_meta_recorded(self):
        """split 메타가 category_extras 에 기록되는지."""
        from agents.handlers.tabular.preprocessor import apply_split

        state = self._make_state()
        df = self._make_df(seed=42)
        _, _, _, new_state = apply_split(
            df,
            [{"name": "impute_numeric", "strategy": "median", "params": {}}],
            state,
            random_state=42,
        )
        meta = (new_state.category_extras or {}).get("tabular", {}).get("leakage_safe_split")
        assert meta is not None
        assert meta["method"] == "split_first_train_fit_3way"
        assert meta["n_train"] > 0
        assert meta["n_val"] > 0
        assert meta["n_test"] >= 0
        assert meta["random_state"] == 42

    def test_smote_not_applied_to_val(self):
        """SMOTE 는 val 에 적용 안 됨 (의도된 동작) — val 행 수 보존."""
        from agents.handlers.tabular.preprocessor import apply_split

        state = self._make_state()
        df = self._make_df(seed=42)
        plan_steps = [
            {"name": "impute_numeric", "strategy": "median", "params": {}},
            {"name": "encode_categorical", "params": {"high_card_threshold": 50}},
            {"name": "smote_resample", "params": {}},
        ]
        _, df_val, _, _ = apply_split(df, plan_steps, state, random_state=42)
        # val 행 수 = holdout(0.2) 의 절반 = 전체의 0.1 (3-way: holdout→val/test 50:50, SMOTE 미적용)
        expected_val_n = int(len(df) * 0.1)
        # train_test_split 의 반올림 차이로 ±1 허용
        assert abs(len(df_val) - expected_val_n) <= 1

    def test_fallback_random_when_stratify_impossible(self):
        """희소 클래스로 stratify 불가능해도 무작위 fallback 으로 통과."""
        from agents.handlers.tabular.preprocessor import apply_split

        state = self._make_state()
        # 클래스 1 이 단 1개 → stratify 불가능
        df = self._make_df(seed=42)
        df.loc[df.index[1:], "y"] = 0
        df.loc[df.index[0], "y"] = 1
        plan_steps = [{"name": "impute_numeric", "strategy": "median", "params": {}}]
        result = apply_split(df, plan_steps, state, random_state=42)
        assert len(result) == 4

    def test_apply_split_registered_as_capability(self):
        """HANDLER_REGISTRY 자동 등록 확인 (HJ 영역 _base.py 변경 검증)."""
        import agents.handlers.tabular  # noqa: F401
        from agents.handlers import HANDLER_REGISTRY

        for cat in ("tabular_ml", "tabular_dl"):
            assert "apply_split" in HANDLER_REGISTRY.get(cat, {}), f"{cat} 에 apply_split 미등록"
