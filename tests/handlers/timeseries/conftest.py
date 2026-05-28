"""CS 단독 — timeseries 테스트 fixture.

Fixtures
--------
ts_state          : 합성 일별 데이터용 PipelineState (target="sales")
ts_df             : 120행 일별 데이터 (추세 + 7일 계절성)
air_passengers_df : AirPassengers 월별 데이터 144행 (1949-01 ~ 1960-12)
                    추세 + 연간(period=12) 계절성이 명확한 교과서 시계열
air_passengers_state : AirPassengers용 PipelineState (target="passengers")
"""

from __future__ import annotations

import pytest

# ── AirPassengers 원본 데이터 (Box & Jenkins, 1976) ──────────────────────────
# 1949-01 ~ 1960-12, 단위: 천 명, 총 144개월
_AIR_PASSENGERS = [
    112,
    118,
    132,
    129,
    121,
    135,
    148,
    148,
    136,
    119,
    104,
    118,  # 1949
    115,
    126,
    141,
    135,
    125,
    149,
    170,
    170,
    158,
    133,
    114,
    140,  # 1950
    145,
    150,
    178,
    163,
    172,
    178,
    199,
    199,
    184,
    162,
    146,
    166,  # 1951
    171,
    180,
    193,
    181,
    183,
    218,
    230,
    242,
    209,
    191,
    172,
    194,  # 1952
    196,
    196,
    236,
    235,
    229,
    243,
    264,
    272,
    237,
    211,
    180,
    201,  # 1953
    204,
    188,
    235,
    227,
    234,
    264,
    302,
    293,
    259,
    229,
    203,
    229,  # 1954
    242,
    233,
    267,
    269,
    270,
    315,
    364,
    347,
    312,
    274,
    237,
    278,  # 1955
    284,
    277,
    317,
    313,
    318,
    374,
    413,
    405,
    355,
    306,
    271,
    306,  # 1956
    315,
    301,
    356,
    348,
    355,
    422,
    465,
    467,
    404,
    347,
    305,
    336,  # 1957
    340,
    318,
    362,
    348,
    363,
    435,
    491,
    505,
    404,
    359,
    310,
    337,  # 1958
    360,
    342,
    406,
    396,
    420,
    472,
    548,
    559,
    463,
    407,
    362,
    405,  # 1959
    417,
    391,
    419,
    461,
    472,
    535,
    622,
    606,
    508,
    461,
    390,
    432,  # 1960
]


# ── 합성 일별 데이터 fixtures ─────────────────────────────────────────────────


@pytest.fixture
def require_statsmodels():
    """statsmodels 미설치 환경(CI 최소 deps)에서 해당 테스트를 skip."""
    pytest.importorskip("statsmodels")


@pytest.fixture
def ts_state():
    from ada.core.state import PipelineState

    return PipelineState(
        job_id="00000000-0000-0000-0000-000000000a01",
        file_id="uploads/test/sales.csv",
        category="timeseries",
        target_column="sales",
        user_intent="다음 7일 매출 예측",
    )


@pytest.fixture
def ts_df():
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=120, freq="D"),
            "sales": (1000 + rng.normal(0, 50, 120).cumsum() + np.sin(np.arange(120) * 2 * np.pi / 7) * 30),
        }
    )


# ── AirPassengers 데모 fixtures ───────────────────────────────────────────────


@pytest.fixture
def air_passengers_df():
    """AirPassengers 월별 승객 수 데이터 (144행, 1949-01 ~ 1960-12).

    특징:
      - 강한 상승 추세 (112 → 432)
      - 뚜렷한 연간 계절성 (period=12, 여름 피크)
      - 분산이 평균에 비례(곱셈 모형) → log 변환 필요 여부 테스트에 유용
    """
    import pandas as pd

    return pd.DataFrame(
        {
            "date": pd.date_range("1949-01", periods=144, freq="MS"),
            "passengers": _AIR_PASSENGERS,
        }
    )


@pytest.fixture
def air_passengers_state():
    """AirPassengers 데이터 전용 PipelineState."""
    from ada.core.state import PipelineState

    return PipelineState(
        job_id="00000000-0000-0000-0000-000000000a02",
        file_id="uploads/test/air_passengers.csv",
        category="timeseries",
        target_column="passengers",
        user_intent="항공 승객 수 월별 예측",
    )
