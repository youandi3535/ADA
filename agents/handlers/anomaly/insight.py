"""agents.handlers.anomaly.insight — 이상탐지 인사이트 (NY 담당, Day 8 v2).

Top-N 이상치 사례 + 피처 기여도 + σ 형식 + 한국어 강제.

진입함수 (dispatcher 자동 등록, "generate" capability):
  - generate(state) -> str          한국어 3~5 문장
  - prompt_payload(state) -> dict   LLM 입력 (HJ BaseAgent._call_llm)
  - fallback(state) -> str          LLM 실패 시 한국어 템플릿

DoD: "거래 #12345 가 평균 대비 8.3σ 벗어남" 형식.
Contract Day: HJ Guardrails (수치 1+ · top3 피처 1+ · 3~5 문장 · 한국어).
"""

from __future__ import annotations

from typing import Any

# ── 모듈 상수 ─────────────────────────────────────────────────────
TOP_N_DEFAULT = 5  # ★ A-1 DoD
TOP_FEATURES_K = 3  # ★ Contract — top3 피처
SCORE_TO_SIGMA_FACTOR = 8.0  # 점수→σ 대략 변환 (fallback)

SYSTEM_PROMPT = """당신은 이상탐지 결과 인사이트 작성자입니다.
다음 데이터를 보고 한국어 3~5문장으로 인사이트를 작성하세요.

규칙:
1. 학습된 이상치 비율(contamination)과 AUC 같은 정확한 수치 1개 이상 인용
2. 가장 영향력 큰 피처(이상치 기여도) 1개 이상 언급
3. Top-N 이상치 사례가 있다면 1건 인용 (예: "거래 #12345 가 평균 대비 8σ 벗어남")
4. 마지막 1문장은 운영 권고
5. 마크다운/리스트/이모지 금지
"""


# ── 헬퍼 ──────────────────────────────────────────────────────────


def _extract_top_n_anomalies(state: Any, n: int = TOP_N_DEFAULT) -> list[dict]:
    """Day 6 ensemble_scores → top N 이상치 사례."""
    import numpy as np

    # X-3/X-6 우선 + category_extras fallback (테스트 호환)
    pipeline = getattr(state, "eval_result", None) or {}
    if not pipeline:
        pipeline = (getattr(state, "category_extras", {}) or {}).get("anomaly", {}).get("pipeline", {}) or {}
    scores = pipeline.get("ensemble_scores")
    predicted = pipeline.get("predicted_anomalies")

    if scores is None or predicted is None:
        return []

    scores = np.asarray(scores)
    predicted = np.asarray(predicted).astype(bool)

    anom_idx = np.where(predicted)[0]
    if len(anom_idx) == 0:
        return []

    sorted_anom = sorted(anom_idx, key=lambda i: -float(scores[i]))[:n]

    return [{"idx": int(i), "score": float(scores[i])} for i in sorted_anom]


def _compute_sigma(value: float, mean: float, std: float) -> float:
    """평균 대비 표준편차 배수 (σ)."""
    if std <= 0:
        return 0.0
    return float(abs(value - mean) / std)


def _compute_anomaly_sigma_from_df(state: Any, idx: int, feature: str) -> float:
    """정상만 평균·std 기반 σ 계산 (★ A-3 옵션 C — DoD 정확화).

    df 없거나 feature 없으면 fallback (점수→σ 대략).
    """
    import numpy as np

    df = getattr(state, "df", None)
    pipeline = getattr(state, "eval_result", None) or {}  # ★ X-3/X-6: per-row 는 eval_result

    if df is None or feature not in getattr(df, "columns", []):
        # fallback: 점수→σ 대략 변환
        scores = pipeline.get("ensemble_scores")
        if scores is None or idx >= len(scores):
            return 0.0
        return float(scores[idx]) * SCORE_TO_SIGMA_FACTOR

    predicted = pipeline.get("predicted_anomalies")
    if predicted is None:
        return 0.0

    # 정상만 mask → 평균·std
    normal_mask = ~np.asarray(predicted).astype(bool)
    normal_values = df.loc[normal_mask, feature].dropna()

    if len(normal_values) < 2:
        return 0.0

    mean = float(normal_values.mean())
    std = float(normal_values.std())
    value = float(df[feature].iloc[idx])

    return _compute_sigma(value, mean, std)


def _get_top_features(state: Any, k: int = TOP_FEATURES_K) -> list[str]:
    """Day 1 permutation_importance → top k 피처."""
    profile = getattr(state, "data_profile", None) or {}
    perm_imp = profile.get("permutation_importance_per_dim", {}) or {}

    if not perm_imp:
        return []

    sorted_features = sorted(perm_imp.items(), key=lambda x: -float(x[1]))[:k]
    return [str(name) for name, _ in sorted_features]


def _format_anomaly_case(idx: int, feature: str, sigma: float) -> str:
    """DoD 형식: '거래 #X 가 Y 평균 대비 Nσ 벗어남'."""
    return f"거래 #{idx} 가 {feature} 평균 대비 {int(round(sigma))}σ 벗어남"


def _build_korean_template(
    state: Any,
    top_anomalies: list[dict],
    top_features: list[str],
) -> str:
    """한국어 3~5 문장 템플릿 (★ DoD + Contract Day Guardrails)."""
    profile = getattr(state, "data_profile", None) or {}
    contam = float(profile.get("contamination_estimate", 0.05))

    # ★ X-3/X-6 ①: 평가 결과(per-row + metrics)는 state.eval_result (top-level)
    eval_result = getattr(state, "eval_result", None) or {}
    auc = eval_result.get("auc")

    sentences: list[str] = []

    # ★ B-1: 평가 결과(이상 점수) 누락 시 warning sentence
    has_scores = eval_result.get("ensemble_scores") is not None
    if not has_scores or not eval_result:
        sentences.append("주의: 평가 결과(이상 점수)가 누락되어 부분 정보만 제공됩니다.")

    # 1문장: contamination + AUC (수치 인용)
    auc_int = int(round(float(auc) * 100)) if auc is not None else None
    auc_str = f"AUC {auc_int}점대" if auc_int is not None else "AUC 미측정"
    contam_int = int(round(float(contam) * 100))
    sentences.append(
        f"본 데이터에서 약 {contam_int}퍼센트 비율의 이상치가 탐지되었으며 {auc_str} 의 안정적 성능을 보였습니다"
    )

    # 2문장: top3 피처 (Contract Day — top3 피처 1+)
    if top_features:
        feature_str = ", ".join(top_features[:TOP_FEATURES_K])
        sentences.append(f"가장 영향력 큰 피처는 {feature_str} 로 해당 차원의 비정상이 주요 원인입니다.")

    # 3문장: Top-1 이상치 사례 (★ DoD 형식 + ★ A-3 옵션 C — 정상만 평균·std σ)
    if top_anomalies and top_features:
        top1 = top_anomalies[0]
        sigma_est = _compute_anomaly_sigma_from_df(state, top1["idx"], top_features[0])
        sentences.append(_format_anomaly_case(top1["idx"], top_features[0], sigma_est))

    # 4문장: 전체 사례 수
    if top_anomalies:
        sentences.append(f"정상 분포에서 크게 이탈한 사례 {len(top_anomalies)} 건이 식별되어 우선 점검 권장됩니다.")

    # 5문장: 운영 권고 (Contract Day — 운영 권고)
    sentences.append("운영팀은 고위험 사례 즉시 점검 워크플로 적용을 권장합니다.")

    return ". ".join(sentences) + "."


# ── 진입점 (dispatcher 자동 등록) ──────────────────────────────────


def generate(state: Any) -> str:
    """anomaly insight 한국어 문장 생성 (dispatcher).

    Top-N 이상치 + 피처 기여도 + σ 형식 + 수치 인용 (Contract Day Guardrails).
    """
    top_anomalies = _extract_top_n_anomalies(state, n=TOP_N_DEFAULT)
    top_features = _get_top_features(state, k=TOP_FEATURES_K)
    return _build_korean_template(state, top_anomalies, top_features)


def prompt_payload(state: Any) -> dict[str, Any]:
    """LLM 입력 dict (HJ BaseAgent._call_llm 활용)."""
    profile = getattr(state, "data_profile", None) or {}
    eval_result = getattr(state, "eval_result", None) or {}  # ★ X-3/X-6: metrics+per-row eval_result

    return {
        "category": "anomaly_detection",
        "user_intent": getattr(state, "user_intent", None),
        "contamination_estimate": profile.get("contamination_estimate"),
        "auc": eval_result.get("auc"),
        "pr_at_10": eval_result.get("pr_at_10"),
        "f1": eval_result.get("f1"),
        "top_n_anomalies": _extract_top_n_anomalies(state, n=TOP_N_DEFAULT),
        "top_features": _get_top_features(state, k=TOP_FEATURES_K),
        "threshold": eval_result.get("threshold"),
        "system_prompt": SYSTEM_PROMPT,
    }


def fallback(state: Any) -> str:
    """LLM 실패 시 한국어 템플릿 (generate 와 동일 — 한국어 보장)."""
    return generate(state)
