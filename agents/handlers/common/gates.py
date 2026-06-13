"""agents.handlers.common.gates — 카테고리 무관 평가 게이트 원시도구 (HJ 단독).

단일 고정 임계의 한계를 보완하는 "상대·유의성" 기준의 공통 표준.
각 카테고리 evaluator (tabular/timeseries/anomaly) 가 자기 지표·trivial baseline 에
맞춰 호출한다. 데이터마다 다른 trivial baseline(Dummy/naïve 등)을 그 변동성 기준으로
"유의하게" 이겼는지 판정함으로써, 절대 임계가 데이터 형태(불균형·스케일·클래스수)에
휘둘리는 문제를 보완한다.
"""

from __future__ import annotations


def significant_lift(
    model_score: float | None,
    baseline_score: float | None,
    baseline_std: float | None,
    *,
    k: float = 2.0,
    higher_better: bool = True,
) -> bool | None:
    """model 이 baseline 을 그 변동성(std)의 k 배 이상 차이로 이겼는가.

    절대 수치가 아니라 baseline 점수의 표준편차(예: CV fold std)를 기준으로 하므로
    데이터 스케일·난이도에 자동 적응한다. "Dummy 를 0.001 이겨도 통과" 같은
    약한 보증 대신, 우위가 noise 수준인지 통계적으로 본다.

    Parameters
    ----------
    model_score / baseline_score : float | None
        비교할 모델·기준선 점수 (동일 지표).
    baseline_std : float | None
        기준선 점수의 변동성. 없거나 <= 0 이면 판단 불가(None 반환).
    k : float
        유의 마진 배수 (기본 2.0 — rule of thumb "2σ").
    higher_better : bool
        True 면 큰 값이 좋음(F1/AUC/R²), False 면 작은 값이 좋음(RMSE/MASE).

    Returns
    -------
    bool | None
        True  — 유의하게 우수
        False — 우위가 noise 수준 (또는 baseline 이 더 좋음)
        None  — 판단 불가 (점수/표준편차 없음 또는 std <= 0)
    """
    if model_score is None or baseline_score is None or baseline_std is None:
        return None
    try:
        m = float(model_score)
        b = float(baseline_score)
        s = float(baseline_std)
    except (TypeError, ValueError):
        return None
    if s <= 0:
        return None
    diff = (m - b) if higher_better else (b - m)
    return bool(diff >= k * s)
