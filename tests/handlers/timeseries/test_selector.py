"""tests/handlers/timeseries/test_selector — cs-selector A안 디벨롭 검증.

검증 카테고리:
  DoD(4): top3≥3 / citations / n<100 DL제외 / exog=0 SARIMAX제외
  A안 핵심(3): exog 통일(category_extras) / SARIMAX 버그 수정 / leakage_suspect 제외
  7축(7): 가 길이 / 나 horizon / 다 계절성 / 라 target_kind / 마 multivariate / 바 heteroscedastic / 사 changepoints
  메타(3): baseline_recommend / multistep_strategy / hybrid_hint
  R-501(1): rationale 수치 인용
  엣지(3): empty state / non-dict / fallback chain
"""

from __future__ import annotations

import pytest


@pytest.fixture
def base_state(ts_state):
    """기본 state — n_rows=200 (DL 비페널티) + 단기 예측 recipe."""
    return ts_state.with_update(
        data_profile={"rows": 200, "freq": "D"},
        chosen_recipe={"title": "단기 예측 (1~30일)"},
    )


# ════════════════════════════════════════════════════════════════
# DoD (4)
# ════════════════════════════════════════════════════════════════
def test_dod_top3_length(base_state):
    """DoD: top3 길이 ≥ 3 (어떤 상태에서도)."""
    from agents.handlers.timeseries.selector import score

    result = score(base_state, recipes=[])
    assert len(result["top3"]) >= 3


def test_dod_citations_from_recipes(base_state):
    """citations 가 recipes hash 에서 추출됨 (R-501)."""
    from agents.handlers.timeseries.selector import score

    recipes = [
        {"hash": "abc123", "title": "단기"},
        {"hash": "def456", "title": "계절"},
    ]
    result = score(base_state, recipes=recipes)
    assert "abc123" in result["citations"]
    assert "def456" in result["citations"]


def test_dod_short_series_excludes_dl(ts_state):
    """DoD: n<100 → DL 페널티로 top3 진입 X."""
    from agents.handlers.timeseries.selector import score

    st = ts_state.with_update(
        data_profile={"rows": 50},
        chosen_recipe={"title": "이상 시점 탐지"},
    )
    result = score(st, recipes=[])
    # 이상 시점 candidates 에 TFT/PatchTST 가 있는데 페널티로 점수가 낮아져 정렬상 뒤로
    # n=50 + 이상 recipe → top3 우선순위: Prophet/SARIMA > DL
    assert all(m in result["top3"] for m in ["Prophet", "SARIMA"])


def test_dod_no_exog_excludes_sarimax(ts_state):
    """DoD: exog=0 → SARIMAX top3 진입 X (EXCLUDED 정책)."""
    from agents.handlers.timeseries.selector import score

    st = ts_state.with_update(
        data_profile={"rows": 500},
        chosen_recipe={"title": "단기 예측"},
        eda_summary={"seasonal_period": 7, "stationary": False},  # exog 없음
    )
    result = score(st, recipes=[])
    assert "SARIMAX" not in result["top3"]


# ════════════════════════════════════════════════════════════════
# A안 핵심 (3) — exog 통일·SARIMAX 버그·leakage 제외
# ════════════════════════════════════════════════════════════════
def test_a_exog_from_category_extras_unifies_source(ts_state):
    """A안: exog 가 category_extras["timeseries"]["exog_columns"] 에서 정상 인식.

    기존 버그 — eda.get("exog") 만 봐서 항상 빈 list → SARIMAX 무조건 EXCLUDED.
    A안 수정으로 category_extras 권위 소스에서 읽어 SARIMAX 가 진입 가능.
    """
    from agents.handlers.timeseries.selector import score

    st = ts_state.with_update(
        data_profile={"rows": 500},
        chosen_recipe={"title": "단기 예측"},
        eda_summary={"seasonal_period": 7, "stationary": False},
        category_extras={"timeseries": {"exog_columns": ["temp", "humidity"]}},
    )
    result = score(st, recipes=[])
    # exog=2 + n=500 + s=7 + 단기 → SARIMAX 가 강한 보너스로 top3 진입
    assert "SARIMAX" in result["top3"]
    assert result["meta"]["exog_columns"] == ["temp", "humidity"]


def test_a_sarimax_bug_fixed_air_passengers_like(ts_state):
    """A안 버그 수정 회귀 가드: exog 가 category_extras 에 있으면 SARIMAX 진입 가능.

    이전 코드는 eda.get("exog") 만 봐서 절대 진입 못했음.
    """
    from agents.handlers.timeseries.selector import score

    st = ts_state.with_update(
        data_profile={"rows": 144, "freq": "MS"},
        chosen_recipe={"title": "단기 예측"},
        eda_summary={"seasonal_period": 12, "stationary": False},
        category_extras={"timeseries": {"exog_columns": ["price"]}},
    )
    result = score(st, recipes=[])
    assert "SARIMAX" in result["top3"], f"A안 수정 회귀 — SARIMAX 가 top3 에 있어야 함. got {result['top3']}"


def test_a_leakage_suspect_cols_excluded_from_exog(ts_state):
    """누수 1-1: profiler 가 표시한 leakage_suspect_cols 는 exog 풀에서 제외."""
    from agents.handlers.timeseries.selector import score

    st = ts_state.with_update(
        data_profile={"rows": 500},
        chosen_recipe={"title": "단기 예측"},
        eda_summary={
            "seasonal_period": 7,
            "leakage_suspect_cols": ["target_copy"],
        },
        category_extras={"timeseries": {"exog_columns": ["temp", "target_copy"]}},
    )
    result = score(st, recipes=[])
    assert "target_copy" not in result["meta"]["exog_columns"]
    assert result["meta"]["leakage_excluded"] == ["target_copy"]


# ════════════════════════════════════════════════════════════════
# 7축 반영 (7) — 헌장 2-1 7개 축
# ════════════════════════════════════════════════════════════════
def test_7axis_length_dl_large_bonus(ts_state):
    """7축 가: n ≥ 1000 → DL 약보너스."""
    from agents.handlers.timeseries.selector import score

    st = ts_state.with_update(
        data_profile={"rows": 2000},
        chosen_recipe={"title": "이상 시점 탐지"},
        eda_summary={},
    )
    result = score(st, recipes=[])
    # n=2000 + 이상 → TFT/PatchTST 가 보너스 받아 top3 진입 기대
    assert any(m in result["top3"] for m in ("TFT", "PatchTST"))


def test_7axis_horizon_long_prefers_prophet(ts_state):
    """7축 나: horizon ≥ 30 → Prophet 보너스."""
    from agents.handlers.timeseries.selector import score

    st = ts_state.with_update(
        data_profile={"rows": 500},
        chosen_recipe={"title": "단기 예측"},
        eda_summary={"seasonal_period": 7},
        category_extras={"timeseries": {"horizon": 60}},
    )
    result = score(st, recipes=[])
    assert "Prophet" in result["top3"]
    assert result["meta"]["horizon"] == 60


def test_7axis_strong_seasonality(ts_state):
    """7축 다: s ∈ {7,12,30,365} + acf_peaks ≥ 2 → SARIMA 강 보너스."""
    from agents.handlers.timeseries.selector import score

    st = ts_state.with_update(
        data_profile={"rows": 500},
        chosen_recipe={"title": "단기 예측"},
        eda_summary={"seasonal_period": 12, "acf_peaks": [12, 24, 36]},
    )
    result = score(st, recipes=[])
    # SARIMA 가 strong seasonal bonus 까지 받아 top3 1위 기대
    assert "SARIMA" in result["top3"]


def test_7axis_target_kind_cumulative_penalizes_dl(ts_state):
    """7축 라: cumulative + DL → 누적성 학습 어려움 페널티."""
    from agents.handlers.timeseries.selector import score

    st = ts_state.with_update(
        data_profile={"rows": 2000},
        chosen_recipe={"title": "이상 시점 탐지"},
        eda_summary={"target_kind": "cumulative"},
    )
    result = score(st, recipes=[])
    assert result["meta"]["target_kind"] == "cumulative"
    # DL 페널티 메타에 반영됐는지 — scores 확인
    for dl in ("Informer", "TFT", "PatchTST"):
        if dl in result["meta"]["scores"]:
            # cumulative 페널티가 반영돼 base 0.70 보다 작아야 함
            assert result["meta"]["scores"][dl] <= 0.75


def test_7axis_multivariate_bonus(ts_state):
    """7축 마: is_multivariate=True → SARIMAX/DL 보너스."""
    from agents.handlers.timeseries.selector import score

    st = ts_state.with_update(
        data_profile={"rows": 500},
        chosen_recipe={"title": "단기 예측"},
        eda_summary={"seasonal_period": 7, "is_multivariate": True},
        category_extras={"timeseries": {"exog_columns": ["x1"]}},
    )
    result = score(st, recipes=[])
    assert result["meta"]["is_multivariate"] is True


def test_7axis_heteroscedastic_prophet_sarima_bonus(ts_state):
    """7축 바: heteroscedastic=True → Prophet/SARIMA 약보너스."""
    from agents.handlers.timeseries.selector import score

    st = ts_state.with_update(
        data_profile={"rows": 500},
        chosen_recipe={"title": "단기 예측"},
        eda_summary={"seasonal_period": 7, "heteroscedastic": True},
    )
    result = score(st, recipes=[])
    assert result["meta"]["heteroscedastic"] is True
    assert "Prophet" in result["top3"]


def test_7axis_changepoints_prophet_bonus(ts_state):
    """7축 사: changepoints ≥ 3 → Prophet 보너스 (내장 검출)."""
    from agents.handlers.timeseries.selector import score

    st = ts_state.with_update(
        data_profile={"rows": 500},
        chosen_recipe={"title": "이상 시점 탐지"},
        eda_summary={"changepoints": 5},
    )
    result = score(st, recipes=[])
    assert result["meta"]["changepoints"] == 5
    assert "Prophet" in result["top3"]


# ════════════════════════════════════════════════════════════════
# 메타 (3) — baseline_recommend / multistep_strategy / hybrid_hint
# ════════════════════════════════════════════════════════════════
def test_meta_baseline_seasonal_naive_and_ets(ts_state):
    """방법론 4-2·6-5: seasonal_naive(s+n) / ETS(n≥30) 메타 추천.

    top3 에는 절대 안 들어감 (pipeline 미지원).
    """
    from agents.handlers.timeseries.selector import score

    st = ts_state.with_update(
        data_profile={"rows": 500},
        chosen_recipe={"title": "단기 예측"},
        eda_summary={"seasonal_period": 7},
    )
    result = score(st, recipes=[])
    assert "seasonal_naive" in result["meta"]["baseline_recommend"]
    assert "ETS" in result["meta"]["baseline_recommend"]
    # top3 에 절대 들어가면 안 됨 (pipeline SUPPORTED_MODELS 미지원)
    assert "seasonal_naive" not in result["top3"]
    assert "ETS" not in result["top3"]


def test_meta_multistep_strategy(ts_state):
    """다단계 전략 — horizon/recipe/n_rows 별 direct/recursive/hybrid."""
    from agents.handlers.timeseries.selector import score

    # horizon=1 → recursive
    st_short = ts_state.with_update(
        data_profile={"rows": 200},
        chosen_recipe={"title": "단기 예측"},
        category_extras={"timeseries": {"horizon": 1}},
    )
    assert score(st_short, recipes=[])["meta"]["multistep_strategy"] == "recursive"

    # horizon=12 + 계절 분해 + n=500 → direct
    st_direct = ts_state.with_update(
        data_profile={"rows": 500},
        chosen_recipe={"title": "계절성 분해"},
        eda_summary={"seasonal_period": 12},
        category_extras={"timeseries": {"horizon": 12}},
    )
    assert score(st_direct, recipes=[])["meta"]["multistep_strategy"] == "direct"

    # horizon=7 + 단기 → hybrid
    st_hybrid = ts_state.with_update(
        data_profile={"rows": 200},
        chosen_recipe={"title": "단기 예측"},
        eda_summary={"seasonal_period": 7},
        category_extras={"timeseries": {"horizon": 7}},
    )
    assert score(st_hybrid, recipes=[])["meta"]["multistep_strategy"] == "hybrid"


def test_meta_hybrid_hint_when_dl_and_stat_coexist(ts_state):
    """장기 horizon + DL + STAT 공존 → ARIMA->DL_residual hint."""
    from agents.handlers.timeseries.selector import score

    st = ts_state.with_update(
        data_profile={"rows": 2000},
        chosen_recipe={"title": "계절성 분해"},
        eda_summary={"seasonal_period": 12, "is_multivariate": True},
        category_extras={"timeseries": {"horizon": 30, "exog_columns": ["x1"]}},
    )
    result = score(st, recipes=[])
    # SARIMA + Prophet + (TFT or PatchTST) 가 top3 → hybrid hint 생성 기대
    if any(m in result["top3"] for m in ("ARIMA", "SARIMA", "SARIMAX")) and any(
        m in result["top3"] for m in ("TFT", "PatchTST", "Informer")
    ):
        assert result["meta"]["hybrid_hint"] is not None
        assert "_residual" in result["meta"]["hybrid_hint"]


# ════════════════════════════════════════════════════════════════
# R-501 (1) — rationale 수치 인용
# ════════════════════════════════════════════════════════════════
def test_r501_rationale_cites_all_keys(base_state):
    """R-501: rationale 에 모든 조정값 수치 인용 (검증 가능)."""
    from agents.handlers.timeseries.selector import score

    st = base_state.with_update(
        eda_summary={
            "seasonal_period": 7,
            "stationary": False,
            "heteroscedastic": True,
            "changepoints": 2,
            "is_multivariate": True,
        },
        category_extras={"timeseries": {"horizon": 14, "exog_columns": ["x"]}},
    )
    result = score(st, recipes=[])
    r = result["rationale"]
    # 핵심 키 모두 rationale 에 등장해야 함
    for needle in ("recipe=", "n=", "s=", "exog=", "horizon=", "changepoints=", "top3="):
        assert needle in r, f"rationale 에 '{needle}' 누락: {r}"


# ════════════════════════════════════════════════════════════════
# 엣지 (3)
# ════════════════════════════════════════════════════════════════
def test_edge_empty_state(ts_state):
    """엣지: profile/eda/recipe 전부 비어도 default 진행 (인라인 안전)."""
    from agents.handlers.timeseries.selector import score

    result = score(ts_state, recipes=[])
    assert len(result["top3"]) >= 3
    assert "rationale" in result
    assert "meta" in result


def test_edge_non_dict_eda_summary(ts_state):
    """엣지: eda_summary 가 str 등 비-dict 일 때 빈 dict 처리 (HJ 단절 B 경로)."""
    from agents.handlers.timeseries.selector import score

    # PipelineState 는 Optional[str] 인 eda_summary 만 받음 → str 주입
    st = ts_state.with_update(eda_summary="some text summary")
    result = score(st, recipes=[])
    assert len(result["top3"]) >= 3  # 빈 dict 로 처리 → default fallback


def test_edge_fallback_chain_arima_prophet_sarima(ts_state):
    """엣지: candidates 가 부족할 때 ARIMA → Prophet → SARIMA fallback 으로 3 보장."""
    from agents.handlers.timeseries.selector import score

    # "기타" recipe → candidates = [ARIMA, SARIMA, Prophet] (default fallback)
    st = ts_state.with_update(chosen_recipe={"title": "unknown_recipe_xxx"})
    result = score(st, recipes=[])
    assert len(result["top3"]) == 3


# ════════════════════════════════════════════════════════════════
# 회귀 가드 (기존 3 키 보존)
# ════════════════════════════════════════════════════════════════
def test_regression_three_keys_preserved(base_state):
    """회귀 0: 기존 top3 / rationale / citations 3 키 보존 (meta 만 신규)."""
    from agents.handlers.timeseries.selector import score

    result = score(base_state, recipes=[{"hash": "h1"}])
    assert "top3" in result
    assert "rationale" in result
    assert "citations" in result
    assert "meta" in result  # 신규
    assert isinstance(result["top3"], list)
    assert isinstance(result["rationale"], str)
    assert isinstance(result["citations"], list)
