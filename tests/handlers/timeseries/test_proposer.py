"""CS 단독 — timeseries proposer 테스트 (cs-day4 v3 디벨롭).

검증:
  ① DoD — g1 길이 3 / g2 길이 1 / 모든 score ∈ [0,1]
  ② eda None → default recipes (인라인 안전)
  ③ user_intent +0.30 (단기/이상/계절)
  ④ changepoints 단계 가중 (1~2 +0.10, 3+ +0.15) + 이분산 +0.10
  ⑤ target_kind cumulative → 단기 보너스
  ⑥ §F meta — variate/forecast_kind/task_kind/horizon_hint
  ⑦ rationale R-501 수치 인용
"""

from __future__ import annotations


def _state(eda=None, profile=None, intent=None):
    """가벼운 state 더블 (PipelineState 의존 최소화)."""

    class _S:
        eda_summary = eda
        data_profile = profile if profile is not None else {"rows": 144, "freq": "M"}
        user_intent = intent

    return _S()


# ── ① DoD ─────────────────────────────────────────────────────────────────────


def test_g1_length_and_score_range():
    from agents.handlers.timeseries.proposer import g1

    eda = {"seasonal_period": 12, "stationary": False, "changepoints": 0}
    recipes = g1(_state(eda=eda))
    assert len(recipes) == 3
    for r in recipes:
        assert 0.0 <= r["score"] <= 1.0
        assert {"id", "title", "rationale", "score"} <= r.keys()


def test_g2_length_and_score():
    from agents.handlers.timeseries.proposer import g2

    g = g2(_state())
    assert len(g) >= 1
    assert g[0]["title"] == "timeseries"
    assert 0.0 <= g[0]["score"] <= 1.0


# ── ② eda None → default ──────────────────────────────────────────────────────


def test_g1_no_eda_default():
    from agents.handlers.timeseries.proposer import g1

    recipes = g1(_state(eda=None))
    assert len(recipes) == 3
    assert recipes[0]["score"] == 0.85  # default base


# ── ③ user_intent +0.30 ───────────────────────────────────────────────────────


def test_g1_intent_forecast_wins():
    from agents.handlers.timeseries.proposer import g1

    eda = {"seasonal_period": None, "stationary": True, "changepoints": 0}
    recipes = g1(_state(eda=eda, intent="매출 예측하고 싶어"))
    top = recipes[0]
    assert "단기" in top["title"]


def test_g1_intent_anomaly_wins():
    from agents.handlers.timeseries.proposer import g1

    eda = {"seasonal_period": None, "stationary": True, "changepoints": 0}
    recipes = g1(_state(eda=eda, intent="이상 탐지"))
    top = recipes[0]
    assert "이상" in top["title"]


# ── ④ changepoints 단계 가중 + 이분산 ─────────────────────────────────────────


def test_g1_changepoints_tiered():
    from agents.handlers.timeseries.proposer import g1

    base_eda = {"seasonal_period": None, "stationary": True}
    # changepoint 많을수록 이상 점수 ↑
    r_cp0 = g1(_state(eda={**base_eda, "changepoints": 0}))
    r_cp1 = g1(_state(eda={**base_eda, "changepoints": 1}))
    r_cp3 = g1(_state(eda={**base_eda, "changepoints": 5}))

    def _anomaly_score(recipes):
        return next(r["score"] for r in recipes if "이상" in r["title"])

    assert _anomaly_score(r_cp1) > _anomaly_score(r_cp0)
    assert _anomaly_score(r_cp3) > _anomaly_score(r_cp1)  # 3건+ 가중 더 큼


def test_g1_heteroscedastic_boosts_anomaly():
    from agents.handlers.timeseries.proposer import g1

    base = {"seasonal_period": None, "stationary": True, "changepoints": 0}
    r_no = g1(_state(eda=base))
    r_yes = g1(_state(eda={**base, "heteroscedastic": True}))

    def _anom(recipes):
        return next(r["score"] for r in recipes if "이상" in r["title"])

    assert _anom(r_yes) > _anom(r_no)


# ── ⑤ target_kind cumulative → 단기 보너스 ────────────────────────────────────


def test_g1_cumulative_boosts_shortterm():
    from agents.handlers.timeseries.proposer import g1

    # 단기 점수가 clip 상한(1.0)에 닿지 않도록 stationary=True + n<100 으로 설정
    base = {"seasonal_period": None, "stationary": True, "changepoints": 0}
    prof = {"rows": 50, "freq": "D"}  # n<100 → 단기 -0.05
    r_no = g1(_state(eda=base, profile=prof))
    r_cum = g1(_state(eda={**base, "target_kind": "cumulative"}, profile=prof))

    def _short(recipes):
        return next(r["score"] for r in recipes if "단기" in r["title"])

    assert _short(r_cum) > _short(r_no)


# ── ⑥ §F meta ─────────────────────────────────────────────────────────────────


def test_g1_meta_present():
    from agents.handlers.timeseries.proposer import g1

    eda = {"seasonal_period": 12, "stationary": False, "changepoints": 2, "is_multivariate": True}
    recipes = g1(_state(eda=eda, profile={"rows": 144, "freq": "MS"}))
    for r in recipes:
        m = r["meta"]
        assert m["variate"] == "multivariate"  # is_multivariate True
        assert m["forecast_kind"] == "interval"  # changepoints>=1 → interval
        assert m["horizon_hint"] == 12  # seasonal_period
        assert "task_kind" in m


def test_g1_meta_anomaly_classification():
    from agents.handlers.timeseries.proposer import g1

    eda = {"seasonal_period": 7, "stationary": True, "changepoints": 0}
    recipes = g1(_state(eda=eda))
    anom = next(r for r in recipes if "이상" in r["title"])
    assert anom["meta"]["task_kind"] == "classification"
    short = next(r for r in recipes if "단기" in r["title"])
    assert short["meta"]["task_kind"] == "regression"


def test_g1_meta_univariate_point():
    """exog 없고 변동성 낮으면 univariate + point."""
    from agents.handlers.timeseries.proposer import g1

    eda = {"seasonal_period": 7, "stationary": True, "changepoints": 0, "is_multivariate": False}
    recipes = g1(_state(eda=eda))
    m = recipes[0]["meta"]
    assert m["variate"] == "univariate"
    assert m["forecast_kind"] == "point"


# ── ⑦ rationale R-501 수치 인용 ───────────────────────────────────────────────


def test_g1_rationale_cites_changepoints():
    from agents.handlers.timeseries.proposer import g1

    eda = {"seasonal_period": 12, "stationary": False, "changepoints": 4, "residual_std": 5.0, "total_std": 10.0}
    recipes = g1(_state(eda=eda))
    anom = next(r for r in recipes if "이상" in r["title"])
    assert "changepoints=4" in anom["rationale"]  # 실제값 인용


def test_g1_rationale_cumulative_hint():
    from agents.handlers.timeseries.proposer import g1

    eda = {"seasonal_period": None, "stationary": False, "changepoints": 0, "target_kind": "cumulative"}
    recipes = g1(_state(eda=eda))
    short = next(r for r in recipes if "단기" in r["title"])
    assert "차분" in short["rationale"]
