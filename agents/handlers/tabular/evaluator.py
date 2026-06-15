"""agents.handlers.tabular.evaluator — 정형 평가 (jh 담당).

기본 임계: tabular_ml val_f1>=0.65, val_accuracy>=0.70. tabular_dl val_f1>=0.70.

Day 11 (jh) — 다음 3가지 보강:
  1. 베이스라인 격차 (improvement_over_baseline) — "강모델이 더미보다 얼마나 나은가"
  2. CV 통계 (cv_stats) — best_model 의 fold 평균·표준편차 노출 (신뢰구간)
  3. 격차의 통계적 유의성 (lift_significant) — lift > 2 * baseline_cv_std 면 의미있음

Day 12 (jh) — 봉인된 test holdout 으로 최종 판정 (누수 완전 차단):
  - 기존: best_model.metrics(=val 점수)로 passed 판정 → 재시도(튜닝) 과정에서
    val 을 거듭 들여다보며 사실상 val 에 과적합될 수 있었음.
  - 변경: val 통과했거나 마지막 재시도일 때만, best_model 을 train+val 에 재적합한
    뒤 봉인된 test 로 1회 평가해 passed 를 판정. 재시도 중(미통과·여유 있음)에는
    test 를 보지 않고 val 로만 판정해 test 불가침을 보장.
  - test 경계는 agents.training_executor._leakage_split_bounds 가 반환하는
    (n_tr, n_val) 로 읽는다. parquet 행 순서는 [train | val | test].
    (해당 심볼이 아직 없거나 메타가 없으면 None → val 기반 2분할 폴백.)

CV 평가는 비용을 고려해 다음 가드:
  - n_rows > 50000 → skip (대용량은 hold-out 으로 충분)
  - tabular_dl → skip (GPU 비용 큼)
  - pipeline.evaluate_with_cv 미존재 (다른 카테고리) → skip
  - CV 데이터도 train+val(=[:n_tr+n_val]) 로 제한 (test 제외 — 봉인 유지).
"""

from __future__ import annotations

from typing import Any

# Day 11 (jh) — val_r2 임계 추가 (C4 해소). 회귀 task 에서 evaluator 게이트가
# 공허 통과하던 문제를 해결. Day10 test_e2e.py 가 직접 assert 하던 보호 장치를
# evaluator 본체로 흡수.
THRESHOLDS_BY_CAT = {
    "tabular_ml": {"val_f1": 0.55, "val_r2": 0.30},
    "tabular_dl": {"val_f1": 0.60},
}

# Day 11 (jh) — improvement_over_baseline 계산에 사용할 metric 우선순위.
# 분류는 val_f1 우선, 회귀는 val_r2 우선.
_BASELINE_COMPARE_METRICS = ("val_f1", "val_accuracy", "val_r2")

# Day 11 (jh) — CV 평가 가드. 큰 데이터는 hold-out 으로 충분, CV 비용 폭주 방지.
_CV_MAX_ROWS = 50_000
_CV_N_SPLITS = 5
# 격차가 baseline_std 의 몇 배 이상이면 통계적으로 유의로 표시 (rule-of-thumb)
_SIGNIFICANCE_THRESHOLD_K = 2.0


def _find_baseline_metrics(state: Any) -> dict[str, Any]:
    """trained_models 에서 '기준(baseline)' = Dummy(naive) 1개 선택.

    HJ 2026-06-14 — 사용자 지시: 기준은 Dummy 다. 경쟁 모델(LogisticRegression/Ridge)을
    기준으로 삼으면 그건 '기준'이 아니다(다른 모델의 임계치를 기준 삼는 셈). 따라서 4단계
    (metrics_aggregator)와 동일하게 5단계 격차(improvement_over_baseline)·통계적 유의성
    (lift_significant)도 **Dummy 대비**로 판정한다. LR/Ridge 는 비교군에서 제외.
    Dummy 가 없으면(일부 카테고리) 기준 없음 → {} (유의성 게이트 미적용 = 미패널티).
    """
    trained = getattr(state, "trained_models", None) or []
    dummy_candidates = [
        (m.get("model_name"), (m.get("metrics") or {}))
        for m in trained
        if str(m.get("model_name", "")).lower().startswith("dummy")
    ]
    if not dummy_candidates:
        return {}

    # Dummy 가 여럿이면 가장 강한 Dummy(가장 보수적 기준) 선택.
    def _key(item: tuple[str, dict]) -> float:
        _, mtr = item
        for k in _BASELINE_COMPARE_METRICS:
            v = mtr.get(k)
            if v is not None:
                return float(v)
        return float("-inf")

    name, metrics = max(dummy_candidates, key=_key)
    return {"name": name, "metrics": dict(metrics)}


def _compute_improvement(best_metrics: dict, baseline_metrics: dict) -> dict[str, Any]:
    """best vs baseline 격차 — metric 별 lift 와 대표 lift_primary 반환."""
    if not best_metrics or not baseline_metrics:
        return {}
    lift: dict[str, float] = {}
    for k in _BASELINE_COMPARE_METRICS:
        bv = best_metrics.get(k)
        bb = baseline_metrics.get(k)
        if bv is not None and bb is not None:
            try:
                lift[k] = round(float(bv) - float(bb), 4)
            except Exception:
                pass
    # 대표 lift: 분류는 val_f1, 회귀는 val_r2
    primary_metric = None
    primary_lift = None
    for k in ("val_f1", "val_r2", "val_accuracy"):
        if k in lift:
            primary_metric = k
            primary_lift = lift[k]
            break
    return {
        "lift_by_metric": lift,
        "primary_metric": primary_metric,
        "primary_lift": primary_lift,
    }


def _resolve_task_for_cv(state: Any) -> str:
    """state 기반 task 추정 — pipeline.evaluate 시그니처와 동일."""
    task = getattr(state, "task", "auto")
    if task in ("classification", "regression"):
        return task
    profile = state.data_profile or {}
    cd = profile.get("class_distribution") or {}
    if cd and len(cd) <= 50:
        return "classification"
    return "regression"


def _read_leakage_bounds(state: Any) -> tuple[int, int] | None:
    """봉인된 test 경계 (n_tr, n_val) 를 training_executor 에서 읽는다.

    parquet 행 순서는 [train | val | test] 이므로:
      - train+val 슬라이스 : [: n_tr + n_val]
      - test 슬라이스       : [n_tr + n_val :]

    _leakage_split_bounds 심볼이 아직 없거나(ImportError) 메타가 없으면 None →
    호출측은 test 격리를 건너뛰고 기존 val 기반 동작으로 폴백한다 (하위호환).
    """
    try:
        from agents.training_executor import _leakage_split_bounds  # type: ignore
    except Exception:
        return None
    try:
        bounds = _leakage_split_bounds(state)
    except Exception:
        return None
    if not bounds:
        return None
    try:
        n_tr, n_val = int(bounds[0]), int(bounds[1])
    except Exception:
        return None
    if n_tr <= 0 or n_val <= 0:
        return None
    return (n_tr, n_val)


def _should_run_cv(state: Any) -> bool:
    """CV 가드 — 데이터 크면/DL/지원 안되면 skip.

    Day 11 (jh) 추가: state.trained_models 비어있으면 운영 흐름이 아닌
    단위/단발 테스트 시나리오로 간주 → skip (CV 비용 0). 운영에선
    training_executor 가 항상 trained_models 채우므로 영향 없음.
    """
    if state.category != "tabular_ml":
        return False
    n_rows = int((state.data_profile or {}).get("rows", 0))
    if n_rows > _CV_MAX_ROWS:
        return False
    # 운영 흐름이 아니면 (trained_models 비어있으면) CV skip
    trained = getattr(state, "trained_models", None) or []
    if not trained:
        return False
    return True


def _compute_cv_stats_leakage_safe(state: Any, model_name: str, params: dict) -> dict[str, Any]:
    """Fix 5 (jh/HJ 2026-06-15) — 폴드마다 raw 에서 전처리 재적합한 누수 없는 CV.

    기존 _compute_cv_stats 는 '이미 전처리된(스케일된) 행렬'을 받아 KFold 재분할만 했다.
    그러면 스케일/인코딩 통계가 train 전체로 한 번 fit 된 값이라 fold 간에 새어, 스케일
    민감 모델(LR/Ridge)의 CV 평균을 부풀리고 baseline_cv_std 를 줄여 유의성 판정을 왜곡했다.
    여기선 raw 데이터를 다시 읽어 각 fold 마다 train 으로만 fit(apply) → val 은 transform-only
    (preprocessor.fit_transform_train_val) 한 뒤 평가 → fold 간 누수 0.

    실패/미지원(raw 로드 실패·plan 없음·tabular 아님 등)이면 {} 반환 → 호출측이 기존
    행렬 CV 로 폴백(무회귀). 모든 예외를 삼킨다.
    """
    try:
        cat = getattr(state, "category", "") or ""
        if not cat.startswith("tabular"):
            return {}
        plan = getattr(state, "preprocessing_plan", None) or []
        if not plan:
            return {}
        import numpy as np  # noqa: WPS433
        from sklearn.model_selection import KFold, StratifiedKFold

        from agents.handlers.common.shared import load_dataframe_from_state
        from agents.handlers.tabular.preprocessor import fit_transform_train_val
        from agents.training_executor import _split_xy
        from pipelines.factory import PipelineFactory

        target = getattr(state, "target_column", None)
        df_raw = load_dataframe_from_state(state, prefer_processed=False)
        if df_raw is None or not target or target not in df_raw.columns:
            return {}
        df_raw = df_raw.reset_index(drop=True)
        if len(df_raw) < (2 * _CV_N_SPLITS):
            return {}
        y_full = df_raw[target]

        pipeline = PipelineFactory.create(state.category)
        if not (hasattr(pipeline, "train") and hasattr(pipeline, "evaluate")):
            return {}
        task = _resolve_task_for_cv(state)
        use_strat = task == "classification" and int(y_full.nunique(dropna=True)) <= 50
        splitter = (
            StratifiedKFold(n_splits=_CV_N_SPLITS, shuffle=True, random_state=42)
            if use_strat
            else KFold(n_splits=_CV_N_SPLITS, shuffle=True, random_state=42)
        )
        split_iter = splitter.split(df_raw, y_full) if use_strat else splitter.split(df_raw)

        fold_metrics: list[dict[str, float]] = []
        all_keys: set[str] = set()
        for tr_idx, val_idx in split_iter:
            df_tr = df_raw.iloc[tr_idx].reset_index(drop=True)
            df_va = df_raw.iloc[val_idx].reset_index(drop=True)
            df_tr_proc, df_va_proc = fit_transform_train_val(df_tr, df_va, plan, state)
            x_tr, y_tr = _split_xy(df_tr_proc, target)
            x_va, y_va = _split_xy(df_va_proc, target)
            if x_tr is None or x_va is None or len(x_tr) == 0 or len(x_va) == 0:
                return {}  # 비정상 → 폴백
            model = pipeline.train(x_tr, y_tr, model_name=model_name, params=params or {})
            m = pipeline.evaluate(model, x_va, y_va, task=task)
            fold_metrics.append({k: float(v) for k, v in m.items() if isinstance(v, (int, float))})
            all_keys.update(fold_metrics[-1].keys())

        if not fold_metrics:
            return {}
        mean_dict: dict[str, float] = {}
        std_dict: dict[str, float] = {}
        for k in all_keys:
            vals = [fm[k] for fm in fold_metrics if k in fm]
            if vals:
                mean_dict[k] = float(np.mean(vals))
                std_dict[k] = float(np.std(vals))
        primary = "val_f1" if task == "classification" else "val_r2"
        return {
            "n_splits": int(_CV_N_SPLITS),
            "fold_metrics": fold_metrics,
            "mean": mean_dict,
            "std": std_dict,
            "primary_metric": primary,
            "primary_mean": float(mean_dict.get(primary, 0.0)),
            "primary_std": float(std_dict.get(primary, 0.0)),
            "leakage_safe_cv": True,
        }
    except Exception:  # noqa: BLE001 — 어떤 실패든 {} → 기존 행렬 CV 폴백(무회귀)
        return {}


def _compute_cv_stats(state: Any, model_name: str, params: dict) -> dict[str, Any]:
    """주어진 모델을 CV 로 재평가 → fold 통계 반환.

    Day 12 (jh): CV 데이터를 train+val(=[:n_tr+n_val]) 로 제한해 봉인된 test 가
    CV 에도 새지 않도록 한다. 경계 메타가 없으면(폴백) 기존처럼 전체 사용.

    Fix 5 (2026-06-15): 누수 없는 폴드별 재전처리 CV 를 우선 시도하고, 실패/미지원 시
    아래 기존 행렬 CV 로 폴백한다(무회귀).

    실패/예외 시 빈 dict (graceful). 운영 회귀 방지를 위해 모든 오류 catch.
    """
    if not _should_run_cv(state):
        return {}
    _ls = _compute_cv_stats_leakage_safe(state, model_name, params)
    if _ls:
        return _ls
    try:
        from agents.handlers.common.shared import load_dataframe_from_state
        from agents.training_executor import _split_xy
        from pipelines.factory import PipelineFactory

        df = load_dataframe_from_state(state)

        # test 제외 — train+val 만 CV 대상 (봉인 유지). 경계 없으면 전체 사용.
        bounds = _read_leakage_bounds(state)
        if bounds is not None:
            n_tr, n_val = bounds
            n_trval = n_tr + n_val
            if 0 < n_trval <= len(df):
                df = df.iloc[:n_trval]

        X, y = _split_xy(df, state.target_column)
        if X is None or y is None or len(X) == 0:
            return {}

        pipeline = PipelineFactory.create(state.category)
        if not hasattr(pipeline, "evaluate_with_cv"):
            return {}

        task = _resolve_task_for_cv(state)
        return (
            pipeline.evaluate_with_cv(
                X,
                y,
                model_name=model_name,
                params=params or {},
                n_splits=_CV_N_SPLITS,
                task=task,
            )
            or {}
        )
    except Exception:
        return {}


def _compute_test_metrics(state: Any, model_name: str, params: dict) -> dict[str, Any]:
    """봉인된 test 로 best_model 을 1회 평가.

    절차: parquet 의 [train | val | test] 행 순서를 이용해
      - train+val = [: n_tr+n_val] 로 best_model 재적합
      - test      = [n_tr+n_val :] 로 1회 평가
    하고 pipeline.evaluate 가 반환한 metric dict (val_* 키 그대로) 를 돌려준다.

    경계 메타가 없거나(폴백) 데이터가 비정상이면 빈 dict 반환 → 호출측이 val
    기반 판정을 유지한다. 모든 예외를 catch 해 운영 회귀를 막는다.
    """
    bounds = _read_leakage_bounds(state)
    if bounds is None:
        return {}
    try:
        from agents.handlers.common.shared import load_dataframe_from_state
        from agents.training_executor import _split_xy
        from pipelines.factory import PipelineFactory

        n_tr, n_val = bounds
        n_trval = n_tr + n_val

        df = load_dataframe_from_state(state)
        n_rows = len(df)
        # test 가 실제로 존재해야 평가 가능 ([train|val|test] 순서 가정).
        if n_trval <= 0 or n_trval >= n_rows:
            return {}

        df_fit = df.iloc[:n_trval]
        df_test = df.iloc[n_trval:]
        if len(df_test) == 0:
            return {}

        X_fit, y_fit = _split_xy(df_fit, state.target_column)
        X_test, y_test = _split_xy(df_test, state.target_column)
        if X_fit is None or y_fit is None or len(X_fit) == 0:
            return {}
        if X_test is None or y_test is None or len(X_test) == 0:
            return {}

        pipeline = PipelineFactory.create(state.category)
        task = _resolve_task_for_cv(state)

        # best_model 을 train+val 에 재적합 후 test 1회 평가.
        model = pipeline.train(X_fit, y_fit, model_name=model_name, params=params or {})
        metrics = pipeline.evaluate(model, X_test, y_test, task=task) or {}
        return dict(metrics)
    except Exception:
        return {}


def _add_significance(improvement: dict, baseline_cv_std: float | None) -> dict:
    """lift 가 baseline_cv_std 의 K 배 이상이면 significant 마킹.

    baseline_cv_std 가 0 이거나 None 이면 'unknown' (판단 불가).
    """
    if not improvement:
        return improvement
    out = dict(improvement)
    lift = out.get("primary_lift")
    if lift is None:
        return out
    if baseline_cv_std is None or baseline_cv_std == 0:
        out["lift_significant"] = None  # 판단 불가
        out["baseline_cv_std"] = baseline_cv_std
        out["significance_threshold_k"] = _SIGNIFICANCE_THRESHOLD_K
        return out
    threshold = _SIGNIFICANCE_THRESHOLD_K * float(baseline_cv_std)
    out["lift_significant"] = bool(abs(float(lift)) >= threshold)
    out["baseline_cv_std"] = float(baseline_cv_std)
    out["significance_threshold_k"] = _SIGNIFICANCE_THRESHOLD_K
    return out


def _check_violations(metrics: dict, thr: dict) -> list[str]:
    """metric dict 를 임계 dict 와 비교해 위반 목록 반환.

    test 평가도 pipeline.evaluate 가 val_* 키로 반환하므로 동일 임계를 그대로 적용.
    """
    violations: list[str] = []
    for k, t in thr.items():
        v = metrics.get(k)
        if v is not None and float(v) < t:
            violations.append(f"{k}<{t} (got {v:.3f})")
    return violations


# HJ 2026-06-13 — 데이터 인지형(adaptive) 임계. 단일 고정값(THRESHOLDS_BY_CAT)의 한계
#   (균형 이진엔 0.55≈랜덤, 불균형엔 weighted-F1 이 다수 클래스로 부풀려 무의미)를 보완.
_RANDOM_MARGIN = 0.15  # 무작위/기준선 위로 요구하는 절대 마진
_IMBALANCE_SWITCH = 1.5  # class_imbalance_ratio 이상이면 weighted-F1 → ROC-AUC 로 전환


def _is_regression(state: Any, metrics: dict) -> bool:
    """회귀 여부 — metrics 우선(val_r2 만 있고 val_f1 없음), 없으면 task 추정."""
    if "val_r2" in metrics and "val_f1" not in metrics:
        return True
    return _resolve_task_for_cv(state) == "regression"


def _n_classes(state: Any, metrics: dict) -> int:
    """클래스 수 — class_distribution → val_f1_per_class → 이진 가정 순 폴백."""
    prof = getattr(state, "data_profile", None) or {}
    cd = prof.get("class_distribution")
    if isinstance(cd, dict) and cd:
        return max(2, len(cd))
    pc = metrics.get("val_f1_per_class")
    if isinstance(pc, dict) and pc:
        return max(2, len(pc))
    return 2


def resolve_thresholds(state: Any) -> tuple[dict[str, float], str]:
    """데이터 특성(task/클래스수/불균형)에 맞춰 (지표→임계, 한국어 근거) 동적 결정.

    - 회귀: R² 는 분산정규화(0=평균예측)라 데이터-불변 고정 바닥이 정당.
    - 분류(불균형 ratio≥1.5): weighted-F1 은 다수 클래스가 점수를 부풀리므로
      ROC-AUC(무작위 0.5 기준, 불균형 강건)로 게이트 전환. AUC 미제공(proba 없음)
      시 weighted-F1 로 폴백(공허 통과 방지).
    - 분류(균형/경미): weighted-F1≈macro-F1. 무작위 F1≈1/n_classes + 마진.
      클래스 많을수록(어려울수록) 자동 완화.
    """
    cat = state.category
    metrics = (state.best_model or {}).get("metrics") or {}
    profile = getattr(state, "data_profile", None) or {}
    base = THRESHOLDS_BY_CAT.get(cat, {})

    if _is_regression(state, metrics):
        floor = float(base.get("val_r2", 0.30))
        return {"val_r2": floor}, f"회귀 → val_r2≥{floor} (평균예측 대비 분산설명, 스케일 불변)"

    imb = float(profile.get("class_imbalance_ratio") or 1.0)
    if imb >= _IMBALANCE_SWITCH and metrics.get("val_roc_auc") is not None:
        thr = round(0.5 + _RANDOM_MARGIN, 2)
        return (
            {"val_roc_auc": thr},
            f"불균형(ratio={imb:.1f}) → val_roc_auc≥{thr} (무작위 0.5+마진{_RANDOM_MARGIN}; weighted-F1 다수편향 회피)",
        )

    n_cls = _n_classes(state, metrics)
    rand = 1.0 / max(n_cls, 2)
    thr = round(min(0.85, max(0.30, rand + _RANDOM_MARGIN)), 2)
    note = "경미불균형 " if imb >= _IMBALANCE_SWITCH else ""
    return (
        {"val_f1": thr},
        f"{note}{n_cls}클래스 → val_f1(weighted)≥{thr} (무작위 {rand:.2f}+마진{_RANDOM_MARGIN})",
    )


def evaluate(state: Any) -> dict[str, Any]:
    best = state.best_model or {}
    metrics = best.get("metrics") or {}
    thr, thr_desc = resolve_thresholds(state)  # HJ — 데이터 인지형 적응 임계

    # 1) val 기반 1차 판정 (best_model.metrics = val 점수).
    val_violations = _check_violations(metrics, thr)
    val_passed = len(val_violations) == 0

    # 2) test 봉인 정책 — 재시도 중(여유 있고 val 미통과)에는 test 불가침.
    #    val 통과했거나 마지막 시도일 때만 test 1회 측정.
    re_loop_count = int(getattr(state, "re_loop_count", 0) or 0)
    max_re_loop = int(getattr(state, "max_re_loop", 0) or 0)
    is_last_attempt = re_loop_count >= max_re_loop
    # 재시도 중(미통과·여유 있음)이면 test 보지 않음.
    allow_test = val_passed or is_last_attempt

    best_name = best.get("model_name")
    best_params = best.get("params_used") or {}

    test_metrics: dict[str, Any] = {}
    if allow_test and best_name:
        test_metrics = _compute_test_metrics(state, best_name, best_params)

    # 3) 최종 판정 — test 를 측정했고 비어있지 않으면 test 기준, 아니면 val 기준.
    if test_metrics:
        test_violations = _check_violations(test_metrics, thr)
        passed = len(test_violations) == 0
        eval_basis = "test"
        test_held_out = False  # 이번 평가에서 test 를 1회 사용함
        violations = test_violations
        if passed:
            rationale = "봉인 test 임계 통과"
        else:
            rationale = "test 미통과: " + "; ".join(test_violations)
    else:
        # test 미측정 (재시도 중 또는 경계 메타 없음) → val 기준 판정.
        passed = val_passed
        eval_basis = "val"
        # 재시도 중이라 일부러 안 본 경우 / 측정 못 한 경우 모두 test 는 봉인 상태.
        test_held_out = True
        violations = val_violations
        if passed:
            rationale = "임계치 통과"
        else:
            rationale = "; ".join(val_violations)

    # HJ 2026-06-13 — 적응형 임계 근거를 rationale 에 노출 (사용자에게 "왜 이 기준" 설명).
    rationale = f"{rationale} · 기준: {thr_desc}"

    # Day 11 (jh) — baseline 대비 격차 계산. baseline 미학습/누락 시 빈 dict.
    # (격차는 학습 시 산출된 val 점수 기준으로 일관되게 계산 — baseline 도 val.)
    baseline = _find_baseline_metrics(state)
    improvement = _compute_improvement(metrics, baseline.get("metrics") or {})

    # Day 11 (jh) — CV 통계 + 통계적 유의성.
    # best_model 과 baseline 둘 다 CV 재평가 (가드 통과 시). CV 는 train+val 한정.
    cv_stats: dict[str, Any] = {}
    baseline_cv_stats: dict[str, Any] = {}
    if best_name:
        cv_stats = _compute_cv_stats(state, best_name, best_params)
    baseline_name = baseline.get("name")
    if baseline_name:
        # baseline 은 기본값으로 학습 (params_used 가 없거나 빈 dict)
        baseline_cv_stats = _compute_cv_stats(state, baseline_name, {})

    # 통계적 유의성: baseline_cv_std 를 기준으로 lift 가 노이즈인지 판단.
    baseline_primary_std = baseline_cv_stats.get("primary_std") if baseline_cv_stats else None
    improvement = _add_significance(improvement, baseline_primary_std)

    # HJ 2026-06-13 — 상대·유의성 게이트(common.gates 표준): 데이터 자신의 Dummy
    #   baseline 을 통계적으로 유의하게(lift ≥ 2σ) 이겼는지. 고정 임계(절대)와 병행.
    #   lift_significant 가 '명시적 False' 일 때만 패널티 — None(판단불가; CV 미실행/
    #   baseline 없음)은 미패널티 → 회귀 0·하위호환. 절대 임계는 통과했어도 Dummy
    #   대비 우위가 noise 수준이면 통과 취소(약한 보증 방지).
    if improvement.get("lift_significant") is False:
        _sig_msg = "baseline 대비 유의한 우위 없음 (lift<2σ)"
        if _sig_msg not in violations:
            violations = list(violations) + [_sig_msg]
        if passed:
            passed = False
            rationale = f"{rationale} | {_sig_msg}"

    result = {
        "passed": passed,
        "rationale": rationale,
        "threshold_violations": violations,
        "metrics": metrics,
        # HJ 2026-06-14 — 적응형 임계값을 구조화 dict 로 노출(프런트 G5 모달이 "지표 vs 임계" 비교 표시).
        #   resolve_thresholds() 가 데이터 종류(회귀/분류)·클래스 수·불균형비 등에 따라 동적으로 산출 →
        #   고정값이 아니라 데이터·카테고리 적응형. {"val_f1": 0.55} / {"val_roc_auc": 0.55} / {"val_r2": 0.30} 등.
        "thresholds": thr,
        # Day 12 (jh) — 평가 근거·test 봉인 상태 노출.
        "eval_basis": eval_basis,  # "test" | "val"
        "threshold_basis": thr_desc,  # HJ — 적응형 임계 근거(한국어)
        "test_held_out": test_held_out,  # True 면 이번 평가에서 test 미사용(봉인)
        "test_metrics": test_metrics,  # test 1회 측정값 (미측정 시 빈 dict)
        "val_passed": val_passed,
        "improvement_over_baseline": improvement,
        "baseline_used": baseline,
        "cv_stats": cv_stats,
        "baseline_cv_stats": baseline_cv_stats,
    }
    return result
