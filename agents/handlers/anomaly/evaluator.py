"""agents.handlers.anomaly.evaluator — 이상탐지 평가 (NY 담당, Day 7 v2).

precision@k (k=10) · ROC-AUC · F1 · threshold sweep 곡선 (MinIO PNG).

진입함수 (dispatcher 자동 등록):
  - evaluate(state) -> dict  반환: pr_at_10, auc, f1, threshold_curve_path

DoD: `pr_at_10`, `auc`, `f1`, `threshold_curve_path` 4 필드.
"""

from __future__ import annotations

from typing import Any

# ── 모듈 상수 ─────────────────────────────────────────────────────
PR_AT_K_DEFAULT = 10  # ★ DoD pr_at_10
THRESHOLD_SWEEP_N = 50  # ★ A-3 결정 — 정밀 PR/F1 곡선 (10→50)
AUC_PASS_THRESHOLD = 0.70  # ★ QA 통과 임계 (기존 evaluator THRESHOLD 와 동일값 — 하드코딩 회피)
CHART_DPI = 100
CHART_FIGSIZE = (8, 5)
RANDOM_STATE_EVAL = 42  # ★ 레이블 평가 train/held-out 무작위 분할 시드 (재현)


# ── 헬퍼 ──────────────────────────────────────────────────────────


def _precision_at_k(scores, y_true, k: int = PR_AT_K_DEFAULT) -> float:
    """top k 의 정밀도 (이상탐지 핵심 지표)."""
    import numpy as np

    if len(scores) == 0 or k <= 0:
        return 0.0
    k = min(k, len(scores))
    top_k_idx = np.argsort(scores)[-k:]
    return float(np.asarray(y_true)[top_k_idx].sum() / k)


def _compute_roc_auc(scores, y_true) -> float | None:
    """sklearn roc_auc_score wrapper."""
    if y_true is None or len(scores) == 0:
        return None
    try:
        from sklearn.metrics import roc_auc_score

        return float(roc_auc_score(y_true, scores))
    except Exception:
        return None


def _compute_f1(predicted, y_true) -> float | None:
    """sklearn f1_score wrapper."""
    if y_true is None or len(predicted) == 0:
        return None
    try:
        from sklearn.metrics import f1_score

        return float(f1_score(y_true, predicted))
    except Exception:
        return None


def _threshold_sweep(scores, y_true, n_thresholds: int = THRESHOLD_SWEEP_N) -> list[dict[str, float]]:
    """threshold sweep — precision·recall·F1 계산."""
    import numpy as np

    if y_true is None or len(scores) == 0:
        return []

    from sklearn.metrics import f1_score, precision_score, recall_score

    scores_arr = np.asarray(scores)
    thresholds = np.linspace(scores_arr.min(), scores_arr.max(), n_thresholds)
    results: list[dict[str, float]] = []

    for thr in thresholds:
        predicted = (scores_arr >= thr).astype(int)
        if predicted.sum() == 0:
            continue
        prec = float(precision_score(y_true, predicted, zero_division=0))
        rec = float(recall_score(y_true, predicted, zero_division=0))
        f1 = float(f1_score(y_true, predicted, zero_division=0))
        results.append(
            {
                "threshold": float(thr),
                "precision": prec,
                "recall": rec,
                "f1": f1,
            }
        )

    return results


def _save_threshold_curve_to_minio(sweep_data: list[dict[str, float]], job_id: str) -> str | None:
    """matplotlib threshold curve → MinIO PNG."""
    if not sweep_data:
        return None

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from agents.handlers.common.shared import save_chart_to_minio

    thresholds = [d["threshold"] for d in sweep_data]
    precisions = [d["precision"] for d in sweep_data]
    recalls = [d["recall"] for d in sweep_data]
    f1s = [d["f1"] for d in sweep_data]

    fig, ax = plt.subplots(figsize=CHART_FIGSIZE, dpi=CHART_DPI)
    ax.plot(thresholds, precisions, label="Precision", color="steelblue", marker="o")
    ax.plot(thresholds, recalls, label="Recall", color="crimson", marker="s")
    ax.plot(thresholds, f1s, label="F1", color="darkgreen", marker="^")
    ax.set_xlabel("Threshold")
    ax.set_ylabel("Metric")
    ax.set_title("Threshold Sweep — Precision/Recall/F1")
    ax.legend(loc="best")
    ax.grid(alpha=0.3)
    fig.tight_layout()

    try:
        return save_chart_to_minio(fig, kind="anomaly/threshold_curve", job_id=job_id)
    except Exception:
        plt.close(fig)
        return None


# ── 진입점 ────────────────────────────────────────────────────────


ENSEMBLE_MAX_MODELS = 3  # ★ V4: top3 계약과 정합 (selector top3 → model_candidates)
ENSEMBLE_SECONDARY_WEIGHT = 0.5  # best_model 1.0, 나머지 후보 0.5 (기존 ensemble_voting 기본과 정합)
_ENSEMBLE_EXCLUDE = frozenset({"TranAD", "AnomalyTransformer", "AutoEncoder"})  # 고비용 DL — 재학습 앙상블 제외


def _resolve_eval_train_mask(state: Any, n: int):
    """레이블 평가용 train/held-out 경계 → train 행 boolean mask 반환.

    ★ 누수 차단: 모델을 "채점 대상과 동일 행"으로 재학습하면 AUC/F1 이 낙관 편향된다.
    train 구간에서만 fit 하고 held-out 구간에서만 채점하기 위한 train mask 를 만든다.

    우선순위:
      1) category_extras["anomaly_detection"]["leakage_safe_split"]["n_train"] (정수).
      2) 시간 컬럼 존재 → 시간순 앞 80% train (시계열 순서 보존).
      3) 무작위 80% train (RANDOM_STATE 고정 → 재현).
    경계가 비정상(<1 또는 >=n)이면 None 반환(분리 불가 → 호출부가 전체 fit 폴백).
    """
    import numpy as np  # noqa: WPS433

    if n < 4:
        return None  # 너무 작음 → 분리 무의미, 전체 fit 폴백

    cat = (getattr(state, "category_extras", None) or {}).get("anomaly_detection", {}) or {}

    # 1) leakage_safe_split.n_train 우선
    lss = cat.get("leakage_safe_split") or {}
    n_train = lss.get("n_train")
    if isinstance(n_train, (int, float)) and 1 <= int(n_train) < n:
        mask = np.zeros(n, dtype=bool)
        mask[: int(n_train)] = True
        return mask

    cut = max(1, int(n * 0.8))
    if cut >= n:
        return None

    # 2) 시간 컬럼 → 시간순 앞 80%
    profile = getattr(state, "data_profile", None) or {}
    if profile.get("has_time_column"):
        mask = np.zeros(n, dtype=bool)
        mask[:cut] = True  # X 는 이미 로드 순서(=시간순 가정) — 앞쪽이 과거
        return mask

    # 3) 무작위 80%
    rng = np.random.default_rng(RANDOM_STATE_EVAL)
    perm = rng.permutation(n)
    mask = np.zeros(n, dtype=bool)
    mask[perm[:cut]] = True
    return mask


def _generate_scores(state: Any):
    """★ X-3/X-6 ① + ★ V4 — best_model 중심 rank-ensemble per-row anomaly score 생성.

    ★ V4 변경 (2026-06-10):
      1. 앙상블 재활성화 — state.model_candidates (selector top3) 중 경량 모델을
         best_model 과 함께 학습, rank 정규화 후 가중평균 (best 1.0 / 보조 0.5).
         근거: outlier ensemble 의 분산 감소 효과 (Aggarwal & Sathe 2015;
         Zimek et al. 2014 "Ensembles for unsupervised outlier detection").
         rank 정규화 근거: Kriegel et al. SDM 2011 — 이종 detector 점수 통일.
      2. threshold — 단순 Otsu → `_otsu_threshold_with_validation` (A-2 로직 실사용):
         Otsu 비율이 contamination 추정의 5배 초과 시 contamination quantile 로 폴백.
      3. 보조 모델 실패는 개별 격리 — best_model 단독으로도 항상 동작 (하위호환).

    반환: (scores, predicted, threshold, y_true|None, info) 또는 None (생성 불가).
    info = {ensemble_method, ensemble_models_used, ensemble_model_errors, threshold_meta}
    (구 4-튜플을 반환하는 테스트 mock 과의 호환은 evaluate() 쪽에서 처리.)
    """
    import numpy as np

    best = getattr(state, "best_model", None) or {}
    model_name = best.get("model_name")
    if not model_name:
        return None
    params = best.get("params_used") or {}

    try:
        from agents.training_executor import _split_xy
        from pipelines.anomaly import AnomalyPipeline
        from tools.minio_tool import get_minio_client

        mc = get_minio_client()
        df = mc.load_dataframe(state.file_id, fmt=state.file_id.rsplit(".", 1)[-1].lower())
        X, y = _split_xy(df, getattr(state, "target_column", None))
    except Exception:
        return None

    y_true = np.asarray(y).astype(int) if getattr(state, "target_column", None) else None

    # ── ★ 누수 차단: 레이블 평가(roc_auc/f1/pr)는 train 구간 fit / held-out 채점으로 분리 ──
    #   y_true 가 있을 때만 분할(지도). 비지도(y_true=None)는 분리 없이 기존 동작 유지.
    #   train_mask=True 행으로만 모델을 fit 하고, 점수는 전체 X 에 대해 산출(transform-only,
    #   held-out 행은 fit 에 미사용 → 누수 없음). evaluate() 가 held-out 행만 채점한다.
    train_mask = None
    if y_true is not None:
        train_mask = _resolve_eval_train_mask(state, int(len(X)))

    # ── ★ V4 ①: 앙상블 후보 구성 (best 우선 + top3 경량 후보) ──────────
    candidates: list[str] = [model_name]
    for m in getattr(state, "model_candidates", None) or []:
        if m in candidates or m in _ENSEMBLE_EXCLUDE:
            continue
        if m in AnomalyPipeline.SUPPORTED_MODELS:
            candidates.append(m)
        if len(candidates) >= ENSEMBLE_MAX_MODELS:
            break

    pipeline = AnomalyPipeline()
    scores_dict: dict[str, np.ndarray] = {}
    model_errors: dict[str, str] = {}
    # ★ train_mask 가 있으면 fit 은 train 행으로만 (X_fit/y_fit), 예측은 전체 X.
    #   mask 없으면(비지도 또는 분리 불가) 전체로 fit — 기존 동작.
    if train_mask is not None:
        X_fit = X[train_mask]
        y_fit = y[train_mask] if y is not None else None
    else:
        X_fit, y_fit = X, y
    for m in candidates:
        try:
            m_params = params if m == model_name else {}
            model = pipeline.train(X_fit, y_fit, m, m_params)  # train 구간만 fit (seed 고정)
            raw = np.asarray(pipeline.predict(model, X), dtype=float)  # 전체 X 채점(transform-only)
            scores_dict[m] = AnomalyPipeline.normalize_scores_rank(raw)  # ★ V4: rank 정규화
        except Exception as e:  # noqa: BLE001 — 보조 모델 실패 격리
            model_errors[m] = f"{type(e).__name__}: {e}"

    if model_name not in scores_dict:
        return None  # best_model 자체 실패 → 기존과 동일하게 평가 skip

    if len(scores_dict) >= 2:
        weights = {m: (1.0 if m == model_name else ENSEMBLE_SECONDARY_WEIGHT) for m in scores_dict}
        scores = np.asarray(AnomalyPipeline.ensemble_voting(scores_dict, weights), dtype=float)
        ensemble_method = "rank_weighted_ensemble"
    else:
        scores = scores_dict[model_name]
        ensemble_method = "single_best"

    # ── ★ V4 ②: threshold — Otsu + contamination sanity (A-2 실사용) ──
    try:
        from pipelines.anomaly.pipeline import _otsu_threshold_with_validation

        profile = getattr(state, "data_profile", None) or {}
        contam = float(profile.get("contamination_estimate", 0.1))
        threshold, threshold_meta = _otsu_threshold_with_validation(scores, contam)
        threshold = float(threshold)
    except Exception:  # noqa: BLE001 — 폴백: 기존 단순 Otsu
        threshold = float(AnomalyPipeline.otsu_threshold(scores))
        threshold_meta = {"method": "otsu", "reason": "validation fallback"}

    predicted = (scores > threshold).astype(int)

    # ★ held-out mask 를 info 로 전달 → evaluate() 가 레이블 메트릭을 held-out 행에만 적용.
    holdout_mask = (~train_mask) if train_mask is not None else None
    leakage_safe_eval = bool(train_mask is not None)
    n_eval_holdout = int(holdout_mask.sum()) if holdout_mask is not None else None

    info = {
        "ensemble_method": ensemble_method,
        "ensemble_models_used": list(scores_dict.keys()),
        "ensemble_model_errors": model_errors,
        "threshold_meta": threshold_meta,
        "holdout_mask": holdout_mask,  # np.ndarray[bool] | None (evaluate 내부 소비)
        "leakage_safe_eval": leakage_safe_eval,  # train fit / held-out 채점 적용 여부
        "n_eval_holdout": n_eval_holdout,
    }
    return scores, predicted, threshold, y_true, info


def _stability_metrics(scores: Any, threshold: float, n_boot: int = 20, seed: int = 42) -> dict[str, Any]:
    """P2-3 (2026-06-16) — 부트스트랩 임계 안정성.

    scores 를 복원추출 리샘플하여 매번 Otsu 임계를 재계산, 임계의 변동계수(CV)를 본다.
    CV 가 낮을수록 임계 결정이 표본 흔들림에 강건(=이상/정상 경계가 안정적). 추가로
    경계(threshold±std) 근처 샘플 비율(판정이 쉽게 뒤집히는 회색지대)도 보고한다.
    재학습 없이 scores 만 리샘플하므로 가볍고, 소표본/실패 시 {} (graceful, additive).
    """
    import numpy as np  # noqa: WPS433

    try:
        s = np.asarray(scores, dtype=float)
        n = len(s)
        if n < 30:
            return {}
        from pipelines.anomaly.pipeline import AnomalyPipeline  # noqa: WPS433

        rng = np.random.default_rng(seed)
        thrs: list[float] = []
        for _ in range(n_boot):
            samp = s[rng.integers(0, n, size=n)]
            try:
                thrs.append(float(AnomalyPipeline.otsu_threshold(samp)))
            except Exception:  # noqa: BLE001
                continue
        if len(thrs) < 3:
            return {}
        arr = np.asarray(thrs, dtype=float)
        mean_t = float(arr.mean())
        std_t = float(arr.std())
        cv = float(std_t / abs(mean_t)) if mean_t != 0 else 0.0
        boundary = float(((s > threshold - std_t) & (s < threshold + std_t)).mean()) if std_t > 0 else 0.0
        return {
            "threshold_bootstrap_mean": round(mean_t, 6),
            "threshold_bootstrap_std": round(std_t, 6),
            "threshold_stability_cv": round(cv, 4),
            "threshold_stable": bool(cv < 0.2),
            "boundary_sample_ratio": round(boundary, 4),
        }
    except Exception:  # noqa: BLE001
        return {}


def evaluate(state: Any) -> dict[str, Any]:
    """anomaly 평가 (dispatcher) — ★ X-3/X-6 ①: per-row score 생성 + metrics.

    best_model 로 per-row anomaly score 를 만들고(_generate_scores) metrics 계산.
    **반환 dict → eval_agent 가 state.eval_result 에 저장** (category_extras 미사용, R-005 준수).
    Day 8·9 는 state.eval_result 에서 ensemble_scores·predicted_anomalies·threshold·metrics 읽음.
    y_true 없으면(C2/C4 비지도) label metrics = None (B-1·서브카테고리 일관).
    """
    gen = _generate_scores(state)
    if gen is None:
        return {
            "ensemble_scores": None,
            "predicted_anomalies": None,
            "threshold": 0.0,
            "passed": True,
            "pr_at_10": None,
            "pr_auc": None,
            "auc": None,
            "f1": None,
            "threshold_curve_path": None,
            "y_true_available": False,
            "threshold_sweep_table": [],
            "warning": "best_model 미설정 또는 데이터 로드 실패 — 평가 skip",
            "rationale": "score 생성 불가 (gen=None) — 후속 단계 skip",
        }

    # ★ V4: 5-튜플 (info 포함) + 구 4-튜플 (테스트 mock) 양쪽 호환
    scores, predicted, threshold, y_true = gen[0], gen[1], gen[2], gen[3]
    info: dict[str, Any] = gen[4] if len(gen) > 4 else {}
    has_y = y_true is not None

    # ★ 누수 차단: 레이블 메트릭(pr/auc/f1/sweep)은 "held-out 행"에만 적용.
    #   _generate_scores 가 모델을 train 구간으로만 fit 했으므로, 채점도 held-out
    #   구간이어야 정직한 일반화 성능이 된다. holdout_mask 가 없으면(구 4-튜플 mock·
    #   분리 불가) 전체로 폴백 — 기존 동작과 동일(하위호환).
    import numpy as np  # noqa: WPS433

    _hmask = info.get("holdout_mask") if isinstance(info, dict) else None
    if has_y and _hmask is not None:
        try:
            _hmask = np.asarray(_hmask, dtype=bool)
            if _hmask.shape[0] == len(scores) and int(_hmask.sum()) > 0:
                y_eval = np.asarray(y_true)[_hmask]
                scores_eval = np.asarray(scores)[_hmask]
                predicted_eval = np.asarray(predicted)[_hmask]
            else:  # 길이 불일치/공집합 → 전체 폴백
                y_eval, scores_eval, predicted_eval = y_true, scores, predicted
        except Exception:  # noqa: BLE001
            y_eval, scores_eval, predicted_eval = y_true, scores, predicted
    else:
        y_eval, scores_eval, predicted_eval = y_true, scores, predicted

    pr = _precision_at_k(scores_eval, y_eval) if has_y else None
    pr_auc = None
    if has_y:
        try:
            from sklearn.metrics import average_precision_score

            pr_auc = float(average_precision_score(y_eval, scores_eval))
        except Exception:
            pr_auc = None
    auc = _compute_roc_auc(scores_eval, y_eval) if has_y else None
    f1 = _compute_f1(predicted_eval, y_eval) if has_y else None
    sweep = _threshold_sweep(scores_eval, y_eval) if has_y else []
    curve_path = _save_threshold_curve_to_minio(sweep, getattr(state, "job_id", "")) if has_y else None

    # ★ V4: sweep 기반 best-F1 threshold (운영 권고용 — passed 판정엔 미사용)
    best_f1_threshold = None
    if sweep:
        best_row = max(sweep, key=lambda d: d["f1"])
        best_f1_threshold = float(best_row["threshold"])

    if has_y and auc is not None:
        auc_ok = bool(auc >= AUC_PASS_THRESHOLD)
        # ★ HJ 2026-06-13 — 극단 불균형(희귀 이상)에서 ROC-AUC 는 낙관적 → 이미 계산된
        #   PR-AUC 가 무작위 기준선(= 양성 base rate)을 유의하게 넘는지 보조 확인.
        #   PR-AUC 의 무작위값은 base rate 이므로, base rate × 1.5 미만이면 랭킹력이
        #   사실상 무작위 → 통과 취소. pr_auc/base_rate 둘 다 있고 희귀(base_rate<0.2)
        #   일 때만 적용(보수적 — 균형 데이터엔 영향 없음).
        pr_ok = True
        try:
            base_rate = float(np.mean(np.asarray(y_eval, dtype=float)))
        except Exception:  # noqa: BLE001
            base_rate = 0.0
        if pr_auc is not None and 0.0 < base_rate < 0.2:
            pr_ok = bool(pr_auc >= base_rate * 1.5)
        passed = bool(auc_ok and pr_ok)
        rationale = f"AUC={auc:.3f} (임계 {AUC_PASS_THRESHOLD:.2f})"
        if pr_auc is not None:
            rationale += f", PR-AUC={pr_auc:.3f}"
            if not pr_ok:
                rationale += f" (PR-AUC < base rate {base_rate:.3f}×1.5 — 희귀 이상 랭킹력 무작위 수준)"
    else:
        passed = True
        rationale = "y_true 부재 — 비지도 평가 (메트릭 None)"

    return {
        "ensemble_scores": scores.tolist(),
        "predicted_anomalies": predicted.tolist(),
        "threshold": float(threshold),
        "passed": passed,
        "pr_at_10": float(pr) if pr is not None else None,
        "pr_auc": pr_auc,
        "auc": float(auc) if auc is not None else None,
        "f1": float(f1) if f1 is not None else None,
        "threshold_curve_path": curve_path,
        "y_true_available": has_y,
        "threshold_sweep_table": sweep,
        "rationale": rationale,
        # ★ V4 신규 키 (additive — 기존 소비처 영향 없음)
        "best_f1_threshold": best_f1_threshold,
        "ensemble_method": info.get("ensemble_method"),
        "ensemble_models_used": info.get("ensemble_models_used"),
        "ensemble_model_errors": info.get("ensemble_model_errors"),
        "threshold_meta": info.get("threshold_meta"),
        # ★ 누수 차단 메타 (additive) — 레이블 메트릭이 held-out 행으로만 산출됐는지.
        "leakage_safe_eval": bool(info.get("leakage_safe_eval", False)),
        "n_eval_holdout": info.get("n_eval_holdout"),
        # ★ P2-3 (2026-06-16) — 부트스트랩 임계 안정성 (additive, graceful; 소표본 시 빈 dict)
        **_stability_metrics(scores, float(threshold)),
    }
