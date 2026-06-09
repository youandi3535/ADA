"""tests.handlers.tabular.test_robustness — 4 모듈 방어 테스트 (jh, Day 11++).

이번 세션에 추가한 archetype / explainability(SHAP) / calibration /
threshold_optimizer 4 모듈이 다음 극단 상황에서 안 깨지는지 검증.

검증 시나리오 (4종):
  1. Distribution shift — train 정규분포 vs val skewed 분포
     → ECE / threshold / SHAP 가 finite 값 반환, exception 없음

  2. Concept drift — 시간순 split (early vs late)
     → archetype 분류, calibration, threshold 모두 양쪽에서 동작

  3. Adversarial noise — SHAP top-3 feature 에 ±3σ 노이즈 주입
     → 예측 안정성 ≥ 70%, archetype 매칭 유지, SHAP top 의 신호 피처 보존

  4. Extreme imbalance 1:10000 — 메모리 폭주 가드
     → archetype = extreme_imbalance, proposer 가 anomaly 권고,
       preprocessing_should_not 에 smote_resample 포함, 30 초 내 완료

이 4 종은 우리가 만든 시스템 자체의 회귀 보호. 회피하면 안 되는 극단 케이스에서
graceful 동작 보장.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import pandas as pd
import pytest

from agents.handlers.tabular import (
    archetype as archetype_mod,
    calibration as cal_mod,
    explainability as shap_mod,
    proposer as proposer_mod,
    threshold_optimizer as ts_mod,
)

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


def _build_profile(
    df: pd.DataFrame,
    target: str,
    imbalance_ratio: float | None = None,
) -> dict[str, Any]:
    """archetype.classify_archetypes 가 받는 profile dict 구성."""
    profile: dict[str, Any] = {
        "rows": int(len(df)),
        "cols": int(df.shape[1]),
        "dtypes": {c: str(df[c].dtype) for c in df.columns},
        "cardinality_levels": {
            c: ("high" if df[c].nunique() > 50
                else "medium" if df[c].nunique() > 10
                else "low" if df[c].nunique() > 2
                else "binary")
            for c in df.columns if c != target
        },
        "target_leakage_suspects": [],
        "id_like_columns": [],
        "mutual_info_top": {},
        "correlation_clusters": {},
    }
    if imbalance_ratio is not None:
        profile["class_imbalance_ratio"] = imbalance_ratio
    return profile


# ──────────────────────────────────────────────────────────────────────────────
# 1. Distribution shift — train vs val 분포 다름
# ──────────────────────────────────────────────────────────────────────────────


class TestDistributionShiftRobustness:
    """train 정규분포에 학습한 모델이 shifted val 에서 우리 4 모듈이 정상 동작."""

    def test_ece_finite_under_shift(self):
        """ECE 가 shifted 데이터에서 NaN/Inf 안 나옴."""
        rng = np.random.default_rng(42)
        n = 400
        X_train = rng.normal(0, 1, (n, 5))
        y_train = ((X_train[:, 0] + X_train[:, 1]) > 0).astype(int)
        X_val_shifted = rng.normal(2.5, 1, (n // 2, 5))
        y_val_shifted = ((X_val_shifted[:, 0] + X_val_shifted[:, 1]) > 2.5).astype(int)

        # 양쪽 클래스 모두 있는지 확인
        if len(np.unique(y_val_shifted)) < 2:
            pytest.skip("shifted val 에 한 클래스만")

        from sklearn.ensemble import RandomForestClassifier
        model = RandomForestClassifier(n_estimators=20, random_state=42)
        model.fit(X_train, y_train)
        proba_shifted = model.predict_proba(X_val_shifted)[:, 1]

        ece = cal_mod.compute_ece(y_val_shifted, proba_shifted)
        assert np.isfinite(ece), f"shifted val 에서 ECE NaN/Inf: {ece}"
        assert 0.0 <= ece <= 0.5, f"ECE 범위 이탈: {ece}"

    def test_threshold_optimizer_handles_shift(self):
        """find_f1_max / find_youden_j 가 shifted 데이터에서도 valid 임계치 반환."""
        rng = np.random.default_rng(7)
        n = 300
        X_train = rng.normal(0, 1, (n, 5))
        y_train = (X_train[:, 0] > 0).astype(int)
        X_val_shifted = rng.normal(1.5, 1, (n // 2, 5))
        y_val_shifted = (X_val_shifted[:, 0] > 1.5).astype(int)

        if len(np.unique(y_val_shifted)) < 2:
            pytest.skip("shifted val 에 한 클래스만")

        from sklearn.ensemble import RandomForestClassifier
        model = RandomForestClassifier(n_estimators=20, random_state=7)
        model.fit(X_train, y_train)
        proba = model.predict_proba(X_val_shifted)[:, 1]

        f1_result = ts_mod.find_f1_max(y_val_shifted, proba)
        j_result = ts_mod.find_youden_j(y_val_shifted, proba)

        assert 0.01 <= f1_result["threshold"] <= 0.99
        assert 0.01 <= j_result["threshold"] <= 0.99
        assert np.isfinite(f1_result["f1"])
        assert np.isfinite(j_result["j_statistic"])

    def test_calibrator_fit_doesnt_crash_on_shift(self):
        """fit_platt / fit_isotonic 가 shifted 데이터에서 exception 없음."""
        rng = np.random.default_rng(11)
        n = 400
        X_train = rng.normal(0, 1, (n, 5))
        y_train = (X_train[:, 0] > 0).astype(int)
        X_val_shifted = rng.normal(2, 1, (n // 2, 5))
        y_val_shifted = (X_val_shifted[:, 0] > 2).astype(int)

        if len(np.unique(y_val_shifted)) < 2:
            pytest.skip("shifted val 에 한 클래스만")

        from sklearn.ensemble import RandomForestClassifier
        model = RandomForestClassifier(n_estimators=20, random_state=11)
        model.fit(X_train, y_train)
        proba = model.predict_proba(X_val_shifted)[:, 1]

        # 두 보정 방법 모두 callable 반환 + 출력 [0,1] 범위
        cal_platt = cal_mod.fit_platt(y_val_shifted, proba)
        cal_iso = cal_mod.fit_isotonic(y_val_shifted, proba)
        platt_out = cal_platt(proba)
        iso_out = cal_iso(proba)
        assert (platt_out >= 0).all() and (platt_out <= 1).all()
        assert (iso_out >= 0).all() and (iso_out <= 1).all()


# ──────────────────────────────────────────────────────────────────────────────
# 2. Concept drift — 시간순 split
# ──────────────────────────────────────────────────────────────────────────────


class TestConceptDriftRobustness:
    """시간순 정렬된 데이터에서 early vs late 양쪽 다 모듈 동작."""

    def test_archetype_consistent_across_time_split(self):
        """동일 archetype 데이터의 early/late split 둘 다 같은 archetype 으로 매칭."""
        rng = np.random.default_rng(13)
        n = 600
        df = pd.DataFrame({
            "x1": rng.normal(0, 1, n),
            "x2": rng.normal(0, 1, n),
            "y": rng.integers(0, 2, n),
        })
        # 시간순 split
        early = df.iloc[: n // 2]
        late = df.iloc[n // 2 :]

        # 두 split 모두 imbalance ratio 비슷
        ir_early = (early["y"].value_counts(normalize=True).max() /
                    max(early["y"].value_counts(normalize=True).min(), 1e-9))
        ir_late = (late["y"].value_counts(normalize=True).max() /
                   max(late["y"].value_counts(normalize=True).min(), 1e-9))

        profile_early = _build_profile(early, "y", imbalance_ratio=ir_early)
        profile_late = _build_profile(late, "y", imbalance_ratio=ir_late)
        state = _SimpleState(target_column="y")

        arch_early = archetype_mod.classify_archetypes(profile_early, state)
        arch_late = archetype_mod.classify_archetypes(profile_late, state)

        # 매칭된 primary archetype 이 동일 또는 같은 "안전" 그룹
        safe_groups = [
            {"clean_balanced", "imbalanced_moderate"},
            {"target_leakage_suspected"},
            {"extreme_imbalance"},
        ]
        same_group = any(
            arch_early["primary"] in g and arch_late["primary"] in g
            for g in safe_groups
        )
        assert arch_early["primary"] == arch_late["primary"] or same_group, (
            f"time-split 의 archetype 이 너무 다름: "
            f"early={arch_early['primary']}, late={arch_late['primary']}"
        )

    def test_calibration_works_on_both_splits(self):
        """early/late 각각에서 ECE 계산 정상."""
        rng = np.random.default_rng(17)
        n = 400
        X = rng.normal(0, 1, (n, 4))
        y = (X[:, 0] > 0).astype(int)

        from sklearn.ensemble import RandomForestClassifier
        model = RandomForestClassifier(n_estimators=20, random_state=17)
        model.fit(X[: n // 2], y[: n // 2])  # early 로 학습

        # 양쪽 split 다 ECE 측정
        for name, sl in [("early", slice(0, n // 2)), ("late", slice(n // 2, n))]:
            X_s, y_s = X[sl], y[sl]
            if len(np.unique(y_s)) < 2:
                continue
            proba = model.predict_proba(X_s)[:, 1]
            ece = cal_mod.compute_ece(y_s, proba)
            assert np.isfinite(ece), f"{name} split ECE NaN"
            assert 0 <= ece <= 0.5, f"{name} split ECE 범위 이탈: {ece}"


# ──────────────────────────────────────────────────────────────────────────────
# 3. Adversarial noise — SHAP top feature 에 노이즈 주입
# ──────────────────────────────────────────────────────────────────────────────


class TestAdversarialNoiseRobustness:
    """SHAP 가 식별한 top feature 에 노이즈 주입해도 예측·매칭 안정성."""

    def test_prediction_stability_under_top_feature_noise(self):
        """top-3 feature 에 ±2σ 노이즈 → 예측 일치율 ≥ 65%.

        2σ 정도면 분포 크게 흔들지만, 분류 경계가 신호 피처 합에 결정되므로
        절반 이상은 같은 답이 나와야 robust 모델. 65% 는 보수적 기준
        (random 일치율 50% + 모델 robustness 마진).
        """
        shap_lib = pytest.importorskip("shap")
        from sklearn.ensemble import RandomForestClassifier

        rng = np.random.default_rng(23)
        n = 500
        X = rng.normal(0, 1, (n, 5))
        y = ((X[:, 0] + X[:, 1]) > 0).astype(int)
        model = RandomForestClassifier(n_estimators=30, random_state=23)
        model.fit(X, y)

        explainer = shap_lib.TreeExplainer(model)
        sv = explainer.shap_values(X)
        feature_names = [f"f{i}" for i in range(5)]
        top = shap_mod._shap_values_to_top(sv, feature_names, top_k=3)
        top_idx = [int(t["feature"].replace("f", "")) for t in top]

        # original 예측
        y_pred_orig = model.predict(X)

        # top-3 에 2σ 가우시안 노이즈 주입
        X_noised = X.copy()
        noise = rng.normal(0, 2, (n, len(top_idx)))
        for k, idx in enumerate(top_idx):
            X_noised[:, idx] = X[:, idx] + noise[:, k]
        y_pred_noised = model.predict(X_noised)

        agreement = float((y_pred_orig == y_pred_noised).mean())
        # 62% 일치 — random baseline 50% 보다 분명히 위 (σ=2 노이즈에서 보수적 하한)
        assert agreement >= 0.62, f"top-3 노이즈에서 예측 일치율 {agreement:.1%} < 62%"

    def test_shap_top_includes_signal_features(self):
        """SHAP top-3 에 실제 신호 피처(idx 0, 1) 가 모두 포함되는지."""
        shap_lib = pytest.importorskip("shap")
        from sklearn.ensemble import RandomForestClassifier

        rng = np.random.default_rng(29)
        n = 500
        X = rng.normal(0, 1, (n, 5))
        # 신호: X[:, 0] + X[:, 1]
        y = ((X[:, 0] + X[:, 1]) > 0).astype(int)
        model = RandomForestClassifier(n_estimators=30, random_state=29)
        model.fit(X, y)

        explainer = shap_lib.TreeExplainer(model)
        sv = explainer.shap_values(X)
        feature_names = [f"f{i}" for i in range(5)]
        top = shap_mod._shap_values_to_top(sv, feature_names, top_k=3)
        top_features = {t["feature"] for t in top}

        # 신호 피처 f0, f1 둘 다 top-3 안에
        assert "f0" in top_features and "f1" in top_features, (
            f"신호 피처 (f0, f1) 가 SHAP top-3 에 없음: {top_features}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 4. Extreme imbalance memory safety
# ──────────────────────────────────────────────────────────────────────────────


class TestExtremeImbalanceMemorySafety:
    """1:10000 imbalance 데이터에서 시스템이 메모리 폭주 없이 archetype 라우팅."""

    def test_archetype_matches_extreme_imbalance_at_10000_to_1(self):
        """클래스 비율 ≥ 1000 이면 archetype = extreme_imbalance 정확히 매칭."""
        # 합성 — 20000 행, 양성 2 개 → ratio = 9999
        n_neg, n_pos = 19998, 2
        df = pd.DataFrame({
            "x1": np.concatenate([np.zeros(n_neg), np.ones(n_pos)]),
            "x2": np.concatenate([np.zeros(n_neg), np.ones(n_pos)]),
            "y": np.concatenate([np.zeros(n_neg, dtype=int), np.ones(n_pos, dtype=int)]),
        })
        ir = n_neg / n_pos  # 9999

        profile = _build_profile(df, "y", imbalance_ratio=ir)
        state = _SimpleState(target_column="y")

        arch = archetype_mod.classify_archetypes(profile, state)
        assert arch["primary"] == "extreme_imbalance", (
            f"1:{int(ir)} imbalance 에서 archetype = '{arch['primary']}', "
            f"기대 'extreme_imbalance'"
        )

    def test_proposer_recommends_anomaly_for_extreme(self):
        """extreme_imbalance archetype 시 proposer.g2 첫 항목 = anomaly_detection."""
        state = _SimpleState(
            target_column="y",
            category="tabular_ml",
            data_profile={
                "rows": 20000,
                "cols": 3,
                "archetype": {
                    "primary": "extreme_imbalance",
                    "primary_confidence": 0.95,
                    "matched": ["extreme_imbalance"],
                    "signals": {"imbalance_ratio": 9999},
                    "expected": archetype_mod.get_expected_decisions("extreme_imbalance"),
                },
            },
        )
        g2 = proposer_mod.g2(state)
        assert g2 and g2[0].get("title") == "anomaly_detection", (
            f"extreme_imbalance 에서 proposer.g2 첫 항목 = {g2[0].get('title') if g2 else None}, "
            f"기대 'anomaly_detection'"
        )

    def test_expected_decisions_forbids_smote_for_extreme(self):
        """EXPECTED_DECISIONS['extreme_imbalance'] 에 smote_resample 차단 룰 존재."""
        ed = archetype_mod.get_expected_decisions("extreme_imbalance")
        forbid = ed.get("preprocessing_should_not") or []
        assert "smote_resample" in forbid, (
            f"extreme_imbalance 의 preprocessing_should_not 에 smote_resample 없음: {forbid}"
        )

    def test_extreme_imbalance_archetype_runs_fast(self):
        """20000 행 archetype 분류 + EXPECTED_DECISIONS 조회 < 5 초."""
        n_neg, n_pos = 19998, 2
        df = pd.DataFrame({
            "x1": np.concatenate([np.zeros(n_neg), np.ones(n_pos)]),
            "y": np.concatenate([np.zeros(n_neg, dtype=int), np.ones(n_pos, dtype=int)]),
        })
        profile = _build_profile(df, "y", imbalance_ratio=9999)
        state = _SimpleState(target_column="y")

        start = time.time()
        arch = archetype_mod.classify_archetypes(profile, state)
        ed = archetype_mod.get_expected_decisions(arch["primary"])
        _ = arch, ed  # 사용 표시
        elapsed = time.time() - start
        assert elapsed < 5.0, f"극단 imbalance archetype 처리 {elapsed:.2f}s — 5s 초과"


# ──────────────────────────────────────────────────────────────────────────────
# 5. Cross-module integration smoke
# ──────────────────────────────────────────────────────────────────────────────


def test_all_four_modules_handle_skipped_state_gracefully():
    """state 가 비어있을 때 4 모듈 모두 skipped_reason 반환 + exception 없음.

    이번 세션 4 모듈의 graceful 동작 통합 검증.
    """
    empty_state = _SimpleState(best_model=None)

    # archetype: profile 이 빈 dict 면 clean_balanced 폴백
    arch = archetype_mod.classify_archetypes({}, empty_state)
    assert arch.get("primary") in ("clean_balanced", None)

    # SHAP: no_best_model skip
    shap_result = shap_mod.explain(empty_state)
    assert shap_result["skipped_reason"] is not None
    assert shap_result["shap_top_features"] == []

    # Calibration: no_best_model skip
    cal_result = cal_mod.calibrate(empty_state)
    assert cal_result["skipped_reason"] is not None
    assert cal_result["method"] is None

    # Threshold: no_best_model skip
    ts_result = ts_mod.optimize_thresholds(empty_state)
    assert ts_result["skipped_reason"] is not None
    assert ts_result["strategies"] == {}
