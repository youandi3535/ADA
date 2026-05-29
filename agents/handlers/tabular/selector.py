"""agents.handlers.tabular.selector — 정형 ML/DL 모델 선택 (jh Day 5)."""

from __future__ import annotations

import math
import re
from typing import Any

# ── 모델 후보 풀 ──────────────────────────────────────────────────────────────

_G2_CANDIDATES: dict[str, list[str]] = {
    "g2_ml_light": ["LogisticRegression", "DecisionTree", "GaussianNB", "kNN", "RandomForest"],
    "g2_ml_standard": ["XGBoost", "LightGBM", "CatBoost"],
    "g2_ml_heavy": ["XGBoost+FLAML", "LightGBM+FLAML", "CatBoost+FLAML"],
    "g2_dl_light": ["TabPFN", "MLP"],
    "g2_dl_heavy": ["FTTransformer", "TabTransformer"],
}

_DEFAULT_SEEDS: dict[str, dict] = {
    "XGBoost": {"n_estimators": 100, "max_depth": 6, "learning_rate": 0.1, "subsample": 0.8},
    "LightGBM": {"n_estimators": 100, "num_leaves": 31, "learning_rate": 0.1, "min_child_samples": 20},
    "CatBoost": {"iterations": 100, "depth": 6, "learning_rate": 0.1},
    "XGBoost+FLAML": {"n_estimators": 100, "max_depth": 6, "learning_rate": 0.1, "subsample": 0.8},
    "LightGBM+FLAML": {"n_estimators": 100, "num_leaves": 31, "learning_rate": 0.1, "min_child_samples": 20},
    "CatBoost+FLAML": {"iterations": 100, "depth": 6, "learning_rate": 0.1},
    "RandomForest": {"n_estimators": 100, "max_depth": None, "min_samples_split": 2},
    "LogisticRegression": {"C": 1.0, "penalty": "l2", "max_iter": 100},
    "DecisionTree": {"max_depth": 5, "min_samples_split": 2},
    "GaussianNB": {},
    "kNN": {"n_neighbors": 5},
    "TabPFN": {"n_estimators": 3},
    "MLP": {"hidden_layer_sizes": [128, 64, 32], "max_iter": 100, "learning_rate_init": 0.001},
    "FTTransformer": {"n_blocks": 3, "d_token": 192, "dropout": 0.1},
    "TabTransformer": {"n_heads": 8, "n_blocks": 6, "dropout": 0.1},
    "KMeans": {"n_clusters": 3},
    "DBSCAN": {"eps": 0.5, "min_samples": 5},
    "CoxPHFitter": {"penalizer": 0.1},
    "MultiOutputRegressor": {},
    "MultiOutputClassifier": {},
}

# ── 모델 분류 집합 ────────────────────────────────────────────────────────────

_LIGHT_MODELS = frozenset({"LogisticRegression", "DecisionTree", "GaussianNB", "kNN", "RandomForest"})
_HEAVY_MODELS = frozenset({"FTTransformer", "TabTransformer", "XGBoost+FLAML", "LightGBM+FLAML", "CatBoost+FLAML"})
_DL_MODELS = frozenset({"FTTransformer", "TabTransformer", "TabPFN", "MLP"})
_SUPPORTS_CLASS_WEIGHT = frozenset(
    {
        "LogisticRegression",
        "RandomForest",
        "XGBoost",
        "LightGBM",
        "CatBoost",
        "XGBoost+FLAML",
        "LightGBM+FLAML",
        "CatBoost+FLAML",
    }
)
_SUPPORTS_THRESHOLD = frozenset(
    {
        "LogisticRegression",
        "XGBoost",
        "LightGBM",
        "CatBoost",
        "XGBoost+FLAML",
        "LightGBM+FLAML",
        "CatBoost+FLAML",
    }
)
_INTERPRETABLE = frozenset({"LogisticRegression", "LightGBM", "XGBoost", "LightGBM+FLAML"})
_FAIR_MODELS = frozenset({"LogisticRegression"})


# ── state 헬퍼 ────────────────────────────────────────────────────────────────


def _profile(state: Any) -> dict:
    p = getattr(state, "data_profile", None)
    return p if isinstance(p, dict) else {}


def _extras(state: Any) -> dict:
    ce = getattr(state, "category_extras", {}) or {}
    return ce.get("tabular", {})


def _baseline(state: Any) -> dict:
    bl = _extras(state).get("eda_baseline")
    return bl if isinstance(bl, dict) else {}


def _artifacts(state: Any) -> dict:
    return _extras(state).get("preprocess_artifacts", {})


def _hints(state: Any) -> dict:
    h = getattr(state, "selector_hints", None)
    return h if isinstance(h, dict) else {}


def _gate(state: Any) -> tuple[str | None, str | None]:
    gr = getattr(state, "gate_responses", {}) or {}
    return gr.get("g1"), gr.get("g2")


def _intent(state: Any) -> str:
    raw = getattr(state, "user_intent", "") or ""
    return re.sub(r"<PII:[^>]+>", "", raw).lower()


def _has_kw(state: Any, *words: str) -> bool:
    text = _intent(state)
    return any(w in text for w in words)


def _clip(v: float) -> float:
    return max(0.0, min(1.0, v))


def _n_rows(state: Any) -> int:
    return int(_profile(state).get("rows", 0))


def _n_classes(state: Any) -> int:
    cd = _profile(state).get("class_distribution")
    return len(cd) if isinstance(cd, dict) else 0


# ── 그룹 A: top-N 결정 신호 4개 ─────────────────────────────────────────────


def _sig_complexity(state: Any) -> float:
    force = _hints(state).get("force_signal", {}).get("complexity")
    if force is not None:
        return _clip(float(force))

    bl = _baseline(state)
    cv = bl.get("cv_score")
    if cv is None:
        base = 0.5
    elif cv >= 0.90:
        base = 0.1
    elif cv >= 0.80:
        base = 0.3
    elif cv >= 0.70:
        base = 0.5
    elif cv >= 0.60:
        base = 0.7
    else:
        base = 0.9

    bonus = 0.0
    top_feat = bl.get("top_feature_concentration")
    nonlin = bl.get("nonlinearity_estimate")
    if top_feat is not None and top_feat < 0.40:
        bonus += 0.1
    if nonlin is not None and nonlin > 0.15:
        bonus += 0.1
    return _clip(base + bonus)


def _sig_variety(state: Any, g2_choice: str | None) -> float:
    force = _hints(state).get("force_signal", {}).get("variety")
    if force is not None:
        return _clip(float(force))

    if g2_choice in ("g2_dl_light", "g2_dl_heavy"):
        base = 0.7
    elif g2_choice == "g2_ml_heavy":
        base = 0.6
    elif g2_choice == "g2_ml_standard":
        base = 0.4
    else:
        base = 0.3

    if _n_rows(state) < 500:
        base -= 0.2
    return _clip(base)


def _sig_quality(state: Any) -> float:
    force = _hints(state).get("force_signal", {}).get("quality")
    if force is not None:
        return _clip(float(force))

    profile = _profile(state)
    s = 0.1
    entropy = float(profile.get("class_entropy_ratio", 1.0) or 1.0)
    if entropy < 0.3:
        s += 0.3
    if int(profile.get("rows", 0)) > 0:
        if float(profile.get("missing_ratio", 0.0) or 0.0) > 0.20:
            s += 0.2
    if float(profile.get("outlier_ratio", 0.0) or 0.0) > 0.10:
        s += 0.2
    n_cols = int(profile.get("columns", 0))
    if n_cols > 0:
        card_levels = profile.get("cardinality_levels") or {}
        high_card = sum(1 for v in card_levels.values() if v in ("high", "very_high"))
        if high_card / n_cols > 0.30:
            s += 0.2
    return _clip(s)


def _sig_size(state: Any) -> float:
    force = _hints(state).get("force_signal", {}).get("size")
    if force is not None:
        return _clip(float(force))

    n = _n_rows(state)
    if n < 500:
        return 0.1
    if n < 5000:
        return 0.3
    if n < 50000:
        return 0.6
    if n < 500000:
        return 0.85
    return 1.0


def _top_n_from_score(top_n_score: float) -> int:
    if top_n_score < 0.30:
        return 1
    if top_n_score < 0.50:
        return 2
    if top_n_score < 0.70:
        return 3
    if top_n_score < 0.85:
        return 4
    return 5


# ── 그룹 B: 모델 가중치 신호 5개 ─────────────────────────────────────────────


def _sig_interpretability(state: Any, g1_choice: str | None) -> float:
    force = _hints(state).get("force_signal", {}).get("interpretability")
    if force is not None:
        return _clip(float(force))

    s = 0.3
    if _has_kw(state, "이유", "원인", "왜", "설명", "투명", "explain", "interpret"):
        s += 0.3
    if g1_choice in ("g1_importance", "g1_hybrid"):
        s += 0.2
    # 컬럼명 의료 패턴: profile의 column_names 힌트 (없으면 0)
    col_names = _profile(state).get("column_names") or []
    med_pat = re.compile(r"(patient|diagnosis|symptom|medical|clinical|drug|disease)", re.I)
    if any(med_pat.search(str(c)) for c in col_names):
        s += 0.2
    return _clip(s)


def _sig_precision(state: Any) -> float:
    force = _hints(state).get("force_signal", {}).get("precision")
    if force is not None:
        return _clip(float(force))

    s = 0.3
    if _has_kw(state, "정확", "놓치면", "오답", "recall", "precision"):
        s += 0.3
    if float(_profile(state).get("class_entropy_ratio", 1.0) or 1.0) < 0.3:
        s += 0.3
    return _clip(s)


def _sig_speed(state: Any) -> float:
    force = _hints(state).get("force_signal", {}).get("speed")
    if force is not None:
        return _clip(float(force))

    s = 0.3
    if _has_kw(state, "빠른", "실시간", "즉시", "간단히", "fast", "quick"):
        s += 0.3
    if _n_rows(state) < 500:
        s += 0.2
    return _clip(s)


def _sig_fairness(state: Any) -> float:
    force = _hints(state).get("force_signal", {}).get("fairness")
    if force is not None:
        return _clip(float(force))

    s = 0.3
    if _has_kw(state, "공정", "차별", "편향", "fair", "bias"):
        s += 0.3
    col_names = _profile(state).get("column_names") or []
    demo_pat = re.compile(r"(age|gender|race|ethnicity|sex|religion|nationality)", re.I)
    if any(demo_pat.search(str(c)) for c in col_names):
        s += 0.3
    return _clip(s)


def _sig_cost(state: Any) -> float:
    force = _hints(state).get("force_signal", {}).get("cost_sensitivity")
    if force is not None:
        return _clip(float(force))

    s = 0.3
    if _has_kw(state, "오답 비용", "false positive", "비용"):
        s += 0.3
    if float(_profile(state).get("class_imbalance_ratio", 1.0) or 1.0) >= 50:
        s += 0.3
    return _clip(s)


# ── 그룹 B 모델 가중치 적용 ──────────────────────────────────────────────────


def _apply_group_b(
    model_scores: dict[str, float],
    signals_b: dict[str, float],
) -> tuple[dict[str, float], dict[str, float]]:
    adjusted: dict[str, float] = {}
    applied: dict[str, float] = {}

    for model, base in model_scores.items():
        adj = 0.0
        if signals_b["interpretability"] >= 0.7:
            if model in ("LightGBM", "LightGBM+FLAML", "LogisticRegression"):
                adj += 0.25  # LightGBM/LogReg 우선 (해석성 top1)
            elif model in _INTERPRETABLE:
                adj += 0.20
            if model in _DL_MODELS:
                adj -= 0.20
        if signals_b["precision"] >= 0.7:
            if model in _SUPPORTS_CLASS_WEIGHT:
                adj += 0.15
        if signals_b["speed"] >= 0.7:
            if model in _LIGHT_MODELS:
                adj += 0.20
            if model in _HEAVY_MODELS:
                adj -= 0.30
        if signals_b["fairness"] >= 0.7:
            if model in _FAIR_MODELS:
                adj += 0.15
        if signals_b["cost_sensitivity"] >= 0.7:
            if model in _SUPPORTS_THRESHOLD:
                adj += 0.15
        adjusted[model] = _clip(base + adj)
        if adj != 0.0:
            applied[model] = round(adj, 4)

    return adjusted, applied


# ── FLAML warm-start ──────────────────────────────────────────────────────────


def _compute_recipe_match(recipe: dict, state: Any) -> float:
    profile = _profile(state)
    n_curr = int(profile.get("rows", 0))
    cls_curr = _n_classes(state)
    imb_curr = float(profile.get("class_imbalance_ratio", 1.0) or 1.0)
    feat_curr = int(profile.get("columns", 0))

    rp = recipe.get("profile") or {}
    n_rec = int(rp.get("rows", n_curr) or n_curr)
    cls_rec = int(rp.get("n_classes", cls_curr) or cls_curr)
    imb_rec = float(rp.get("imbalance_ratio", imb_curr) or imb_curr)
    feat_rec = int(rp.get("columns", feat_curr) or feat_curr)

    if n_curr > 0 and n_rec > 0:
        sim_rows = _clip(1 - abs(math.log10(n_curr) - math.log10(n_rec)) / 5)
    else:
        sim_rows = 0.5
    sim_classes = 1.0 if cls_curr == cls_rec else 0.5
    sim_imb = _clip(1 - abs(imb_curr - imb_rec) / 10)
    sim_feat = _clip(1 - abs(feat_curr - feat_rec) / 100) if feat_curr > 0 else 0.5

    profile_sim = sim_rows * 0.30 + sim_classes * 0.25 + sim_imb * 0.25 + sim_feat * 0.20
    quality = float(recipe.get("quality_score", 0.5) or 0.5)
    return _clip(profile_sim * 0.7 + quality * 0.3)


def _add_noise(params: dict, noise_amount: float) -> dict:
    import random  # noqa: WPS433

    result = {}
    for k, v in params.items():
        if isinstance(v, float):
            result[k] = max(0.0, v * (1 + random.uniform(-noise_amount, noise_amount)))
        elif isinstance(v, int) and v > 1:
            delta = max(1, int(v * noise_amount))
            result[k] = max(1, v + random.randint(-delta, delta))
        else:
            result[k] = v
    return result


def _warm_start_for_model(
    model: str,
    recipes: list[dict],
    state: Any,
    disable: bool = False,
) -> dict:
    seed = dict(_DEFAULT_SEEDS.get(model, {}))
    if disable or not recipes:
        seed["_source"] = "default"
        seed["_recipe_score"] = 0.0
        return seed

    model_recipes = [r for r in recipes if r.get("model") == model] or recipes
    best_recipe, best_score = None, -1.0
    for r in model_recipes:
        ms = _compute_recipe_match(r, state)
        if ms > best_score:
            best_score, best_recipe = ms, r

    if best_recipe is None or best_score < 0.5:
        seed["_source"] = "default"
        seed["_recipe_score"] = round(best_score, 4) if best_recipe else 0.0
        return seed

    best_params = dict(best_recipe.get("best_params", {}))
    h = best_recipe.get("hash", "unknown")
    if best_score >= 0.7:
        return {**best_params, "_source": f"recipe_{h}", "_recipe_score": round(best_score, 4)}
    noise = (0.7 - best_score) * 0.3
    return {
        **_add_noise(best_params, noise),
        "_source": f"recipe_{h}_with_noise",
        "_recipe_score": round(best_score, 4),
    }


# ── fallback g2 추정 (Day 4 weight_score 알고리즘 재활용) ─────────────────────


def _fallback_g2_card(state: Any) -> str:
    bl = _baseline(state)
    cv = bl.get("cv_score")
    top_feat = bl.get("top_feature_concentration")
    nonlin = bl.get("nonlinearity_estimate")
    hints = _hints(state)

    if cv is None:
        comp_base = 0.5
    elif cv >= 0.90:
        comp_base = 0.1
    elif cv >= 0.80:
        comp_base = 0.3
    elif cv >= 0.70:
        comp_base = 0.5
    elif cv >= 0.60:
        comp_base = 0.7
    else:
        comp_base = 0.9
    bonus = 0.0
    if top_feat is not None and top_feat < 0.40:
        bonus += 0.1
    if nonlin is not None and nonlin > 0.15:
        bonus += 0.1
    complexity = _clip(comp_base + bonus)

    size = _sig_size(state)
    quality = _sig_quality(state)
    resource = 0.3 if hints.get("time_constraint") is not None else 0.7

    ws = _clip(size * 0.20 + complexity * 0.45 + quality * 0.20 + resource * 0.15)

    n = _n_rows(state)
    n_cls = _n_classes(state)
    dl_min = max(5000, int(_profile(state).get("columns", 0)) * 100)
    dl_min = max(dl_min, 5000)
    dl_max_cls = min(10, math.ceil(math.log2(max(n, 2))) + 3)
    dl_ok = n >= dl_min and (n_cls == 0 or n_cls <= dl_max_cls)

    if ws < 0.30:
        return "g2_ml_light"
    if ws < 0.55:
        return "g2_ml_standard"
    if ws < 0.75:
        return "g2_ml_heavy"
    if ws < 0.90 and dl_ok:
        return "g2_dl_light"
    if dl_ok:
        return "g2_dl_heavy"
    return "g2_ml_standard"


# ── 특수 카드 분기 ────────────────────────────────────────────────────────────


def _special_result(
    top_models: list[str],
    rationale: str,
    recipes: list[dict],
    state: Any,
    signals_meta: dict,
    special_key: str,
    extra_signals: dict | None = None,
) -> dict:
    hints = _hints(state)
    disable_ws = bool(hints.get("disable_warm_start", False))
    seeds = {m: _warm_start_for_model(m, recipes, state, disable_ws) for m in top_models}
    citations = [r["hash"] for r in recipes[:3] if r.get("hash")]
    sel_signals: dict = {"special_branch": special_key, **signals_meta}
    if extra_signals:
        sel_signals.update(extra_signals)
    return {
        "top_models": top_models,
        "model_candidates": top_models,
        "rationale": rationale,
        "citations": citations,
        "warm_start_seed": seeds,
        "selector_signals": sel_signals,
    }


def _segment_selection(state: Any, signals: dict, recipes: list[dict]) -> dict:
    n = _n_rows(state)
    k = _hints(state).get("segment_k_override") or max(2, min(8, int(math.sqrt(max(n, 4) / 10)) + 1))
    top_models = ["KMeans", "DBSCAN"]
    kb_note = " KB 미사용 (cold start, 기본 시드 활용)." if not recipes else ""
    rationale = f"군집 분석 시나리오입니다. KMeans (K={k}) 와 DBSCAN 으로 데이터 구조를 탐색합니다.{kb_note}"
    result = _special_result(top_models, rationale, recipes, state, signals, "g1_segment", {"k_clusters": int(k)})
    result["warm_start_seed"]["KMeans"]["n_clusters"] = int(k)
    return result


def _survival_selection(state: Any, signals: dict, recipes: list[dict]) -> dict:
    kb_note = " KB 미사용 (cold start, 기본 시드 활용)." if not recipes else ""
    rationale = f"생존 분석 시나리오입니다. CoxPHFitter (비례 위험 모델)로 생존 함수를 추정합니다.{kb_note}"
    return _special_result(["CoxPHFitter"], rationale, recipes, state, signals, "g1_survival_analysis")


def _multi_target_selection(state: Any, signals: dict, recipes: list[dict]) -> dict:
    task = getattr(state, "task", "auto") or "auto"
    model = "MultiOutputRegressor" if task == "regression" else "MultiOutputClassifier"
    kb_note = " KB 미사용 (cold start, 기본 시드 활용)." if not recipes else ""
    rationale = f"멀티 타겟 예측 시나리오입니다. {model}로 복수 타겟을 동시 예측합니다.{kb_note}"
    return _special_result([model], rationale, recipes, state, signals, "g1_multi_target")


# ── 공개 함수 ─────────────────────────────────────────────────────────────────


def score(state: Any, recipes: list[dict[str, Any]]) -> dict[str, Any]:
    """데이터 적응적 모델 후보 top-N + FLAML warm-start 시드 반환.

    state mutation 없음. dispatcher가 with_update.
    """
    # 단계 1: 입력 안전 추출
    recipes = recipes or []
    hints = _hints(state)
    g1_choice, g2_choice = _gate(state)
    disable_ws = bool(hints.get("disable_warm_start", False))

    # 단계 2: 그룹 A·B 신호 계산
    complexity = _sig_complexity(state)
    variety = _sig_variety(state, g2_choice)
    quality = _sig_quality(state)
    size = _sig_size(state)

    interpretability = _sig_interpretability(state, g1_choice)
    precision = _sig_precision(state)
    speed = _sig_speed(state)
    fairness = _sig_fairness(state)
    cost_sensitivity = _sig_cost(state)

    signals_a = {
        "complexity": round(complexity, 4),
        "variety": round(variety, 4),
        "quality": round(quality, 4),
        "size": round(size, 4),
    }
    signals_b = {
        "interpretability": round(interpretability, 4),
        "precision": round(precision, 4),
        "speed": round(speed, 4),
        "fairness": round(fairness, 4),
        "cost_sensitivity": round(cost_sensitivity, 4),
    }
    signals_meta = {**signals_a, **signals_b}

    # 단계 3: 특수 카드 분기
    if g1_choice == "g1_segment":
        return _segment_selection(state, signals_meta, recipes)
    if g1_choice == "g1_survival_analysis":
        return _survival_selection(state, signals_meta, recipes)
    if g1_choice == "g1_multi_target":
        return _multi_target_selection(state, signals_meta, recipes)

    # 단계 4: g2 카드 → 후보 매핑
    fallback_used: dict | None = None
    if g2_choice and g2_choice in _G2_CANDIDATES:
        candidates = list(_G2_CANDIDATES[g2_choice])
    else:
        fb_card = _fallback_g2_card(state)
        candidates = list(_G2_CANDIDATES[fb_card])
        fallback_used = {"reason": "g2_choice missing", "fallback_card": fb_card}

    disabled = list(hints.get("disable_model") or [])
    candidates = [c for c in candidates if c not in disabled] or ["XGBoost", "LightGBM"]

    # 단계 5: 그룹 B → 모델 가중치 조정
    base_scores = {m: 0.5 for m in candidates}
    adjusted_scores, applied_adj = _apply_group_b(base_scores, signals_b)

    # 단계 6: 그룹 A → top-N 결정
    top_n_score = _clip(complexity * 0.40 + variety * 0.25 + quality * 0.20 + size * 0.15)
    n_rows_val = _n_rows(state)
    top_n_max = max(1, min(5, math.ceil(n_rows_val / 10000) + 2)) if n_rows_val > 0 else 5
    top_n = min(
        hints.get("top_n_override") or _top_n_from_score(top_n_score),
        top_n_max,
        len(candidates),
    )
    top_n = max(1, top_n)
    if speed >= 0.8:
        top_n = max(1, top_n - 1)

    # 단계 7: g1 카드 가중치 조정
    if g1_choice in ("g1_importance", "g1_hybrid"):
        for lgbm in ("LightGBM", "LightGBM+FLAML"):
            if lgbm in adjusted_scores:
                adjusted_scores[lgbm] = _clip(adjusted_scores[lgbm] + 0.30)
                applied_adj[lgbm] = applied_adj.get(lgbm, 0.0) + 0.30
                break

    # force_top_models hint
    force_top = hints.get("force_top_models")
    if force_top:
        forced = [m for m in force_top if m in candidates]
        rest = [m for m in sorted(adjusted_scores, key=adjusted_scores.__getitem__, reverse=True) if m not in forced]
        top_models = (forced + rest)[:top_n]
    else:
        top_models = sorted(adjusted_scores, key=adjusted_scores.__getitem__, reverse=True)[:top_n]

    # 단계 8: warm-start 시드
    warm_start_seed = {m: _warm_start_for_model(m, recipes, state, disable_ws) for m in top_models}
    citations = [r["hash"] for r in recipes[:3] if r.get("hash")]

    # R-501: KB 미사용 명시
    kb_note = "" if citations else " KB 미사용 (cold start, 기본 시드 활용)."

    rationale = (
        f"모델 후보 {len(top_models)}개 선정되었습니다. "
        f"학습 난이도(complexity {complexity:.2f})와 "
        f"모델 다양성(variety {variety:.2f})으로 결정했습니다."
    )
    if interpretability >= 0.7:
        rationale += " 해석 가능 모델(LightGBM/LogReg)을 우선합니다."
    if speed >= 0.7:
        rationale += " 속도 우선으로 가벼운 모델이 선택되었습니다."
    if precision >= 0.7:
        rationale += " class_weight 지원 모델 우선 적용됩니다."
    rationale += kb_note

    # 단계 2-C: selector_signals 기록
    selector_signals: dict[str, Any] = {
        "group_a_top_n": {**signals_a, "weighted_score": round(top_n_score, 4), "decided_n": top_n},
        "group_b_weights": {**signals_b, "applied_to_models": applied_adj},
        "extraction_sources": {"eda_baseline_used": bool(_baseline(state))},
    }
    if fallback_used:
        selector_signals["fallback_used"] = fallback_used

    # 단계 9: 반환
    assert 1 <= len(top_models) <= 5

    return {
        "top_models": top_models,
        "model_candidates": candidates,
        "rationale": rationale,
        "citations": citations,
        "warm_start_seed": warm_start_seed,
        "selector_signals": selector_signals,
    }
