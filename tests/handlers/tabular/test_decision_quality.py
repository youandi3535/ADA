"""tests.handlers.tabular.test_decision_quality — Decision audit (jh 담당, Day 11+).

목적
====
"임의의 데이터가 들어왔을 때 시스템이 적합한 분석 경로를 고르는가" 를 측정.
F1·AUC 같은 outcome 메트릭이 아니라 **decision match rate** 가 측정 단위.

각 시나리오:
  1. archetype 특성을 만족하는 합성 데이터 생성 (seed 고정, 결정론)
  2. profiler.profile() 호출 → archetype 분류
  3. selector.score() 호출 → 모델 추천
  4. proposer.g2() 호출 → 카테고리 권고
  5. expected_decisions 와 비교 → match_rate 산출

KPI:
  - KP_tab1 (평균 match_rate) ≥ 0.85
  - KP_tab2 (최악 케이스 match_rate) ≥ 0.70
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from agents.handlers.tabular import (
    archetype as archetype_mod,
    profiler as profiler_mod,
    proposer as proposer_mod,
    selector as selector_mod,
)

# ──────────────────────────────────────────────────────────────────────────────
# 시나리오 합성 데이터 생성기
# ──────────────────────────────────────────────────────────────────────────────


def _gen_clean_balanced(seed: int = 42) -> tuple[pd.DataFrame, str]:
    """깨끗한 균형 분류 — 정상 baseline."""
    rng = np.random.default_rng(seed)
    n = 800
    df = pd.DataFrame({
        "x1": rng.normal(0, 1, n),
        "x2": rng.normal(0, 1, n),
        "x3": rng.normal(0, 1, n),
        "cat": rng.choice(["A", "B", "C"], n),
    })
    df["y"] = (df["x1"] + df["x2"] > 0).astype(int)
    return df, "y"


def _gen_extreme_imbalance(seed: int = 42) -> tuple[pd.DataFrame, str]:
    """1:1500 극단 불균형 → anomaly 권고 기대."""
    rng = np.random.default_rng(seed)
    n_neg, n_pos = 6000, 4  # ratio ≈ 1500
    df_neg = pd.DataFrame({
        "x1": rng.normal(0, 1, n_neg),
        "x2": rng.normal(0, 1, n_neg),
        "y": np.zeros(n_neg, dtype=int),
    })
    df_pos = pd.DataFrame({
        "x1": rng.normal(3, 1, n_pos),
        "x2": rng.normal(3, 1, n_pos),
        "y": np.ones(n_pos, dtype=int),
    })
    df = pd.concat([df_neg, df_pos], ignore_index=True).sample(frac=1, random_state=seed).reset_index(drop=True)
    return df, "y"


def _gen_target_leakage(seed: int = 42) -> tuple[pd.DataFrame, str]:
    """target 과 corr ≥ 0.95 컬럼 포함."""
    rng = np.random.default_rng(seed)
    n = 500
    y = rng.normal(0, 1, n)
    df = pd.DataFrame({
        "leak": y + rng.normal(0, 0.05, n),  # corr ≈ 0.998
        "x1": rng.normal(0, 1, n),
        "x2": rng.normal(0, 1, n),
        "y": y,
    })
    return df, "y"


def _gen_p_gg_n(seed: int = 42) -> tuple[pd.DataFrame, str]:
    """n=200, features=120 → ratio=0.6 → p≫n."""
    rng = np.random.default_rng(seed)
    n, p = 200, 120
    X = rng.normal(0, 1, (n, p))
    y = (X[:, 0] + X[:, 1] - X[:, 2] > 0).astype(int)
    df = pd.DataFrame(X, columns=[f"x{i}" for i in range(p)])
    df["y"] = y
    return df, "y"


def _gen_high_cardinality(seed: int = 42) -> tuple[pd.DataFrame, str]:
    """high-cardinality 컬럼 4 개 (city, merchant_id, product_id, user_segment)."""
    rng = np.random.default_rng(seed)
    n = 1000
    df = pd.DataFrame({
        "city": rng.choice([f"city_{i}" for i in range(200)], n),
        "merchant_id": rng.choice([f"m_{i}" for i in range(500)], n),
        "product_id": rng.choice([f"p_{i}" for i in range(800)], n),
        "user_segment": rng.choice([f"seg_{i}" for i in range(150)], n),
        "amount": rng.normal(100, 30, n),
        "y": rng.integers(0, 2, n),
    })
    return df, "y"


def _gen_multicollinear(seed: int = 42) -> tuple[pd.DataFrame, str]:
    """수치형 강한 다중공선성 — corr cluster 2 개 이상."""
    rng = np.random.default_rng(seed)
    n = 500
    base1 = rng.normal(0, 1, n)
    base2 = rng.normal(0, 1, n)
    df = pd.DataFrame({
        "a1": base1,
        "a2": base1 + rng.normal(0, 0.05, n),  # cluster 1
        "a3": base1 + rng.normal(0, 0.05, n),  # cluster 1
        "b1": base2,
        "b2": base2 + rng.normal(0, 0.05, n),  # cluster 2
        "b3": base2 + rng.normal(0, 0.05, n),  # cluster 2
        "y": (base1 + base2 > 0).astype(int),
    })
    return df, "y"


def _gen_imbalanced_moderate(seed: int = 42) -> tuple[pd.DataFrame, str]:
    """1:20 중간 불균형."""
    rng = np.random.default_rng(seed)
    n_neg, n_pos = 4000, 200
    df_neg = pd.DataFrame({
        "x1": rng.normal(0, 1, n_neg),
        "x2": rng.normal(0, 1, n_neg),
        "y": np.zeros(n_neg, dtype=int),
    })
    df_pos = pd.DataFrame({
        "x1": rng.normal(2, 1, n_pos),
        "x2": rng.normal(2, 1, n_pos),
        "y": np.ones(n_pos, dtype=int),
    })
    df = pd.concat([df_neg, df_pos], ignore_index=True).sample(frac=1, random_state=seed).reset_index(drop=True)
    return df, "y"


def _gen_id_overload(seed: int = 42) -> tuple[pd.DataFrame, str]:
    """id-like 컬럼이 전체의 30% 이상."""
    rng = np.random.default_rng(seed)
    n = 500
    df = pd.DataFrame({
        "user_id": np.arange(n),         # unique_ratio=1.0
        "session_id": np.arange(n) + 1000,  # unique_ratio=1.0
        "request_id": np.arange(n) + 2000,  # unique_ratio=1.0
        "x1": rng.normal(0, 1, n),
        "x2": rng.normal(0, 1, n),
        "y": rng.integers(0, 2, n),
    })
    return df, "y"


# 시나리오 catalogue
SCENARIOS = {
    "clean_balanced":        (_gen_clean_balanced,        "clean_balanced"),
    "extreme_imbalance":     (_gen_extreme_imbalance,     "extreme_imbalance"),
    "target_leakage":        (_gen_target_leakage,        "target_leakage_suspected"),
    "p_gg_n":                (_gen_p_gg_n,                "p_gg_n"),
    "high_cardinality":      (_gen_high_cardinality,      "high_cardinality_heavy"),
    "multicollinear":        (_gen_multicollinear,        "multicollinear_heavy"),
    "imbalanced_moderate":   (_gen_imbalanced_moderate,   "imbalanced_moderate"),
    "id_overload":           (_gen_id_overload,           "id_overload"),
}


# ──────────────────────────────────────────────────────────────────────────────
# 결정 추출 + decision match 함수
# ──────────────────────────────────────────────────────────────────────────────


class _SimpleState:
    """profile/selector/proposer 호출용 최소 state."""

    def __init__(self, target: str, category: str = "tabular_ml"):
        self.target_column = target
        self.category = category
        self.task = "auto"
        self.data_profile = None
        self.category_extras = {}
        self.user_intent = "테스트"
        self.eval_result = None
        self.explanations = None
        self.best_model = None
        self.trained_models = []


def _build_decisions(df: pd.DataFrame, target: str) -> dict[str, Any]:
    """전체 파이프라인 일부 (profile → selector → proposer.g2) 실행 결과 수집."""
    state = _SimpleState(target=target)
    # profile() 의 결과로 state.data_profile 을 즉시 구성 (정상 흐름 모방)
    profile_extra = profiler_mod.profile(df, state)
    state.data_profile = {
        "rows": int(df.shape[0]),
        "cols": int(df.shape[1]),
        "dtypes": {c: str(df[c].dtype) for c in df.columns},
        **profile_extra,
    }
    # selector 호출
    selector_result = selector_mod.score(state, recipes=[])
    # proposer.g2 호출
    g2_result = proposer_mod.g2(state)
    return {
        "archetype_primary": (profile_extra.get("archetype") or {}).get("primary"),
        "selector_top3": selector_result["top3"],
        "selector_archetype": selector_result.get("archetype", {}),
        "proposer_g2_top": (g2_result[0] if g2_result else {}).get("title"),
    }


def _audit(decisions: dict[str, Any], expected_archetype: str) -> tuple[int, int, list[str]]:
    """decisions vs expected_decisions 비교 → (matched, total, missed[])."""
    expected = archetype_mod.get_expected_decisions(expected_archetype)
    matched = 0
    total = 0
    missed: list[str] = []

    # check 1: archetype primary 가 기대값과 일치하는가
    total += 1
    if decisions["archetype_primary"] == expected_archetype:
        matched += 1
    else:
        missed.append(
            f"archetype_primary: expected={expected_archetype}, got={decisions['archetype_primary']}"
        )

    # check 2: selector_top1_in 만족
    sel_in = expected.get("selector_top1_in")
    if sel_in:
        total += 1
        top1 = decisions["selector_top3"][0] if decisions["selector_top3"] else None
        if top1 in sel_in:
            matched += 1
        else:
            missed.append(f"selector_top1_in: expected∈{sel_in}, got={top1}")

    # check 3: selector_top1_not_in 만족
    sel_out = expected.get("selector_top1_not_in")
    if sel_out:
        total += 1
        top1 = decisions["selector_top3"][0] if decisions["selector_top3"] else None
        if top1 not in sel_out:
            matched += 1
        else:
            missed.append(f"selector_top1_not_in: expected∉{sel_out}, got={top1}")

    # check 4: proposer_recommends_category 만족
    proposer_rec = expected.get("proposer_recommends_category")
    if proposer_rec:
        total += 1
        if decisions["proposer_g2_top"] == proposer_rec:
            matched += 1
        else:
            missed.append(
                f"proposer_recommends_category: expected={proposer_rec}, got={decisions['proposer_g2_top']}"
            )

    return matched, total, missed


# ──────────────────────────────────────────────────────────────────────────────
# 시나리오별 테스트
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def decision_audit_results() -> dict[str, Any]:
    """전 시나리오에 대해 결정 추출 + audit 1 회 실행 (모듈 단일 실행)."""
    results: dict[str, Any] = {}
    for sid, (gen, expected_archetype) in SCENARIOS.items():
        df, target = gen()
        decisions = _build_decisions(df, target)
        matched, total, missed = _audit(decisions, expected_archetype)
        results[sid] = {
            "expected": expected_archetype,
            "decisions": decisions,
            "matched": matched,
            "total": total,
            "missed": missed,
            "match_rate": round(matched / total, 3) if total else 0.0,
        }
    return results


@pytest.mark.parametrize("scenario_id", list(SCENARIOS.keys()))
def test_per_scenario_decision_quality(scenario_id: str, decision_audit_results: dict[str, Any]) -> None:
    """각 시나리오별 결정 정확도 ≥ 0.70 (최악 케이스 보호선)."""
    r = decision_audit_results[scenario_id]
    rate = r["match_rate"]
    assert rate >= 0.70, (
        f"{scenario_id}: 결정 정확도 {rate:.0%} < 0.70 — "
        f"missed: {'; '.join(r['missed'])}"
    )


def test_average_decision_quality(decision_audit_results: dict[str, Any]) -> None:
    """KP_tab1 — 전 시나리오 평균 결정 정확도 ≥ 0.85."""
    rates = [r["match_rate"] for r in decision_audit_results.values()]
    avg = sum(rates) / len(rates)
    assert avg >= 0.85, (
        f"평균 결정 정확도 {avg:.0%} < 0.85 — "
        f"per-scenario: {[(sid, r['match_rate']) for sid, r in decision_audit_results.items()]}"
    )


def test_no_false_positive_on_clean_data(decision_audit_results: dict[str, Any]) -> None:
    """KP_tab4 — 깨끗한 데이터에서 archetype 오인 없음 (false positive 0건)."""
    clean = decision_audit_results["clean_balanced"]
    # clean_balanced 시나리오는 leakage / extreme_imbalance / p_gg_n 같은 우선순위
    # 0/1 archetype 으로 오인되면 안 됨.
    primary = clean["decisions"]["archetype_primary"]
    forbidden = {
        "target_leakage_suspected",
        "extreme_imbalance",
        "p_gg_n",
        "id_overload",
    }
    assert primary not in forbidden, (
        f"clean_balanced 데이터에 archetype='{primary}' 잘못 매칭 — false positive 발생"
    )


def test_extreme_imbalance_routes_to_anomaly(decision_audit_results: dict[str, Any]) -> None:
    """1:1500 데이터는 proposer.g2 가 anomaly_detection 을 1 순위로 권고해야 함."""
    r = decision_audit_results["extreme_imbalance"]
    assert r["decisions"]["proposer_g2_top"] == "anomaly_detection", (
        f"극단 불균형이지만 proposer 가 anomaly 를 권고하지 않음: "
        f"{r['decisions']['proposer_g2_top']}"
    )


def test_target_leakage_excludes_gbdt_top1(decision_audit_results: dict[str, Any]) -> None:
    """target leakage 데이터에선 selector top1 이 보수적 모델 (RF/LR/Ridge/Dummy)."""
    r = decision_audit_results["target_leakage"]
    top1 = r["decisions"]["selector_top3"][0]
    safe_models = {"RandomForest", "LogisticRegression", "Ridge", "Dummy"}
    assert top1 in safe_models, (
        f"target_leakage 데이터에서 selector top1='{top1}' 이 안전 집합 {safe_models} 에 없음"
    )


def test_p_gg_n_excludes_tree_top1(decision_audit_results: dict[str, Any]) -> None:
    """p≫n 데이터에선 selector top1 이 트리 모델 아님."""
    r = decision_audit_results["p_gg_n"]
    top1 = r["decisions"]["selector_top3"][0]
    tree_models = {"RandomForest", "XGBoost", "LightGBM", "CatBoost"}
    assert top1 not in tree_models, (
        f"p≫n 데이터에서 selector top1='{top1}' 가 트리 모델 — 정규화 선형 권고 기대"
    )
