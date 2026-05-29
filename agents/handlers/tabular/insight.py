"""agents.handlers.tabular.insight — 정형 인사이트 (jh 담당).

Day 8: best 피처 top3 기여도(%) + 비즈니스 행동 권고.
DoD 형식: "{피처} 피처가 결과의 32% 를 설명" (기여도 백분율 인용).

피처 중요도 소스 (우선순위):
  1. ``state.best_model["feature_importances"]`` (+ ``feature_names``)
  2. ``state.explanations["shap_top_features"]``  (dict / [name,val] / [{name,importance}])
  3. ``state.eval_result["feature_importance" | "importances" | "top_features"]``

dispatcher(agents/insight.py, HJ) 는 ``prompt_payload`` / ``fallback`` / ``SYSTEM_PROMPT``
를 사용. fallback 텍스트는 HJ Day8 가드(insight_must_cite)를 통과하도록 설계:
  (a) 수치 1개+ (b) top 피처명 1개+ (c) 3~5 한국어 문장.
"""

from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """당신은 정형 데이터 분석 인사이트 작성자입니다.
다음 데이터를 보고 한국어 3~5문장으로 인사이트를 작성하세요.

규칙:
1. 정확도/F1/AUC 같은 정확한 수치 1개 이상 인용
2. 상위 피처 top3 중 1개 이상을 기여도(%)와 함께 자연스럽게 언급
   (예: "X 피처가 결과의 32%를 설명")
3. 마지막 1문장은 비즈니스 행동 권고
4. 마크다운/리스트/이모지 금지
"""


# 피처 중요도 추출 ──────────────────────────────────────────────────────────


def _coerce_pairs(obj: Any) -> list[tuple[str, float]]:
    """다양한 형태 -> [(name, abs_importance)] 로 정규화."""
    out: list[tuple[str, float]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (int, float)):
                out.append((str(k), abs(float(v))))
        return out
    if isinstance(obj, (list, tuple)):
        for x in obj:
            if isinstance(x, dict):
                name = x.get("name") or x.get("feature") or x.get("col")
                val = x.get("importance", x.get("value", x.get("shap", x.get("weight"))))
                if name is not None:
                    out.append((str(name), abs(float(val)) if isinstance(val, (int, float)) else 0.0))
            elif isinstance(x, (list, tuple)) and len(x) >= 2 and isinstance(x[1], (int, float)):
                out.append((str(x[0]), abs(float(x[1]))))
            elif isinstance(x, str):
                out.append((x, 0.0))
    return out


def _feature_importance_pairs(state: Any) -> list[tuple[str, float]]:
    bm = getattr(state, "best_model", None) or {}
    fi = bm.get("feature_importances")
    fn = bm.get("feature_names")
    if isinstance(fi, (list, tuple)) and fi:
        if isinstance(fn, (list, tuple)) and len(fn) == len(fi):
            names = [str(n) for n in fn]
        else:
            names = [f"f{i}" for i in range(len(fi))]
        return [
            (n, abs(float(v)))
            for n, v in zip(names, fi)
            if isinstance(v, (int, float))
        ]

    expl = getattr(state, "explanations", None) or {}
    pairs = _coerce_pairs(expl.get("shap_top_features"))
    if pairs:
        return pairs

    er = getattr(state, "eval_result", None) or {}
    src = er.get("feature_importance") or er.get("importances") or er.get("top_features")
    return _coerce_pairs(src)


def top_features(state: Any, k: int = 3) -> list[dict[str, Any]]:
    """상위 k 피처 + 기여도(%). [{name, importance, contribution_pct}]."""
    pairs = _feature_importance_pairs(state)
    if not pairs:
        return []
    total = sum(v for _, v in pairs)
    ranked = sorted(pairs, key=lambda p: p[1], reverse=True)[:k]
    out: list[dict[str, Any]] = []
    for name, v in ranked:
        pct = (v / total * 100.0) if total > 0 else 0.0
        out.append({"name": name, "importance": round(v, 6), "contribution_pct": round(pct, 1)})
    return out


# dispatcher 진입점 ──────────────────────────────────────────────────────────


def prompt_payload(state: Any) -> dict[str, Any]:
    feats = top_features(state, k=3)
    return {
        "category": state.category,
        "user_intent": state.user_intent,
        "best_model": state.best_model,
        "shap_top": (state.explanations or {}).get("shap_top_features"),
        "top_features": feats,
        "top_feature_names": [f["name"] for f in feats],
        "eval_result": state.eval_result,
        "class_imbalance_ratio": (state.data_profile or {}).get("class_imbalance_ratio"),
    }


def fallback(state: Any) -> str:
    bm = getattr(state, "best_model", None) or {}
    metrics = bm.get("metrics", {}) or {}
    f1 = metrics.get("val_f1")
    auc = metrics.get("val_roc_auc")
    acc = metrics.get("val_accuracy")
    feats = top_features(state, k=3)

    parts: list[str] = [
        f"본 분석에서는 {bm.get('model_name', '미정')} 모델이 가장 우수한 성능을 보였습니다."
    ]

    # 수치 인용 (가드 a)
    metric_bits: list[str] = []
    if f1 is not None:
        metric_bits.append(f"검증 F1 {float(f1):.2f}")
    if auc is not None:
        metric_bits.append(f"ROC AUC {float(auc):.2f}")
    if acc is not None and not metric_bits:
        metric_bits.append(f"정확도 {float(acc):.2f}")
    if metric_bits:
        parts.append(f"{', '.join(metric_bits)} 수준의 성능입니다.")

    # DoD 형식: top 피처 기여도(%) (가드 b)
    if feats:
        top1 = feats[0]
        sentence = f"{top1['name']} 피처가 결과의 {top1['contribution_pct']:.0f}%를 설명합니다."
        rest = [f["name"] for f in feats[1:]]
        if rest:
            sentence = (
                f"{top1['name']} 피처가 결과의 {top1['contribution_pct']:.0f}%를 설명하며, "
                f"그다음으로 {', '.join(rest)} 순으로 중요합니다."
            )
        parts.append(sentence)
        parts.append(
            f"실무에서는 {top1['name']} 를 중심으로 의사결정 기준을 마련하고 "
            f"모델 예측을 보조 자료로 활용할 것을 권장합니다."
        )
    else:
        parts.append("실무에서는 본 모델 예측 결과를 의사결정 보조 자료로 활용할 것을 권장합니다.")

    return " ".join(parts)
