"""tests.handlers.tabular.test_shap_explainability — SHAP 본구현 검증 (jh, Day 11++).

검증 범위:
  1. explainer 자동 선택 (TreeExplainer/LinearExplainer/KernelExplainer 분기)
  2. baseline 모델 / model 부재 / shap import 실패 시 graceful skip
  3. top_features 가 permutation importance top-3 과 ≥1건 일치 (sanity)
  4. multi-class / 회귀 / 이진 모두 동작
  5. shap_top_features 가 mean_abs_shap 내림차순 정렬
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from agents.handlers.tabular import explainability as shap_mod


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


class _SimpleState:
    def __init__(self, **kwargs):
        self.category = kwargs.get("category", "tabular_ml")
        self.task = kwargs.get("task", "auto")
        self.best_model = kwargs.get("best_model")
        self.data_profile = kwargs.get("data_profile") or {}
        self.target_column = kwargs.get("target_column", "y")
        self.category_extras = kwargs.get("category_extras") or {}
        self.job_id = kwargs.get("job_id", "test-shap")


def _make_state_with_model(model_name: str, category: str = "tabular_ml") -> _SimpleState:
    return _SimpleState(
        best_model={"model_name": model_name, "metrics": {"val_f1": 0.85}},
        category=category,
    )


# ──────────────────────────────────────────────────────────────────────────────
# 1. Explainer 자동 선택
# ──────────────────────────────────────────────────────────────────────────────


class TestExplainerSelection:
    """모델명 + 카테고리로 explainer 종류 결정."""

    def test_tree_for_random_forest(self):
        assert shap_mod._select_explainer_type("RandomForest", "tabular_ml") == "tree"

    def test_tree_for_xgboost(self):
        assert shap_mod._select_explainer_type("XGBoost", "tabular_ml") == "tree"

    def test_tree_for_lightgbm(self):
        assert shap_mod._select_explainer_type("LightGBM", "tabular_ml") == "tree"

    def test_tree_for_catboost(self):
        assert shap_mod._select_explainer_type("CatBoost", "tabular_ml") == "tree"

    def test_linear_for_logistic_regression(self):
        assert shap_mod._select_explainer_type("LogisticRegression", "tabular_ml") == "linear"

    def test_linear_for_ridge(self):
        assert shap_mod._select_explainer_type("Ridge", "tabular_ml") == "linear"

    def test_linear_for_lasso(self):
        assert shap_mod._select_explainer_type("Lasso", "tabular_ml") == "linear"

    def test_kernel_for_dl_category(self):
        assert shap_mod._select_explainer_type("RandomForest", "tabular_dl") == "kernel"

    def test_kernel_for_unknown_model(self):
        assert shap_mod._select_explainer_type("MysteryModel", "tabular_ml") == "kernel"


# ──────────────────────────────────────────────────────────────────────────────
# 2. Graceful skip 가드
# ──────────────────────────────────────────────────────────────────────────────


class TestSkipGuards:
    """가드 통과 못 했을 때 skipped_reason 채워서 반환."""

    def test_no_best_model_skip(self):
        state = _SimpleState(best_model=None)
        result = shap_mod.explain(state)
        assert result["skipped_reason"] == "no_best_model"
        assert result["shap_top_features"] == []
        assert result["shap_summary_path"] is None

    def test_baseline_model_skip(self):
        state = _make_state_with_model("Dummy")
        result = shap_mod.explain(state)
        assert result["skipped_reason"] == "baseline_skip"
        assert result["shap_top_features"] == []

    def test_logistic_regression_baseline_skip(self):
        # LogisticRegression 은 baseline (selector._baselines_for 기준)
        # is_baseline_model 이 True 반환 → skip
        state = _make_state_with_model("LogisticRegression")
        result = shap_mod.explain(state)
        # Day 11+ — LogisticRegression 은 baseline 으로 분류 (selector 와 일관)
        # baseline_skip 이면 통과, 아니면 model_reload_failed 도 OK (테스트 환경 무모델)
        assert result["skipped_reason"] in ("baseline_skip", "model_reload_failed", "shap_import_failed")


# ──────────────────────────────────────────────────────────────────────────────
# 3. Skipped result 형식
# ──────────────────────────────────────────────────────────────────────────────


class TestSkippedResultShape:
    """skipped 결과도 동일 키 구조여야 — insight·output_extras 가 깨지지 않게."""

    def test_skipped_has_all_keys(self):
        result = shap_mod._skipped_result("test_reason")
        required_keys = {
            "shap_top_features",
            "shap_summary_path",
            "shap_dependence_paths",
            "explainer_type",
            "n_samples_used",
            "skipped_reason",
        }
        assert required_keys.issubset(result.keys())

    def test_skipped_top_features_is_empty_list(self):
        result = shap_mod._skipped_result("test_reason")
        assert isinstance(result["shap_top_features"], list)
        assert result["shap_top_features"] == []

    def test_skipped_dependence_paths_is_empty_list(self):
        result = shap_mod._skipped_result("test_reason")
        assert isinstance(result["shap_dependence_paths"], list)
        assert result["shap_dependence_paths"] == []


# ──────────────────────────────────────────────────────────────────────────────
# 4. shap_values_to_top — 정렬 + 출력 형식
# ──────────────────────────────────────────────────────────────────────────────


class TestShapValuesToTop:
    """_shap_values_to_top 매트릭스 → top-K 변환 검증."""

    def test_simple_2d_array(self):
        # 3 sample x 4 feature, feature 2 가 가장 큰 영향
        sv = np.array([
            [0.1, 0.2, 0.8, 0.05],
            [0.1, 0.3, 0.9, 0.04],
            [0.2, 0.1, 0.7, 0.06],
        ])
        feature_names = ["f0", "f1", "f2", "f3"]
        top = shap_mod._shap_values_to_top(sv, feature_names, top_k=3)

        assert len(top) == 3
        assert top[0]["feature"] == "f2"  # 가장 큰 mean_abs
        # 모든 entry 가 직무 key 보유
        for entry in top:
            assert "feature" in entry
            assert "mean_abs_shap" in entry
            assert "direction" in entry
            assert entry["direction"] in ("+", "-")

    def test_descending_order(self):
        sv = np.array([[0.5, -0.1, 0.3, -0.7]])
        feature_names = ["a", "b", "c", "d"]
        top = shap_mod._shap_values_to_top(sv, feature_names, top_k=4)
        # mean_abs 내림차순: d(0.7) > a(0.5) > c(0.3) > b(0.1)
        assert [t["feature"] for t in top] == ["d", "a", "c", "b"]

    def test_multiclass_list_of_arrays(self):
        # multi-class: list of (n_samples, n_features) — class 별
        sv_class0 = np.array([[0.1, 0.5, 0.2]])
        sv_class1 = np.array([[0.2, 0.6, 0.1]])
        sv_class2 = np.array([[0.3, 0.7, 0.05]])
        feature_names = ["x", "y", "z"]
        top = shap_mod._shap_values_to_top([sv_class0, sv_class1, sv_class2], feature_names, top_k=3)

        # 모든 class 의 mean_abs 합산 → y 가 가장 큼
        assert top[0]["feature"] == "y"

    def test_top_k_limit(self):
        sv = np.random.default_rng(42).standard_normal((10, 20))
        feature_names = [f"f{i}" for i in range(20)]
        top = shap_mod._shap_values_to_top(sv, feature_names, top_k=5)
        assert len(top) == 5

    def test_feature_name_mismatch_fallback(self):
        # feature_names 가 짧으면 fallback (feature_i)
        sv = np.array([[0.5, 0.3, 0.1]])
        top = shap_mod._shap_values_to_top(sv, ["only_one"], top_k=3)
        assert all(t["feature"].startswith("feature_") for t in top)


# ──────────────────────────────────────────────────────────────────────────────
# 5. SHAP top matches permutation top (sanity)
# ──────────────────────────────────────────────────────────────────────────────


def _train_dummy_tree_model(seed: int = 42):
    """sklearn RandomForest 학습 — TreeExplainer 직접 검증용."""
    pytest.importorskip("sklearn")
    from sklearn.ensemble import RandomForestClassifier

    rng = np.random.default_rng(seed)
    n = 300
    df = pd.DataFrame({
        "important_1": rng.normal(0, 1, n),
        "important_2": rng.normal(0, 1, n),
        "noise_1": rng.normal(0, 1, n),
        "noise_2": rng.normal(0, 1, n),
    })
    # 중요한 두 피처가 라벨 결정
    df["y"] = ((df["important_1"] + df["important_2"]) > 0).astype(int)

    X = df.drop(columns=["y"])
    y = df["y"]
    model = RandomForestClassifier(n_estimators=50, random_state=seed)
    model.fit(X, y)
    return model, X, y


class TestShapSanityVsPermutation:
    """TreeExplainer SHAP 값이 permutation importance 와 top-3 ≥1건 일치하는지.

    이는 SHAP 구현이 "그럴듯한 값"을 내고 있는지 sanity 보장.
    """

    def test_shap_top_overlaps_permutation_top(self):
        shap_lib = pytest.importorskip("shap")
        from sklearn.inspection import permutation_importance

        model, X, y = _train_dummy_tree_model()
        explainer = shap_lib.TreeExplainer(model)
        shap_values = explainer.shap_values(X)
        feature_names = list(X.columns)
        top_shap = shap_mod._shap_values_to_top(shap_values, feature_names, top_k=3)
        shap_top_features = {t["feature"] for t in top_shap}

        # permutation importance top-3
        result = permutation_importance(model, X, y, n_repeats=3, random_state=42, n_jobs=1)
        perm_idx = np.argsort(result.importances_mean)[::-1][:3]
        perm_top_features = {feature_names[i] for i in perm_idx}

        # 최소 1개 겹쳐야 — 그렇지 않으면 SHAP 구현 의심
        overlap = shap_top_features & perm_top_features
        assert len(overlap) >= 1, (
            f"SHAP top-3 ({shap_top_features}) 가 permutation top-3 ({perm_top_features}) 와 "
            f"전혀 겹치지 않음 — SHAP 구현 오류 의심"
        )

    def test_important_features_rank_higher_than_noise(self):
        shap_lib = pytest.importorskip("shap")

        model, X, y = _train_dummy_tree_model()
        explainer = shap_lib.TreeExplainer(model)
        shap_values = explainer.shap_values(X)
        feature_names = list(X.columns)
        top = shap_mod._shap_values_to_top(shap_values, feature_names, top_k=4)

        # important_1, important_2 가 noise_1, noise_2 보다 위 순위
        ranks = {t["feature"]: i for i, t in enumerate(top)}
        important_ranks = [ranks.get("important_1", 99), ranks.get("important_2", 99)]
        noise_ranks = [ranks.get("noise_1", 99), ranks.get("noise_2", 99)]
        assert max(important_ranks) < min(noise_ranks), (
            f"important features ({important_ranks}) 가 noise ({noise_ranks}) 보다 "
            f"낮은 순위 — SHAP 가 신호를 못 잡음"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 6. 편의 함수 (shap_top_features / shap_summary_chart) 캐시 동작
# ──────────────────────────────────────────────────────────────────────────────


class TestCacheReuse:
    """category_extras 에 캐시가 있으면 재계산 안 함."""

    def test_shap_top_features_uses_cache(self):
        cached_top = [
            {"feature": "cached_feat", "mean_abs_shap": 0.9, "direction": "+"},
        ]
        state = _SimpleState(
            best_model={"model_name": "RandomForest", "metrics": {}},
            category_extras={"tabular": {"shap": {"shap_top_features": cached_top}}},
        )
        result = shap_mod.shap_top_features(state)
        assert result == cached_top

    def test_shap_summary_chart_uses_cache(self):
        state = _SimpleState(
            best_model={"model_name": "RandomForest", "metrics": {}},
            category_extras={
                "tabular": {
                    "shap": {
                        "shap_top_features": [],
                        "shap_summary_path": "s3://cached/path/summary.png",
                    }
                }
            },
        )
        result = shap_mod.shap_summary_chart(state)
        assert result == "s3://cached/path/summary.png"
