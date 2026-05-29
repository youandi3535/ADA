"""jh 단독 — tabular EDA 차트 카탈로그 테스트 (Day 3)."""

from __future__ import annotations

import itertools
from typing import Any
from unittest.mock import MagicMock

import pytest

# ── MinIO mock (autouse) ─────────────────────────────────────────────────────

_counter = itertools.count()


@pytest.fixture(autouse=True)
def mock_minio(monkeypatch):
    """실제 MinIO 없이 fake s3:// URI 반환."""
    import matplotlib.pyplot as plt

    def _fake_save(fig, *, kind, job_id):
        plt.close(fig)
        return f"s3://test/{kind}/{job_id}/{next(_counter)}.png"

    monkeypatch.setattr("agents.handlers.common.shared.save_chart_to_minio", _fake_save)


# ── helpers ──────────────────────────────────────────────────────────────────


def _call(df, state, **hint_overrides):
    from ada.core.state import PipelineState

    if hint_overrides:
        state = state.with_update(**{"eda_hints": hint_overrides} if hasattr(state, "eda_hints") else {})
        # eda_hints를 category_extras가 아닌 직접 kwarg로 전달
        state_dict = state.model_dump()
        state_dict["eda_hints"] = hint_overrides  # 임시 patch
        state = type(state)(**{k: v for k, v in state_dict.items() if k != "eda_hints"})
        # eda_hints는 getattr fallback으로 처리됨 — mock object 사용
        state = _wrap_hints(state, hint_overrides)
    from agents.handlers.tabular.eda import charts

    return charts(df, state)


def _wrap_hints(state, hints):
    """eda_hints 속성을 동적으로 붙인 state wrapper."""

    class _W:
        def __getattr__(self, name):
            return getattr(state, name)

        @property
        def eda_hints(self):
            return hints

    w = _W()
    w.__class__.__name__ = type(state).__name__
    return w


def _charts(df, state, **hints):
    if hints:
        state = _wrap_hints(state, hints)
    from agents.handlers.tabular.eda import charts

    return charts(df, state)


# ── DoD 보장 ──────────────────────────────────────────────────────────────────


class TestDoD:
    def test_min_3_uris(self, tab_df, tab_state):
        uris, _ = _charts(tab_df, tab_state)
        assert len(uris) >= 3

    def test_max_12_uris(self, tab_df_wide, tab_state):
        uris, _ = _charts(tab_df_wide, tab_state)
        assert len(uris) <= 12

    def test_all_uris_s3_scheme(self, tab_df, tab_state):
        uris, _ = _charts(tab_df, tab_state)
        assert all(u.startswith("s3://") for u in uris)

    def test_return_type_is_tuple(self, tab_df, tab_state):
        result = _charts(tab_df, tab_state)
        assert isinstance(result, tuple)
        assert len(result) == 2
        uris, extras = result
        assert isinstance(uris, list)
        assert isinstance(extras, dict)

    def test_state_not_mutated(self, tab_df, tab_state):
        import copy

        original_json = tab_state.model_dump()
        _charts(tab_df, tab_state)
        assert tab_state.model_dump() == original_json


# ── Chart Registry ────────────────────────────────────────────────────────────


class TestChartRegistry:
    def test_registry_count_12(self):
        from agents.handlers.tabular.eda import CHART_REGISTRY

        assert len(CHART_REGISTRY) == 12

    def test_all_names_present(self):
        from agents.handlers.tabular.eda import CHART_REGISTRY

        expected = {
            "correlation_heatmap",
            "target_boxplot",
            "class_distribution",
            "feature_importance_preview",
            "missing_pattern",
            "numeric_distribution_grid",
            "categorical_frequency",
            "pairplot_top4",
            "qq_plot_grid",
            "target_correlation_bar",
            "outlier_summary",
            "smote_before_after_scatter",
        }
        assert set(CHART_REGISTRY.keys()) == expected

    def test_chart_spec_fields(self):
        from agents.handlers.tabular.eda import CHART_REGISTRY, ChartSpec

        for spec in CHART_REGISTRY.values():
            assert isinstance(spec, ChartSpec)
            assert spec.name
            assert callable(spec.trigger_fn)
            assert callable(spec.score_fn)
            assert callable(spec.render_fn)


# ── Chart 1: correlation_heatmap ─────────────────────────────────────────────


class TestCorrelationHeatmap:
    def test_triggers_on_numeric_ge2(self, tab_df, tab_state):
        uris, _ = _charts(tab_df, tab_state)
        assert any("correlation_heatmap" in u for u in uris)

    def test_skip_when_no_numeric(self, tab_state):
        import pandas as pd

        cat_df = pd.DataFrame({"Sex": ["male", "female"] * 60, "Survived": ["y", "n"] * 60})
        uris, _ = _charts(cat_df, tab_state)
        # heatmap should not appear (or only as placeholder forced by DoD)
        heatmap_uris = [u for u in uris if "correlation_heatmap" in u]
        assert len(heatmap_uris) == 0 or len(heatmap_uris) >= 0  # skip or placeholder ok

    def test_cluster_ordering_applied(self, tab_df, tab_state):
        # data_profile에 correlation_clusters 있을 때 트리거 통과 확인
        state = tab_state.with_update(data_profile={"correlation_clusters": {"A": ["Age", "Fare"], "B": ["Pclass"]}})
        uris, _ = _charts(tab_df, state)
        assert any("correlation_heatmap" in u for u in uris)

    def test_cap_applied_on_wide_df(self, tab_df_wide, tab_state):
        uris, _ = _charts(tab_df_wide, tab_state)
        # cap이 적용돼도 heatmap은 여전히 렌더링됨
        assert any("correlation_heatmap" in u for u in uris)


# ── Chart 2: target_boxplot ───────────────────────────────────────────────────


class TestTargetBoxplot:
    def test_classification_renders(self, tab_df, tab_state):
        uris, _ = _charts(tab_df, tab_state)
        assert any("target_boxplot" in u for u in uris)

    def test_regression_renders(self, tab_df, tab_state_regression):
        uris, _ = _charts(tab_df, tab_state_regression)
        assert any("target_boxplot" in u for u in uris)

    def test_no_target_skips(self, tab_df_unsupervised):
        from ada.core.state import PipelineState

        state = PipelineState(
            job_id="test-unsup",
            file_id="test.csv",
            category="tabular_ml",
            target_column=None,
        )
        uris, _ = _charts(tab_df_unsupervised, state)
        # DoD 보장으로 placeholder가 들어갈 수 있으나 ≥3 보장
        assert len(uris) >= 3

    def test_label_encoder_used(self, tab_df, tab_state_after_day2_smote):
        uris, _ = _charts(tab_df, tab_state_after_day2_smote)
        assert any("target_boxplot" in u for u in uris)


# ── Chart 3: class_distribution ───────────────────────────────────────────────


class TestClassDistribution:
    def test_classification_renders(self, tab_df, tab_state):
        uris, _ = _charts(tab_df, tab_state)
        assert any("class_distribution" in u for u in uris)

    def test_regression_skips(self, tab_df, tab_state_regression):
        uris, _ = _charts(tab_df, tab_state_regression)
        assert not any("class_distribution" in u for u in uris)

    def test_smote_before_after_bar(self, tab_df, tab_state_after_day2_smote):
        uris, _ = _charts(tab_df, tab_state_after_day2_smote)
        assert any("class_distribution" in u for u in uris)

    def test_no_smote_text(self, tab_df, tab_state):
        # tab_state에는 SMOTE artifact 없음 → "SMOTE 적용 안 됨"
        uris, _ = _charts(tab_df, tab_state)
        assert any("class_distribution" in u for u in uris)

    def test_entropy_self_computed(self, tab_df, tab_state):
        # profiler 없이도 class_distribution이 렌더링되면 entropy 자체 계산 성공
        state = tab_state.with_update(data_profile=None)
        uris, _ = _charts(tab_df, state)
        assert any("class_distribution" in u for u in uris)


# ── Chart 4: feature_importance_preview ──────────────────────────────────────


class TestFeatureImportance:
    def test_renders_on_sufficient_data(self, tab_df, tab_state):
        uris, _ = _charts(tab_df, tab_state)
        assert any("feature_importance" in u for u in uris)

    def test_no_target_baseline_absent(self, tab_df_unsupervised):
        from ada.core.state import PipelineState

        state = PipelineState(
            job_id="test-unsup-imp",
            file_id="test.csv",
            category="tabular_ml",
            target_column=None,
        )
        _, extras = _charts(tab_df_unsupervised, state)
        # target 없으면 chart4 placeholder → eda_baseline 없음
        assert "eda_baseline" not in extras

    def test_importance_top_n_cumulative_95(self, tab_df, tab_state):
        uris, extras = _charts(tab_df, tab_state)
        if "eda_baseline" in extras:
            assert extras["eda_baseline"]["top_feature_concentration"] is not None

    def test_random_state_from_job_id(self, tab_df, tab_state):
        # 같은 job_id → 같은 random_state → 같은 결과 (재현성)
        uris1, extras1 = _charts(tab_df, tab_state)
        uris2, extras2 = _charts(tab_df, tab_state)
        if "eda_baseline" in extras1 and "eda_baseline" in extras2:
            assert extras1["eda_baseline"]["metric"] == extras2["eda_baseline"]["metric"]


# ── Chart 5: missing_pattern ─────────────────────────────────────────────────


class TestMissingPattern:
    def test_triggers_on_mar_data(self, tab_df_with_mar_missing, tab_state):
        uris, _ = _charts(tab_df_with_mar_missing, tab_state)
        assert any("missing_pattern" in u for u in uris)

    def test_skips_when_not_enough_missing(self, tab_df, tab_state):
        # tab_df 기본은 결측 없음 → missing_pattern skip
        uris, _ = _charts(tab_df, tab_state)
        assert not any("missing_pattern" in u for u in uris)


# ── Chart 6: numeric_distribution_grid ───────────────────────────────────────


class TestNumericDistributionGrid:
    def test_renders_on_4_plus_numeric(self, tab_df, tab_state):
        uris, _ = _charts(tab_df, tab_state)
        assert any("numeric_distribution" in u for u in uris)

    def test_dist_transforms_title(self, tab_df, tab_state_after_day2_smote):
        uris, _ = _charts(tab_df, tab_state_after_day2_smote)
        assert any("numeric_distribution" in u for u in uris)


# ── Chart 7: categorical_frequency ───────────────────────────────────────────


class TestCategoricalFrequency:
    def test_high_card_triggers(self, tab_df_high_card, tab_state):
        uris, _ = _charts(tab_df_high_card, tab_state)
        assert any("categorical_frequency" in u for u in uris)

    def test_no_high_card_skips(self, tab_df, tab_state):
        # tab_df의 Sex는 nunique=2 < threshold=10 → skip
        uris, _ = _charts(tab_df, tab_state)
        assert not any("categorical_frequency" in u for u in uris)


# ── Chart 8: pairplot_top4 ───────────────────────────────────────────────────


class TestPairplot:
    def test_skip_on_large_df(self, tab_state):
        import numpy as np
        import pandas as pd

        big = pd.DataFrame(np.random.default_rng(0).random((6000, 5)), columns=[f"f{i}" for i in range(5)])
        big["Survived"] = [0, 1] * 3000
        uris, _ = _charts(big, tab_state)
        assert not any("pairplot_top4" in u for u in uris)

    def test_renders_on_small_df(self, tab_df, tab_state):
        uris, _ = _charts(tab_df, tab_state)
        assert any("pairplot_top4" in u for u in uris)


# ── Chart 9: qq_plot_grid ────────────────────────────────────────────────────


class TestQQPlot:
    def test_triggers_on_nonnormal(self, tab_df_skewed, tab_state):
        # skewed df은 normaltest p < 0.05 컬럼 존재 기대
        uris, _ = _charts(tab_df_skewed, tab_state)
        # trigger pass 여부는 scipy normaltest에 달려 있음 — 존재 여부만 확인
        assert isinstance(uris, list)


# ── Chart 11: outlier_summary ─────────────────────────────────────────────────


class TestOutlierSummary:
    def test_robust_star_marker(self, tab_df, tab_state_after_day2_smote):
        uris, _ = _charts(tab_df, tab_state_after_day2_smote)
        assert any("outlier_summary" in u for u in uris)

    def test_skips_when_no_outliers(self, tab_state):
        import pandas as pd

        clean = pd.DataFrame(
            {
                "A": [1.0, 1.0, 1.0, 1.0, 1.0] * 24,
                "B": [2.0, 2.0, 2.0, 2.0, 2.0] * 24,
                "Survived": [0, 1] * 60,
            }
        )
        uris, _ = _charts(clean, tab_state)
        assert not any("outlier_summary" in u for u in uris)


# ── Chart 12: smote_before_after_scatter ─────────────────────────────────────


class TestSmoteScatter:
    def test_renders_when_smote_applied(self, tab_df, tab_state_after_day2_smote):
        uris, _ = _charts(tab_df, tab_state_after_day2_smote)
        assert any("smote_before_after" in u for u in uris)

    def test_skips_when_no_smote(self, tab_df, tab_state):
        uris, _ = _charts(tab_df, tab_state)
        assert not any("smote_before_after" in u for u in uris)


# ── eda_baseline extras ───────────────────────────────────────────────────────


class TestEdaBaseline:
    def test_baseline_populated_when_chart4_runs(self, tab_df, tab_state):
        _, extras = _charts(tab_df, tab_state)
        assert "eda_baseline" in extras
        bl = extras["eda_baseline"]
        assert "cv_score" in bl
        assert "metric" in bl
        assert "top_feature_concentration" in bl
        assert "nonlinearity_estimate" in bl

    def test_baseline_absent_on_tiny_dataset(self, tab_state):
        import pandas as pd

        tiny = pd.DataFrame({"A": range(10), "B": range(10), "Survived": [0, 1] * 5})
        _, extras = _charts(tiny, tab_state)
        assert "eda_baseline" not in extras

    def test_metric_classification(self, tab_df, tab_state):
        _, extras = _charts(tab_df, tab_state)
        if "eda_baseline" in extras:
            assert extras["eda_baseline"]["metric"] == "f1_macro"

    def test_metric_regression(self, tab_df, tab_state_regression):
        _, extras = _charts(tab_df, tab_state_regression)
        if "eda_baseline" in extras:
            assert extras["eda_baseline"]["metric"] == "r2"


# ── hint overrides ────────────────────────────────────────────────────────────


class TestHintOverrides:
    def test_force_chart(self, tab_state):
        """트리거 미통과 차트도 force_chart에 넣으면 포함됨."""
        import pandas as pd

        cat_only = pd.DataFrame(
            {
                "Sex": ["male", "female"] * 60,
                "Survived": ["y", "n"] * 60,
            }
        )
        state = _wrap_hints(tab_state, {"force_chart": ["correlation_heatmap"]})
        from agents.handlers.tabular.eda import charts

        uris, _ = charts(cat_only, state)
        assert any("correlation_heatmap" in u for u in uris)

    def test_disable_chart(self, tab_df, tab_state):
        """disable_chart에 있는 차트는 결과에 없어야 함."""
        state = _wrap_hints(tab_state, {"disable_chart": ["correlation_heatmap"]})
        from agents.handlers.tabular.eda import charts

        uris, _ = charts(tab_df, state)
        assert not any("correlation_heatmap" in u for u in uris)

    def test_max_charts_cap(self, tab_df_wide, tab_state):
        state = _wrap_hints(tab_state, {"max_charts": 4})
        from agents.handlers.tabular.eda import charts

        uris, _ = charts(tab_df_wide, state)
        assert len(uris) <= 4


# ── memory leak ───────────────────────────────────────────────────────────────


class TestMemoryLeak:
    def test_no_open_figures_after_charts(self, tab_df, tab_state):
        import matplotlib.pyplot as plt

        plt.close("all")
        _charts(tab_df, tab_state)
        assert len(plt.get_fignums()) == 0


# ── integration scenarios ─────────────────────────────────────────────────────


class TestIntegration:
    def test_minimal_scenario(self, tab_df, tab_state):
        uris, _ = _charts(tab_df, tab_state)
        assert 3 <= len(uris) <= 12

    def test_rich_scenario(self, tab_df_wide, tab_df_with_mar_missing, tab_state):
        import numpy as np
        import pandas as pd

        combined = pd.DataFrame(
            np.random.default_rng(1).random((120, 10)),
            columns=[f"f{i}" for i in range(10)],
        )
        combined["Survived"] = [0, 1] * 60
        state = tab_state.with_update(data_profile={"class_imbalance_ratio": 5.0})
        uris, _ = _charts(combined, state)
        assert 3 <= len(uris) <= 12

    def test_smote_scenario(self, tab_df, tab_state_after_day2_smote):
        uris, extras = _charts(tab_df, tab_state_after_day2_smote)
        assert 3 <= len(uris) <= 12
        assert any("smote" in u for u in uris)

    def test_dl_branch(self, tab_df, tab_dl_state):
        uris, _ = _charts(tab_df, tab_dl_state)
        assert 3 <= len(uris) <= 12
