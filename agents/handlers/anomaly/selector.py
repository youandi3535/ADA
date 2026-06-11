"""agents.handlers.anomaly.selector — 이상탐지 모델 선택 (NY 담당, Day 5 v3).

진입함수 (dispatcher 자동 등록):
  - score(state, recipes=None) -> dict
      반환: {
        "top3": list[str],       # ★ X-1: 모델명 (dispatcher model_candidates 계약)
        "cards": list[dict],     # 점수 상세 (id/title/rationale/total_score/score_breakdown), 내부/테스트용
        "rationale": str,        # 전체 한 줄 요약
        "citations": list[str],  # R-501
      }

DoD: 시간 컬럼 있으면 TranAD 점수 up → top3 에 들어감.

점수 매트릭스 5 차원:
  base + dim + time (★ DoD) + contam + interp (★ A-1)

★ X-1 정정 (2026-05-29): top3 = list[str] 모델명 (디스패처 계약). 카드는 cards 분리. (옛 E-1 list[dict] 뒤집음)
★ V4 (2026-06-10): 6 차원 점수 (base/dim/time/contam/interp/local) — ECOD·HBOS 추가, 지역 이상치 LOF 부스트.
"""

from __future__ import annotations

from typing import Any

from agents.handlers.anomaly import proposer

# ── 모듈 상수 ─────────────────────────────────────────────────────
BASE_SCORE: dict[str, float] = {
    "IsolationForest": 0.85,
    "LOF": 0.70,
    "OneClassSVM": 0.75,
    "AutoEncoder": 0.65,
    "COPOD": 0.60,  # ★ FIX-3: COPOD 추가 (INTERPRETABILITY_SCORE 와 정합)
    "ECOD": 0.72,  # ★ V4: ADBench(NeurIPS 2022) 평균 무감독 상위권 — LOF 보다 약간 높게
    "HBOS": 0.55,  # ★ V4: 빠르지만 지역 이상치 약함 — 보수적 base
    "TranAD": 0.55,
    "AnomalyTransformer": 0.50,
}

DIM_PENALTY_LOF = -0.2
DIM_BONUS_IFOREST = 0.1
TIME_BONUS_TRANAD = 0.4  # ★ DoD (C-1·A-2 결정 — 동시 시나리오 보장)
TIME_BONUS_TRANSFORMER = 0.25
LOW_CONTAM_OCSVM_BONUS = 0.2
LOW_CONTAM_THRESHOLD = 0.02
HIGH_DIM_THRESHOLD = 50
MIN_ROWS_FOR_DL = 1000
DL_PENALTY_SMALL_DATA = -0.3
# ★ V4: 지역(local) 이상치 신호 — 단변량 통계는 침묵하는데 IF/LOF 만 발화하는
#   high_contamination_suspected 패턴은 군집 구조 내 지역 이상치의 전형
#   (Breunig et al., SIGMOD 2000 — LOF 가 설계된 바로 그 케이스).
#   이때 LOF 부스트 + (신뢰 불가한 contamination 추정 기반) OCSVM 보너스 차단.
LOCAL_STRUCTURE_LOF_BONUS = 0.25

# ★ A-1 결정 (2026-05-28): interpretability 5 번째 차원
INTERPRETABILITY_SCORE: dict[str, float] = {
    "IsolationForest": 0.1,  # node path 시각화 가능
    "LOF": 0.1,  # 이웃 거리 직관적
    "OneClassSVM": 0.0,  # 결정 경계 시각화 어려움
    "AutoEncoder": -0.05,  # 재구성 오류 기여도 어려움
    "TranAD": -0.05,  # attention 일부 시각화
    "AnomalyTransformer": -0.1,  # 가장 black-box
    "COPOD": 0.1,  # ★ A-1 (Day 6) 추가 — dim_score 제공, ECDF 해석 가능
    "ECOD": 0.1,  # ★ V4: 차원별 꼬리확률 분해 → '왜 이상?' 직접 답변 가능
    "HBOS": 0.05,  # ★ V4: 차원별 히스토그램 — 시각화 쉬움
}


# ── 헬퍼 ──────────────────────────────────────────────────────────


def _compute_base_score(model_name: str, n_rows: int) -> float:
    """모델별 기본 적합도 + 딥러닝 소규모 페널티."""
    base = BASE_SCORE.get(model_name, 0.0)
    if model_name in {"AutoEncoder", "TranAD", "AnomalyTransformer"}:
        if n_rows < MIN_ROWS_FOR_DL:
            base += DL_PENALTY_SMALL_DATA
    return base


def _compute_dim_bonus(model_name: str, n_dim: int) -> float:
    """차원성 보너스/페널티."""
    if model_name == "LOF" and n_dim > HIGH_DIM_THRESHOLD:
        return DIM_PENALTY_LOF
    if model_name in ("IsolationForest", "ECOD") and n_dim > HIGH_DIM_THRESHOLD:
        # ★ V4: ECOD 도 차원별 독립 추정 → 고차원 보너스 (IForest 와 동일 근거)
        return DIM_BONUS_IFOREST
    return 0.0


def _compute_time_bonus(model_name: str, has_time: bool) -> float:
    """시간성 보너스 (★ DoD)."""
    if not has_time:
        return 0.0
    if model_name == "TranAD":
        return TIME_BONUS_TRANAD
    if model_name == "AnomalyTransformer":
        return TIME_BONUS_TRANSFORMER
    return 0.0


def _compute_contam_bonus(model_name: str, contam: float, contam_unreliable: bool = False) -> float:
    """오염도 보너스 (저오염 → OCSVM 강화).

    ★ V4: contamination 추정이 신뢰 불가(high_contamination_suspected)하면
    저오염 보너스를 주지 않음 — 가짜 저오염(지역 이상치 침묵)에 OCSVM 오선정 방지.
    """
    if contam_unreliable:
        return 0.0
    if contam < LOW_CONTAM_THRESHOLD and model_name == "OneClassSVM":
        return LOW_CONTAM_OCSVM_BONUS
    return 0.0


def _compute_local_bonus(model_name: str, local_suspected: bool) -> float:
    """★ V4: 지역 이상치 의심 시 LOF 부스트 (Breunig et al. 2000)."""
    if local_suspected and model_name == "LOF":
        return LOCAL_STRUCTURE_LOF_BONUS
    return 0.0


def _compute_interp_bonus(model_name: str) -> float:
    """★ A-1: interpretability 보너스 (설명 가능 모델 가중).

    이상탐지 도메인 본질 — '왜 이상?' 설명 가능성이 Day 8 Insight 보고서 품질 좌우.
    """
    return INTERPRETABILITY_SCORE.get(model_name, 0.0)


def _build_score_matrix(state: Any, model_cards: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """전체 점수 매트릭스 조립 (5 차원 — A-1 결정).

    ★ B-2 결정: n_dim 우선순위 = preprocessing.n_cols_out > dim > cols > 0
    (PCA 적용 시 실제 모델이 받는 차원 우선)
    """
    profile = getattr(state, "data_profile", None) or {}
    n_rows = int(profile.get("rows", 0))
    pp = (getattr(state, "category_extras", {}) or {}).get("anomaly", {}).get("preprocessing", {}) or {}
    n_dim = int(pp.get("n_cols_out") or profile.get("dim") or profile.get("cols") or 0)  # ★ B-2
    has_time = bool(profile.get("has_time_column", False))
    contam = float(profile.get("contamination_estimate", 0.05))
    # ★ V4: 지역 이상치 신호 — local_anomaly_suspected(정밀) 우선, 구 키 fallback
    local_suspected = bool(
        profile.get("local_anomaly_suspected", False) or profile.get("high_contamination_suspected", False)
    )

    matrix: dict[str, dict[str, float]] = {}
    for card in model_cards:
        name = card.get("title", "")
        if not name:
            continue
        base = _compute_base_score(name, n_rows)
        dim_b = _compute_dim_bonus(name, n_dim)
        time_b = _compute_time_bonus(name, has_time)
        contam_b = _compute_contam_bonus(name, contam, contam_unreliable=local_suspected)  # ★ V4
        interp_b = _compute_interp_bonus(name)  # ★ A-1
        local_b = _compute_local_bonus(name, local_suspected)  # ★ V4
        matrix[name] = {
            "base": base,
            "dim": dim_b,
            "time": time_b,
            "contam": contam_b,
            "interp": interp_b,  # ★ A-1
            "local": local_b,  # ★ V4
            "total": base + dim_b + time_b + contam_b + interp_b + local_b,
        }
    return matrix


# ── 카드 빌더 (E-1 결정 후 추가) ──────────────────────────────────


def _build_card(rank: int, name: str, breakdown: dict[str, float]) -> dict[str, Any]:
    """top3 카드 dict 5 키 (id/title/rationale/total_score/score_breakdown).

    ★ A-1 결정: score_breakdown 5 키 (base/dim/time/contam/interp).
    ★ E-2 결정: rationale 한국어 통일 (DL→딥러닝, black-box→블랙박스).
    """
    parts: list[str] = []
    if breakdown["time"] > 0:
        parts.append(f"시간성 보너스 +{breakdown['time']:.1f} ★")
    if breakdown["contam"] > 0:
        parts.append(f"저오염 보너스 +{breakdown['contam']:.1f}")
    if breakdown["dim"] > 0:
        parts.append(f"차원 보너스 +{breakdown['dim']:.1f}")
    elif breakdown["dim"] < 0:
        parts.append(f"고차원 페널티 {breakdown['dim']:.1f}")
    if breakdown["interp"] > 0:
        parts.append(f"설명 가능 보너스 +{breakdown['interp']:.2f}")
    elif breakdown["interp"] < 0:
        parts.append(f"블랙박스 페널티 {breakdown['interp']:.2f}")  # ★ E-2
    if breakdown.get("local", 0.0) > 0:
        parts.append(f"지역 이상치 보너스 +{breakdown['local']:.2f} ★V4")
    if breakdown["base"] < BASE_SCORE.get(name, 0.0):
        parts.append("딥러닝 소규모 페널티")  # ★ E-2
    rationale = ", ".join(parts) or "기본 점수"
    return {
        "id": rank,
        "title": name,
        "rationale": rationale,
        "total_score": breakdown["total"],
        "score_breakdown": {
            "base": breakdown["base"],
            "dim": breakdown["dim"],
            "time": breakdown["time"],
            "contam": breakdown["contam"],
            "interp": breakdown["interp"],  # ★ A-1
            "local": breakdown.get("local", 0.0),  # ★ V4
        },
    }


# ── 진입점 ────────────────────────────────────────────────────────


def score(state: Any, recipes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """모델 선정 점수화. dispatcher 계약: top3 = list[str].

    반환 키:
        - top3       : list[str]   — 모델명 (model_selection dispatcher 가 직접 소비)
        - cards      : list[dict]  — 점수 상세, 디버깅·테스트용
        - rationale  : str         — 전체 한 줄 요약
        - citations  : list[str]   — R-501 KB 인용

    ★ X-1 정정 (2026-05-29): top3 = list[str] 모델명 (옛 E-1 list[dict] 뒤집음).
        E-1 (구) → X-1 (현). dispatcher (model_selection.py) 가 list[str] 만 인식.
    proposer.g2() 호출 → 5 차원 점수 매트릭스 (base/dim/time/contam/interp) → top3 빌드.
    """
    recipes = recipes or []

    try:
        model_cards = proposer.g2(state)
    except Exception:
        model_cards = []

    if not model_cards:
        return {"top3": [], "rationale": "proposer.g2() empty", "citations": []}

    matrix = _build_score_matrix(state, model_cards)
    if not matrix:
        return {"top3": [], "rationale": "score matrix empty", "citations": []}

    # total 내림차순 정렬 (동점 → 사전순)
    sorted_models = sorted(matrix.items(), key=lambda x: (-x[1]["total"], x[0]))

    # ★ X-1 수정 (2026-05-29): top3 = 모델명 list[str] — dispatcher model_candidates 계약.
    #    tuner/executor 가 model_name 문자열로 사용 (AnomalyPipeline.train(model_name=...)).
    #    카드 상세(rationale/score_breakdown)는 "cards" 키로 분리.

    cards = []
    top3_names = []
    for rank, (name, breakdown) in enumerate(sorted_models[:3], start=1):
        cards.append(_build_card(rank, name, breakdown))
        top3_names.append(name)

    rationale_lines = [f"{c['id']}. {c['title']} — {c['rationale']}" for c in cards]
    rationale = "\n".join(rationale_lines) if rationale_lines else "후보 없음"

    citations = [r["hash"] for r in (recipes or []) if r.get("hash")]

    return {
        "top3": top3_names,
        "cards": cards,
        "rationale": rationale,
        "citations": citations,
    }
