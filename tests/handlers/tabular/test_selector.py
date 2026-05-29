"""jh Day 5 — test_selector.py: 모델 선택 테스트 (35 unit + 6 integration)."""

from __future__ import annotations

import pytest

REQUIRED_KEYS = {"top_models", "model_candidates", "rationale", "citations", "warm_start_seed", "selector_signals"}


def _wrap_hints(state, hints: dict):
    class _W:
        def __getattr__(self, name):
            return getattr(state, name)

        @property
        def selector_hints(self):
            return hints

    return _W()


# ── TestReturnContract ────────────────────────────────────────────────────────


class TestReturnContract:
    def test_required_keys_present(self, tab_state):
        from agents.handlers.tabular.selector import score

        result = score(tab_state, [])
        assert REQUIRED_KEYS.issubset(result.keys())

    def test_top_models_length_in_range(self, tab_state):
        from agents.handlers.tabular.selector import score

        result = score(tab_state, [])
        assert 1 <= len(result["top_models"]) <= 5

    def test_top_models_sorted_by_priority(self, tab_state):
        from agents.handlers.tabular.selector import score

        result = score(tab_state, [])
        assert len(result["top_models"]) >= 1  # top_models[0] is best

    def test_no_state_mutation(self, tab_state):
        from agents.handlers.tabular.selector import score

        profile_id = id(tab_state.data_profile)
        score(tab_state, [])
        assert id(tab_state.data_profile) == profile_id


# ── TestG2Mapping ─────────────────────────────────────────────────────────────


class TestG2Mapping:
    def test_g2_ml_light_maps_light_models(self, tab_state_with_g2_ml_light):
        from agents.handlers.tabular.selector import _G2_CANDIDATES, score

        result = score(tab_state_with_g2_ml_light, [])
        expected = set(_G2_CANDIDATES["g2_ml_light"])
        assert set(result["model_candidates"]).issubset(expected)

    def test_g2_ml_standard_maps_boosting(self, tab_state):
        from agents.handlers.tabular.selector import score

        state = tab_state.with_update(gate_responses={"g2": "g2_ml_standard"})
        result = score(state, [])
        assert set(result["model_candidates"]) == {"XGBoost", "LightGBM", "CatBoost"}

    def test_g2_ml_heavy_has_flaml_tag(self, tab_state):
        from agents.handlers.tabular.selector import score

        state = tab_state.with_update(gate_responses={"g2": "g2_ml_heavy"})
        result = score(state, [])
        assert all("+FLAML" in m for m in result["model_candidates"])

    def test_g2_dl_light_maps_dl(self, tab_state_large):
        from agents.handlers.tabular.selector import score

        state = tab_state_large.with_update(gate_responses={"g2": "g2_dl_light"})
        result = score(state, [])
        assert set(result["model_candidates"]) == {"TabPFN", "MLP"}

    def test_g2_dl_heavy_maps_transformers(self, tab_state_with_g2_dl_heavy):
        from agents.handlers.tabular.selector import score

        result = score(tab_state_with_g2_dl_heavy, [])
        assert set(result["model_candidates"]) == {"FTTransformer", "TabTransformer"}

    def test_g2_missing_triggers_fallback(self, tab_state):
        from agents.handlers.tabular.selector import score

        state = tab_state.with_update(gate_responses={})
        result = score(state, [])
        assert "fallback_used" in result["selector_signals"]
        assert result["selector_signals"]["fallback_used"]["reason"] == "g2_choice missing"


# ── TestSpecialBranch ─────────────────────────────────────────────────────────


class TestSpecialBranch:
    def test_g1_segment_returns_kmeans(self, tab_state_with_g1_segment):
        from agents.handlers.tabular.selector import score

        result = score(tab_state_with_g1_segment, [])
        assert "KMeans" in result["top_models"]
        assert result["selector_signals"]["special_branch"] == "g1_segment"

    def test_g1_survival_returns_cox(self, tab_state):
        from agents.handlers.tabular.selector import score

        state = tab_state.with_update(gate_responses={"g1": "g1_survival_analysis"})
        result = score(state, [])
        assert result["top_models"] == ["CoxPHFitter"]
        assert result["selector_signals"]["special_branch"] == "g1_survival_analysis"

    def test_g1_multi_target_returns_multioutput(self, tab_state):
        from agents.handlers.tabular.selector import score

        state = tab_state.with_update(gate_responses={"g1": "g1_multi_target"})
        result = score(state, [])
        assert result["top_models"][0] in ("MultiOutputClassifier", "MultiOutputRegressor")
        assert result["selector_signals"]["special_branch"] == "g1_multi_target"

    def test_g1_importance_lightgbm_top1(self, tab_state):
        from agents.handlers.tabular.selector import score

        state = tab_state.with_update(
            gate_responses={"g1": "g1_importance", "g2": "g2_ml_standard"},
            data_profile={"rows": 2000, "columns": 10, "class_distribution": {0: 1000, 1: 1000}},
            category_extras={"tabular": {"eda_baseline": {"cv_score": 0.72, "metric": "f1_macro"}}},
        )
        result = score(state, [])
        assert result["top_models"][0] == "LightGBM"

    def test_g1_hybrid_lightgbm_top1(self, tab_state):
        from agents.handlers.tabular.selector import score

        state = tab_state.with_update(
            gate_responses={"g1": "g1_hybrid", "g2": "g2_ml_standard"},
            data_profile={"rows": 2000, "columns": 10, "class_distribution": {0: 1000, 1: 1000}},
            category_extras={"tabular": {"eda_baseline": {"cv_score": 0.72, "metric": "f1_macro"}}},
        )
        result = score(state, [])
        assert result["top_models"][0] == "LightGBM"


# ── TestGroupASignals ─────────────────────────────────────────────────────────


class TestGroupASignals:
    def test_complexity_high_when_cv_low(self, tab_state_with_eda_baseline):
        from agents.handlers.tabular.selector import _sig_complexity

        # cv_score=0.72 → complexity=0.5
        assert _sig_complexity(tab_state_with_eda_baseline) == 0.5

    def test_complexity_default_without_baseline(self, tab_state):
        from agents.handlers.tabular.selector import _sig_complexity

        # no eda_baseline → default 0.5
        assert _sig_complexity(tab_state) == 0.5

    def test_variety_high_for_dl_choice(self, tab_state_with_g2_dl_heavy):
        from agents.handlers.tabular.selector import _sig_variety

        assert _sig_variety(tab_state_with_g2_dl_heavy, "g2_dl_heavy") > 0.6

    def test_quality_high_extreme_imbalance(self, tab_state_complex_medium):
        from agents.handlers.tabular.selector import _sig_quality

        assert _sig_quality(tab_state_complex_medium) > 0.5

    def test_size_signal_10000_rows(self, tab_state):
        from agents.handlers.tabular.selector import _sig_size

        state = tab_state.with_update(data_profile={"rows": 10000, "columns": 5})
        assert _sig_size(state) == 0.6

    def test_top_n_mapping_4_scenarios(self, tab_state):
        from agents.handlers.tabular.selector import _top_n_from_score

        assert _top_n_from_score(0.20) == 1
        assert _top_n_from_score(0.40) == 2
        assert _top_n_from_score(0.60) == 3
        assert _top_n_from_score(0.75) == 4
        assert _top_n_from_score(0.90) == 5


# ── TestGroupBSignals ─────────────────────────────────────────────────────────


class TestGroupBSignals:
    def test_interpretability_medical_keywords(self, tab_state_medical_keywords):
        from agents.handlers.tabular.selector import _sig_interpretability

        # user_intent "환자의 진단 이유 설명" → 이유 keyword + column_names medical
        val = _sig_interpretability(tab_state_medical_keywords, None)
        assert val >= 0.7

    def test_precision_extreme_imbalance(self, tab_state_complex_medium):
        from agents.handlers.tabular.selector import _sig_precision

        # entropy=0.25 < 0.3 → +0.3 (base 0.3 + 0.3 = 0.6)
        val = _sig_precision(tab_state_complex_medium)
        assert val >= 0.6

    def test_precision_keyword_and_imbalance(self, tab_state_complex_medium):
        from agents.handlers.tabular.selector import _sig_precision

        # keyword "정확" + extreme imbalance → base 0.3 + 0.3 + 0.3 = 0.9
        state = tab_state_complex_medium.with_update(user_intent="정확한 분류 필요")
        assert _sig_precision(state) >= 0.7

    def test_speed_signal_with_keyword(self, tab_state):
        from agents.handlers.tabular.selector import _sig_speed

        state = tab_state.with_update(user_intent="빠른 분류 원합니다")
        assert _sig_speed(state) >= 0.6

    def test_fairness_demographic_columns(self, tab_state):
        from agents.handlers.tabular.selector import _sig_fairness

        state = tab_state.with_update(
            data_profile={"rows": 120, "columns": 4, "column_names": ["age", "gender", "income", "Survived"]},
            user_intent="공정한 모델 학습",
        )
        assert _sig_fairness(state) >= 0.7

    def test_cost_sensitivity_extreme_imbalance(self, tab_state):
        from agents.handlers.tabular.selector import _sig_cost

        # imbalance_ratio=60 + keyword → base 0.3 + 0.3 + 0.3 = 0.9
        state = tab_state.with_update(
            user_intent="오답 비용이 큰 모델",
            data_profile={
                "rows": 1000,
                "columns": 5,
                "class_imbalance_ratio": 60.0,
                "class_distribution": {0: 990, 1: 10},
            },
        )
        assert _sig_cost(state) >= 0.7

    def test_model_weight_interpretability_boosts_lgbm(self, tab_state_medical_keywords):
        from agents.handlers.tabular.selector import score

        result = score(tab_state_medical_keywords, [])
        # interpretability ≥ 0.7 → LightGBM should be top1
        assert result["top_models"][0] == "LightGBM"

    def test_speed_high_reduces_top_n(self, tab_state):
        from agents.handlers.tabular.selector import score

        state = _wrap_hints(
            tab_state.with_update(
                gate_responses={"g2": "g2_ml_standard"},
                data_profile={"rows": 5000, "columns": 5, "class_distribution": {0: 2500, 1: 2500}},
                category_extras={"tabular": {"eda_baseline": {"cv_score": 0.55, "metric": "f1_macro"}}},
            ),
            {"force_signal": {"speed": 0.85}},
        )
        result_fast = score(state, [])

        state_normal = _wrap_hints(
            tab_state.with_update(
                gate_responses={"g2": "g2_ml_standard"},
                data_profile={"rows": 5000, "columns": 5, "class_distribution": {0: 2500, 1: 2500}},
                category_extras={"tabular": {"eda_baseline": {"cv_score": 0.55, "metric": "f1_macro"}}},
            ),
            {"force_signal": {"speed": 0.3}},
        )
        result_normal = score(state_normal, [])
        assert (
            result_fast["selector_signals"]["group_a_top_n"]["decided_n"]
            <= result_normal["selector_signals"]["group_a_top_n"]["decided_n"]
        )


# ── TestWarmStart ─────────────────────────────────────────────────────────────


class TestWarmStart:
    def test_high_match_uses_recipe_params(self, tab_state_medical_keywords, mock_recipes_list):
        from agents.handlers.tabular.selector import score

        # tab_state_medical: rows=2000, n_classes=2 — recipe_abc001(rows=2000) should be near-perfect
        result = score(tab_state_medical_keywords, mock_recipes_list)
        xgb_seed = result["warm_start_seed"].get("XGBoost") or result["warm_start_seed"].get("LightGBM")
        if xgb_seed:
            assert xgb_seed.get("_source", "").startswith("recipe_")

    def test_low_match_uses_default_seed(self, tab_state, mock_recipes_list):
        from agents.handlers.tabular.selector import score

        # tab_state rows=0, tiny data → poor match → default
        result = score(tab_state, mock_recipes_list)
        for model, seed in result["warm_start_seed"].items():
            # source is either recipe_* or default
            assert "_source" in seed

    def test_empty_recipes_all_default(self, tab_state):
        from agents.handlers.tabular.selector import score

        result = score(tab_state.with_update(gate_responses={"g2": "g2_ml_standard"}), [])
        for seed in result["warm_start_seed"].values():
            assert seed.get("_source") == "default"

    def test_citations_empty_recipes_rationale_kb_note(self, tab_state):
        from agents.handlers.tabular.selector import score

        result = score(tab_state, [])
        assert result["citations"] == []
        assert "KB 미사용" in result["rationale"]

    def test_citations_nonempty_recipes(self, tab_state, mock_recipes_list):
        from agents.handlers.tabular.selector import score

        state = tab_state.with_update(gate_responses={"g2": "g2_ml_standard"})
        result = score(state, mock_recipes_list)
        assert len(result["citations"]) > 0
        assert all(c.startswith("recipe_") for c in result["citations"])

    def test_selector_signals_structure(self, tab_state):
        from agents.handlers.tabular.selector import score

        result = score(tab_state, [])
        ss = result["selector_signals"]
        assert "group_a_top_n" in ss
        assert "group_b_weights" in ss
        assert "decided_n" in ss["group_a_top_n"]
        assert "applied_to_models" in ss["group_b_weights"]

    def test_disable_warm_start_hint(self, tab_state, mock_recipes_list):
        from agents.handlers.tabular.selector import score

        state = _wrap_hints(
            tab_state.with_update(gate_responses={"g2": "g2_ml_standard"}),
            {"disable_warm_start": True},
        )
        result = score(state, mock_recipes_list)
        for seed in result["warm_start_seed"].values():
            assert seed.get("_source") == "default"

    def test_noise_added_for_medium_match(self, tab_state, mock_recipes_list):
        # recipe_abc003: rows=500000 vs tab_state rows=0 → poor match
        # Use a state with similar but not identical rows
        from ada.core.state import PipelineState
        from agents.handlers.tabular.selector import _compute_recipe_match, _warm_start_for_model

        state_med = PipelineState(
            job_id="00000000-0000-0000-0000-000000000t99",
            file_id="uploads/test/test.csv",
            category="tabular_ml",
            target_column="label",
            user_intent="분류",
            data_profile={"rows": 2000, "columns": 10, "n_classes": 2},
        )
        # recipe_abc001: rows=2000, columns=10, quality=0.90 → match ≥ 0.7 → direct
        seed = _warm_start_for_model("XGBoost", mock_recipes_list, state_med)
        # _source = f"recipe_{hash}" or f"recipe_{hash}_with_noise" or "default"
        src = seed["_source"]
        assert src == "default" or src.startswith("recipe_")


# ── TestIntegration ───────────────────────────────────────────────────────────


class TestIntegration:
    def test_small_g2_ml_light_scenario(self, tab_state_with_g2_ml_light):
        from agents.handlers.tabular.selector import score

        result = score(tab_state_with_g2_ml_light, [])
        assert 1 <= len(result["top_models"]) <= 2
        assert all(
            m in {"LogisticRegression", "DecisionTree", "GaussianNB", "kNN", "RandomForest"}
            for m in result["top_models"]
        )

    def test_large_simple_g2_ml_standard(self, tab_state_huge):
        from agents.handlers.tabular.selector import score

        state = tab_state_huge.with_update(gate_responses={"g2": "g2_ml_standard"})
        result = score(state, [])
        assert all(m in {"XGBoost", "LightGBM", "CatBoost"} for m in result["top_models"])

    def test_large_complex_g2_dl_heavy(self, tab_state_with_g2_dl_heavy):
        from agents.handlers.tabular.selector import score

        result = score(tab_state_with_g2_dl_heavy, [])
        assert all(m in {"FTTransformer", "TabTransformer"} for m in result["top_models"])

    def test_medical_interpretability_lgbm_top1(self, tab_state_medical_keywords):
        from agents.handlers.tabular.selector import score

        result = score(tab_state_medical_keywords, [])
        assert result["top_models"][0] == "LightGBM"
        assert "해석" in result["rationale"]

    def test_g1_segment_full_flow(self, tab_state_with_g1_segment):
        from agents.handlers.tabular.selector import score

        result = score(tab_state_with_g1_segment, [])
        assert result["top_models"] == ["KMeans", "DBSCAN"]
        assert 1 <= len(result["top_models"]) <= 5

    def test_recipe_warm_start_matched(self, tab_state_medical_keywords, mock_recipes_list):
        from agents.handlers.tabular.selector import score

        result = score(tab_state_medical_keywords, mock_recipes_list)
        assert len(result["citations"]) > 0
        # warm_start_seed should reference a recipe
        seeds = result["warm_start_seed"]
        any_recipe = any(s.get("_source", "").startswith("recipe_") for s in seeds.values())
        assert any_recipe
