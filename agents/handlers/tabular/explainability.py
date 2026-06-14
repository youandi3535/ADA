"""agents.handlers.tabular.explainability — 정형 모델 SHAP 본구현 (jh 담당).

Day 11++ — insight payload 의 shap_top 키가 빈값이던 문제 해결.
실제 SHAP 값으로 채워 산출물(insight 텍스트, OUT-07 MD, PPT 슬라이드 14)에
"왜 이 예측이 나왔는지" 정보 노출.

Explainer 자동 선택
==================
  - TreeExplainer   : RandomForest / XGBoost / LightGBM / CatBoost (빠름·정확)
  - LinearExplainer : LogisticRegression / Ridge / Lasso
  - KernelExplainer : TabPFN / Transformer / 기타 (느림, sample=100)

가드
====
  - baseline 모델(Dummy) → skip (의미 없음)
  - 모델 재로드 실패 → skip
  - DL 카테고리 또는 비-tree 모델 → KernelExplainer sample=100
  - n_rows > 5000 → 1000 행 샘플링
  - shap 라이브러리 import 실패 → skip (graceful)

저장 위치 (jh 영역, state.category_extras)
=========================================
state.category_extras["tabular"]["shap"] = {
    "shap_top_features"     : list[dict] — [{feature, mean_abs_shap, sign}] top-N
    "shap_summary_path"     : str | None — beeswarm 차트 MinIO 경로
    "shap_dependence_paths" : list[str]  — top-3 feature dependence 차트
    "explainer_type"        : "tree" | "linear" | "kernel"
    "n_samples_used"        : int
    "skipped_reason"        : str | None
}

Insight·output_extras 가 이 키를 직접 읽음. 향후 HJ 가 agents/explainability.py
dispatcher 에 "explain" capability 호출을 연결하면 state.explanations 에도
자동 머지될 수 있도록 동일 페이로드 형식으로 explain() 도 노출.

진입함수 (jh 영역)
=================
  - explain(state) -> dict       : 위 dict 그대로 반환 (dispatcher 용)
  - shap_summary_chart(state)    : output_extras 가 호출 (charts 리스트에 추가)
  - shap_top_features(state)     : insight 가 호출 (fallback)
"""

from __future__ import annotations

import logging
from typing import Any

import matplotlib  # noqa: WPS433

matplotlib.use("Agg")

logger = logging.getLogger(__name__)


# 모델 종류별 explainer 라우팅 상수
_TREE_MODELS = {"RandomForest", "XGBoost", "LightGBM", "CatBoost"}
_LINEAR_MODELS = {"LogisticRegression", "Ridge", "Lasso"}
_SKIP_MODELS = {"Dummy"}  # baseline — SHAP 의미 없음

# 비용 가드
_MAX_ROWS_FOR_SHAP = 5000
_SAMPLE_SIZE_LARGE = 1000  # n_rows > MAX 일 때 샘플링 크기
_KERNEL_SAMPLE = 100  # KernelExplainer 는 더 작게
_KERNEL_BACKGROUND = 50  # KernelExplainer 의 background data 크기
_TOP_K = 10
_DEPENDENCE_TOP_K = 3


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────


def _select_explainer_type(model_name: str, category: str) -> str:
    """모델명 + 카테고리로 explainer 종류 결정."""
    if category == "tabular_dl":
        return "kernel"
    if model_name in _TREE_MODELS:
        return "tree"
    if model_name in _LINEAR_MODELS:
        return "linear"
    return "kernel"


def _skipped_result(reason: str, explainer_type: str = "none") -> dict[str, Any]:
    """가드 통과 못 했을 때 반환할 표준 빈 결과."""
    return {
        "shap_top_features": [],
        "shap_summary_path": None,
        "shap_dependence_paths": [],
        "explainer_type": explainer_type,
        "n_samples_used": 0,
        "skipped_reason": reason,
    }


def _maybe_sample(X: Any, y: Any, n_target: int):
    """n_rows > n_target 이면 무작위 샘플링 — SHAP 비용 폭주 가드."""
    import numpy as np

    n = len(X)
    if n <= n_target:
        return X, y
    rng = np.random.default_rng(42)
    idx = rng.choice(n, size=n_target, replace=False)
    try:
        return X.iloc[idx], y.iloc[idx]
    except AttributeError:
        return X[idx], y[idx]


def _shap_values_to_top(
    shap_values: Any,
    feature_names: list[str],
    top_k: int = _TOP_K,
) -> list[dict[str, Any]]:
    """shap_values 매트릭스 → top-K 피처 리스트.

    - 분류 multi-class: shap_values 가 list of arrays (class 별) 또는 3D 텐서.
      모든 클래스의 |shap| 평균을 합산해 mean_abs 산출.
    - 이진/회귀: 2D 매트릭스 (n_samples, n_features).

    Returns:
        [{"feature": str, "mean_abs_shap": float, "direction": str}, ...]
        direction: 평균 SHAP 가 양/음 — 양이면 "+"(증가 방향), 음이면 "-".
    """
    import numpy as np

    if isinstance(shap_values, list):
        # 분류 multi-class: class 별 array → |shap| 평균 모두 더함
        abs_stack = np.stack([np.abs(sv) for sv in shap_values], axis=0)
        mean_abs = abs_stack.mean(axis=(0, 1))  # average over class + samples
        # direction: class 0 의 평균 SHAP 부호 (binary 면 그게 양성 방향)
        signed_mean = shap_values[0].mean(axis=0) if shap_values else mean_abs
    else:
        arr = np.asarray(shap_values)
        if arr.ndim == 3:  # (n_samples, n_features, n_classes)
            abs_stack = np.abs(arr)
            mean_abs = abs_stack.mean(axis=(0, 2))
            signed_mean = arr[..., 0].mean(axis=0) if arr.shape[2] > 0 else mean_abs
        else:  # (n_samples, n_features)
            mean_abs = np.abs(arr).mean(axis=0)
            signed_mean = arr.mean(axis=0)

    # 피처 수 매칭 가드
    n_features = len(mean_abs)
    if len(feature_names) != n_features:
        feature_names = [f"feature_{i}" for i in range(n_features)]

    # jh 2026-06-14 — 원-핫 인코딩 컬럼을 베이스 피처로 합산 집계 (Sex_male+Sex_female→Sex,
    # Embarked_C/Q/S→Embarked). '<base>_<value>' 형태이고 같은 base 형제가 2개 이상일 때만
    # 묶어, 단일 언더스코어 피처(charge_per_tenure 등) 오병합을 방지한다.
    import re as _re

    _bases: dict[str, list[int]] = {}
    for _i, _fn in enumerate(feature_names):
        _m = _re.match(r"^(.+)_[^_]+$", str(_fn))
        if _m:
            _bases.setdefault(_m.group(1), []).append(_i)
    _agg = {b: idxs for b, idxs in _bases.items() if len(idxs) >= 2}
    _grouped = {i for idxs in _agg.values() for i in idxs}

    entries: list[tuple[str, float, float]] = []
    for _b, _idxs in _agg.items():
        _tot = float(sum(mean_abs[i] for i in _idxs))
        _dom = max(_idxs, key=lambda i: mean_abs[i])
        entries.append((_b, _tot, float(signed_mean[_dom])))
    for _i in range(n_features):
        if _i not in _grouped:
            entries.append((str(feature_names[_i]), float(mean_abs[_i]), float(signed_mean[_i])))

    entries.sort(key=lambda e: e[1], reverse=True)
    out: list[dict[str, Any]] = [
        {
            "feature": _n,
            "mean_abs_shap": round(_v, 6),
            "direction": "+" if _s >= 0 else "-",
        }
        for _n, _v, _s in entries[:top_k]
    ]
    return out


# ──────────────────────────────────────────────────────────────────────────────
# 핵심 진입점
# ──────────────────────────────────────────────────────────────────────────────


def explain(state: Any) -> dict[str, Any]:
    """tabular SHAP 본구현 — explainer 자동 선택 + 차트 + top-K feature.

    output 형식은 모듈 docstring 참조. 가드 통과 못 하면 skipped_reason 채움.
    """
    from pipelines.tabular_ml.pipeline import is_baseline_model

    bm = getattr(state, "best_model", None) or {}
    model_name = bm.get("model_name")
    category = getattr(state, "category", "tabular_ml")

    if not model_name:
        return _skipped_result("no_best_model")
    if is_baseline_model(model_name) or model_name in _SKIP_MODELS:
        return _skipped_result("baseline_skip")

    # shap 라이브러리 import 확인 (worker.txt 의존성 — 운영 환경엔 있음)
    try:
        import shap  # noqa: F401
    except ImportError as exc:
        logger.warning("shap_import_failed: %s", exc)
        return _skipped_result("shap_import_failed")

    # 모델 + val 데이터 재로드 (output_extras 의 _try_reload 재사용)
    from agents.handlers.tabular.output_extras import _try_reload_model_and_data

    reload = _try_reload_model_and_data(state)
    if reload is None:
        return _skipped_result("model_reload_failed")

    model_obj, X_val, y_val = reload
    explainer_type = _select_explainer_type(model_name, category)

    # 비용 가드 — n_rows 가 크면 샘플링
    if explainer_type == "kernel":
        X_sample, y_sample = _maybe_sample(X_val, y_val, _KERNEL_SAMPLE)
    elif len(X_val) > _MAX_ROWS_FOR_SHAP:
        X_sample, y_sample = _maybe_sample(X_val, y_val, _SAMPLE_SIZE_LARGE)
    else:
        X_sample, y_sample = X_val, y_val

    try:
        feature_names = (
            list(X_sample.columns) if hasattr(X_sample, "columns")
            else [f"feature_{i}" for i in range(X_sample.shape[1])]
        )

        # explainer 생성
        import shap as _shap

        if explainer_type == "tree":
            explainer = _shap.TreeExplainer(model_obj)
            shap_values = explainer.shap_values(X_sample)
        elif explainer_type == "linear":
            explainer = _shap.LinearExplainer(model_obj, X_sample)
            shap_values = explainer.shap_values(X_sample)
        else:  # kernel
            # background 작게
            if hasattr(model_obj, "predict_proba"):
                predict_fn = model_obj.predict_proba
            else:
                predict_fn = model_obj.predict
            X_bg, _ = _maybe_sample(X_sample, y_sample, _KERNEL_BACKGROUND)
            explainer = _shap.KernelExplainer(predict_fn, X_bg)
            shap_values = explainer.shap_values(X_sample, nsamples=50)

        top_features = _shap_values_to_top(shap_values, feature_names, _TOP_K)
        summary_path = _build_summary_chart(shap_values, X_sample, feature_names, state)
        dependence_paths = _build_dependence_charts(
            shap_values, X_sample, feature_names, top_features, state
        )

        return {
            "shap_top_features": top_features,
            "shap_summary_path": summary_path,
            "shap_dependence_paths": dependence_paths,
            "explainer_type": explainer_type,
            "n_samples_used": int(len(X_sample)),
            "skipped_reason": None,
        }

    except Exception as exc:
        logger.warning("shap_compute_failed: %s -> %s", explainer_type, exc)
        return _skipped_result(f"shap_error: {type(exc).__name__}", explainer_type=explainer_type)


# ──────────────────────────────────────────────────────────────────────────────
# 차트 helpers
# ──────────────────────────────────────────────────────────────────────────────


def _build_summary_chart(
    shap_values: Any,
    X_sample: Any,
    feature_names: list[str],
    state: Any,
) -> str | None:
    """SHAP beeswarm summary chart → MinIO."""
    try:
        import matplotlib.pyplot as plt
        import shap as _shap

        from agents.handlers.common.shared import save_chart_to_minio

        # multi-class 면 class 0 사용 (일관성)
        sv = shap_values[0] if isinstance(shap_values, list) else shap_values
        if hasattr(sv, "ndim") and sv.ndim == 3:
            sv = sv[..., 0]

        fig = plt.figure(figsize=(8, max(4, _TOP_K * 0.4)), dpi=100)
        _shap.summary_plot(
            sv, X_sample, feature_names=feature_names, show=False, max_display=_TOP_K
        )
        fig = plt.gcf()
        model_name = (getattr(state, "best_model", None) or {}).get("model_name", "모델")
        fig.suptitle(f"SHAP Summary — {model_name}", fontsize=12)
        fig.tight_layout()

        return save_chart_to_minio(
            fig, kind="tabular/shap_summary", job_id=getattr(state, "job_id", "")
        )
    except Exception as exc:
        logger.warning("shap_summary_chart_failed: %s", exc)
        return None


def _build_dependence_charts(
    shap_values: Any,
    X_sample: Any,
    feature_names: list[str],
    top_features: list[dict[str, Any]],
    state: Any,
) -> list[str]:
    """top-3 feature 의 SHAP dependence plot → MinIO."""
    paths: list[str] = []
    try:
        import matplotlib.pyplot as plt
        import shap as _shap

        from agents.handlers.common.shared import save_chart_to_minio

        sv = shap_values[0] if isinstance(shap_values, list) else shap_values
        if hasattr(sv, "ndim") and sv.ndim == 3:
            sv = sv[..., 0]

        job_id = getattr(state, "job_id", "")
        for entry in top_features[:_DEPENDENCE_TOP_K]:
            feat = entry["feature"]
            try:
                fig = plt.figure(figsize=(6.5, 5), dpi=100)
                _shap.dependence_plot(
                    feat, sv, X_sample, feature_names=feature_names,
                    show=False, interaction_index=None,
                )
                fig = plt.gcf()
                fig.suptitle(f"SHAP Dependence — {feat}", fontsize=11)
                fig.tight_layout()
                path = save_chart_to_minio(
                    fig, kind=f"tabular/shap_dependence_{feat}", job_id=job_id
                )
                if path:
                    paths.append(path)
            except Exception as exc:
                logger.debug("shap_dependence_skip: %s -> %s", feat, exc)
                plt.close("all")
    except Exception as exc:
        logger.warning("shap_dependence_charts_failed: %s", exc)
    return paths


# ──────────────────────────────────────────────────────────────────────────────
# output_extras·insight 가 호출할 진입점 (편의 함수)
# ──────────────────────────────────────────────────────────────────────────────


def shap_summary_chart(state: Any) -> str | None:
    """output_extras 가 charts 리스트에 추가하기 위해 호출.

    state.category_extras["tabular"]["shap"] 가 비어있으면 explain() 한 번 실행
    후 결과를 거기에 저장 (중복 계산 방지). 이미 있으면 캐시된 path 반환.
    """
    cached = (
        (getattr(state, "category_extras", None) or {})
        .get("tabular", {})
        .get("shap")
    )
    if isinstance(cached, dict) and cached.get("shap_summary_path"):
        return cached["shap_summary_path"]
    # 계산 트리거 — 결과는 caller (output_extras) 가 category_extras 에 저장해야 함.
    # 본 헬퍼는 비-쓰기. 호출자가 explain() 한 번 돌리고 캐시하는 게 권장.
    result = explain(state)
    return result.get("shap_summary_path")


def shap_top_features(state: Any) -> list[dict[str, Any]]:
    """insight 가 fallback 으로 호출. category_extras 의 캐시 우선.

    state.explanations 가 정식 위치이지만 dispatcher 미연결 시 본 함수 사용.
    """
    cached = (
        (getattr(state, "category_extras", None) or {})
        .get("tabular", {})
        .get("shap")
    )
    if isinstance(cached, dict) and cached.get("shap_top_features"):
        return list(cached["shap_top_features"])
    return list(explain(state).get("shap_top_features") or [])
