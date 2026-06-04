"""agents.handlers.anomaly.proposer — 게이트 fallback (NY, Day 4 v3).

LLM 호출 X (D2). 규칙 기반 score 산출.

- g1(state) -> list[dict]   G2 3 안 (점수화·정상학습·Top-N)
- g2(state) -> list[dict]   G3 모델 카드 4~6 종 (D1: has_time_column 분기)

DoD: contamination < 0.05 시 OCSVM 1 위 (D3·DoD).
의심 결정 8 (셜록홈즈 §Day 4).
"""

from __future__ import annotations

from typing import Any

# ── 모듈 상수 ─────────────────────────────────────────────────────
LOW_CONTAMINATION_THRESHOLD = 0.05  # D3
MIN_ROWS_FOR_AE = 500
MIN_ROWS_FOR_TRANSFORMER = 1000
HIGH_DIM_THRESHOLD = 20
TIME_BONUS = 0.3  # D8
OCSVM_LOW_CONTAM_BONUS = 0.4  # D3 · DoD
NEEDS_REVIEW_DEFAULT = False  # D7

# ★ D1 불변식 키 (ny-day10 후속): 시계열 전용 모델 — 시간 컬럼 없으면 절대 금지.
_TIME_SERIES_MODELS = frozenset({"TranAD", "AnomalyTransformer"})


# ── 공통 헬퍼 ─────────────────────────────────────────────────────
def _get_profile(state: Any) -> dict:
    return getattr(state, "data_profile", None) or {}


def _get_preprocessing(state: Any) -> dict:
    """E-7: category_extras 에서 읽음."""
    extras = getattr(state, "category_extras", None) or {}
    return extras.get("anomaly", {}).get("preprocessing", {}) or {}


def _clip(x: float) -> float:
    return min(max(x, 0.0), 1.0)


def _make_card(title: str, score: float, rationale: str) -> dict:
    return {
        "id": 0,
        "title": title,
        "rationale": rationale,
        "score": score,
        "needs_review": NEEDS_REVIEW_DEFAULT,
    }


# ── G2 score 헬퍼 (D4 데이터 기반) ────────────────────────────────
def _g1_score_scoring(profile: dict, preproc: dict) -> float:
    base = 0.85
    if profile.get("n_rows", 0) < 100:
        base -= 0.1
    return _clip(base)


def _g1_score_normal_learning(profile: dict, preproc: dict) -> float:
    base = 0.5
    if profile.get("contamination_estimate", 0.1) < LOW_CONTAMINATION_THRESHOLD:
        base += 0.3
    if profile.get("is_approximately_gaussian"):
        base += 0.1
    return _clip(base)


def _g1_score_top_n(profile: dict, preproc: dict) -> float:
    base = 0.6
    if profile.get("n_rows", 0) >= 10_000:
        base += 0.15
    return _clip(base)


# ── G3 모델 score 헬퍼 (D1·D3·D8) ─────────────────────────────────
def _g2_score_iforest(profile: dict, preproc: dict) -> float:
    return 0.7


def _g2_score_lof(profile: dict, preproc: dict) -> float:
    base = 0.5
    if profile.get("intrinsic_dim_ratio", 1.0) < 0.5:
        base += 0.2
    return _clip(base)


def _g2_score_ocsvm(profile: dict, preproc: dict) -> float:
    """★ DoD: contamination 낮으면 우위 (D3)."""
    base = 0.5
    if profile.get("contamination_estimate", 0.1) < LOW_CONTAMINATION_THRESHOLD:
        base += OCSVM_LOW_CONTAM_BONUS  # +0.4
    if profile.get("is_approximately_gaussian"):
        base += 0.1
    return _clip(base)


def _g2_score_autoencoder(profile: dict, preproc: dict) -> float:
    base = 0.5
    n_rows = profile.get("n_rows", 0)
    n_cols = preproc.get("n_cols_out", 0) or profile.get("n_numeric_cols", 0)
    if n_rows >= MIN_ROWS_FOR_AE:
        base += 0.2
    if n_cols > HIGH_DIM_THRESHOLD:
        base += 0.2
    return _clip(base)


def _g2_score_copod(profile: dict, preproc: dict) -> float:
    """★ FIX-3: COPOD — ECDF 기반, 고차원 친화적 (D6 추가).

    COPOD는 copula 함수로 각 차원의 이상치 확률을 독립 추정 — 해석 가능 + 빠름.
    """
    base = 0.55
    n_cols = preproc.get("n_cols_out", 0) or profile.get("n_numeric_cols", 0)
    if n_cols > HIGH_DIM_THRESHOLD:
        base += 0.1  # 고차원 우위 (copula independence assumption)
    if profile.get("is_approximately_gaussian"):
        base -= 0.1  # 가우시안이면 IForest/OCSVM 이 더 강함
    return _clip(base)


def _g2_score_tranad(profile: dict, preproc: dict) -> float:
    """시계열 모델 (D8 +0.3)."""
    if not profile.get("has_time_column"):
        return 0.0
    if profile.get("n_rows", 0) < MIN_ROWS_FOR_TRANSFORMER:
        return 0.0
    return 0.3 + TIME_BONUS


def _g2_score_anomaly_transformer(profile: dict, preproc: dict) -> float:
    if not profile.get("has_time_column"):
        return 0.0
    if profile.get("n_rows", 0) < MIN_ROWS_FOR_TRANSFORMER:
        return 0.0
    return 0.3 + TIME_BONUS


# ── 공개 진입점 1: G2 ────────────────────────────────────────────
def g1(state: Any) -> list[dict[str, Any]]:
    """G2 3 안 fallback (점수화·정상학습·Top-N)."""
    profile = _get_profile(state)
    preproc = _get_preprocessing(state)

    return [
        {
            "id": 1,
            "title": "이상치 점수화",
            "rationale": "샘플별 anomaly score 산출 — 모든 데이터에 가장 일반적",
            "score": _g1_score_scoring(profile, preproc),
            "needs_review": NEEDS_REVIEW_DEFAULT,
        },
        {
            "id": 2,
            "title": "정상 분포 학습",
            "rationale": "OneClassSVM/AE 가 정상만 학습 — contamination 낮을 때 강함",
            "score": _g1_score_normal_learning(profile, preproc),
            "needs_review": NEEDS_REVIEW_DEFAULT,
        },
        {
            "id": 3,
            "title": "Top-N 알림",
            "rationale": "상위 N 개 이상치만 리포트 — 빠른 운영·알림",
            "score": _g1_score_top_n(profile, preproc),
            "needs_review": NEEDS_REVIEW_DEFAULT,
        },
    ]


# ── 공개 진입점 2: G3 ────────────────────────────────────────────
def g2(state: Any) -> list[dict[str, Any]]:
    """G3 모델 카드 fallback (D1: 4~6 종 동적)."""
    profile = _get_profile(state)
    preproc = _get_preprocessing(state)

    cards = [
        _make_card(
            "IsolationForest", _g2_score_iforest(profile, preproc), "트리 기반, 가장 안정 — 모든 데이터 baseline"
        ),
        _make_card("LOF", _g2_score_lof(profile, preproc), "밀도 기반 — intrinsic_dim_ratio 낮은 저차원 우위"),
        _make_card(
            "OneClassSVM", _g2_score_ocsvm(profile, preproc), "정상 경계 학습 — contamination 낮을 때 강함 (★ DoD)"
        ),
        _make_card("AutoEncoder", _g2_score_autoencoder(profile, preproc), "딥러닝 — 큰 데이터·고차원 우위"),
        # ★ FIX-3: COPOD 추가 — g2 경로에서 항상 후보에 포함 (selector BASE_SCORE 정합)
        _make_card("COPOD", _g2_score_copod(profile, preproc), "Copula 기반 — 해석 가능 ECDF 이상치 확률, 고차원 친화"),
    ]

    # D1: 시계열 데이터면 트랜스포머 2 종 추가
    if profile.get("has_time_column"):
        cards.append(
            _make_card(
                "TranAD",
                _g2_score_tranad(profile, preproc),
                "시계열 트랜스포머 — 시간 + 큰 데이터 (≥1000행)",
            )
        )
        cards.append(
            _make_card(
                "AnomalyTransformer",
                _g2_score_anomaly_transformer(profile, preproc),
                "시계열 트랜스포머 — self-attention 기반",
            )
        )

    # ★ D1 불변식 (회귀 방지): 시간 컬럼이 없으면 시계열 트랜스포머는 절대 포함 금지.
    # score 헬퍼가 미래에 바뀌거나 머지 충돌로 카드가 새도 no-time 경로는
    # 반드시 base 4 종(IForest·LOF·OCSVM·AE)만 남도록 구조적으로 강제.
    if not profile.get("has_time_column"):
        cards = [c for c in cards if c["title"] not in _TIME_SERIES_MODELS]

    # score 0 제외 + 정렬 (내림차순)
    cards = [c for c in cards if c["score"] > 0]
    cards.sort(key=lambda c: c["score"], reverse=True)

    # id 재할당 (정렬 후)
    for i, c in enumerate(cards, 1):
        c["id"] = i

    return cards
