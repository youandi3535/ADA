"""테스트 — 데이터·주제 유연 대응 디벨롭 X1·X3·X4·X5·X6 (2026-06-05).

X1 profiler 타겟 자동 추천 (target 미명시 graceful)
X3 evaluator 적응형 임계 (n_rows 따라 동적)
X5 profiler missing_ratio + preprocessor 단기 강등 권고
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


# ════════════════════════════════════════════════════════
# X1 — 타겟 자동 추천
# ════════════════════════════════════════════════════════
class TestSuggestTargetCandidates:
    def test_helper_exists(self):
        from agents.handlers.timeseries.profiler import _suggest_target_candidates

        assert callable(_suggest_target_candidates)

    def test_recommend_high_autocorr_column(self):
        from agents.handlers.timeseries.profiler import _suggest_target_candidates

        rng = np.random.default_rng(42)
        n = 100
        # ts_col : 강한 자기상관 (랜덤워크)
        ts_col = np.cumsum(rng.normal(0, 1, n))
        # noise_col : 백색 잡음 (자기상관 없음)
        noise_col = rng.normal(0, 1, n)
        df = pd.DataFrame({"ds": pd.date_range("2024-01-01", periods=n), "ts": ts_col, "noise": noise_col})
        cands = _suggest_target_candidates(df, date_col="ds", top_k=2)
        assert len(cands) >= 1
        # ts 가 noise 보다 점수 높아야 (자기상관 차이)
        assert cands[0]["column"] == "ts"
        assert cands[0]["autocorr_lag1"] > 0.5

    def test_skip_high_missing(self):
        from agents.handlers.timeseries.profiler import _suggest_target_candidates

        n = 50
        df = pd.DataFrame(
            {
                "ds": pd.date_range("2024-01-01", periods=n),
                "many_missing": [np.nan] * 30 + list(range(20)),  # 60% 결측
            }
        )
        cands = _suggest_target_candidates(df, date_col="ds")
        # many_missing 제외됨 (50% 이상 결측)
        cols = [c["column"] for c in cands]
        assert "many_missing" not in cols

    def test_empty_for_short_df(self):
        from agents.handlers.timeseries.profiler import _suggest_target_candidates

        df = pd.DataFrame({"y": [1.0, 2.0, 3.0]})
        assert _suggest_target_candidates(df) == []


# ════════════════════════════════════════════════════════
# X3 — evaluator 적응형 임계
# ════════════════════════════════════════════════════════
class TestAdaptiveThresholds:
    def test_short_series_relaxes_mase(self, ts_state):
        from agents.handlers.timeseries.evaluator import THRESHOLDS, _adaptive_thresholds

        s = ts_state.with_update(data_profile={"rows": 50})
        th = _adaptive_thresholds(s)
        assert th["MASE_max"] > THRESHOLDS["MASE_max"]  # 완화됨

    def test_long_series_tightens_mase(self, ts_state):
        from agents.handlers.timeseries.evaluator import THRESHOLDS, _adaptive_thresholds

        s = ts_state.with_update(data_profile={"rows": 2000})
        th = _adaptive_thresholds(s)
        assert th["MASE_max"] < THRESHOLDS["MASE_max"]  # 강화됨

    def test_medium_series_uses_default(self, ts_state):
        from agents.handlers.timeseries.evaluator import THRESHOLDS, _adaptive_thresholds

        s = ts_state.with_update(data_profile={"rows": 500})
        th = _adaptive_thresholds(s)
        assert th["MASE_max"] == THRESHOLDS["MASE_max"]


# ════════════════════════════════════════════════════════
# X5 — missing_ratio + 단기 강등 권고
# ════════════════════════════════════════════════════════
class TestMissingRatioAndShortHorizon:
    def test_short_horizon_hint_appears_when_high_missing(self, ts_state):
        from agents.handlers.timeseries.preprocessor import plan

        s = ts_state.with_update(data_profile={"rows": 200, "missing_ratio": 0.40})
        steps = plan(s)
        names = [step.get("name") for step in steps]
        assert "_meta_short_horizon_hint" in names
        meta_step = next(st for st in steps if st.get("name") == "_meta_short_horizon_hint")
        assert meta_step["missing_ratio"] == 0.40

    def test_no_short_horizon_hint_when_low_missing(self, ts_state):
        from agents.handlers.timeseries.preprocessor import plan

        s = ts_state.with_update(data_profile={"rows": 200, "missing_ratio": 0.05})
        steps = plan(s)
        names = [step.get("name") for step in steps]
        assert "_meta_short_horizon_hint" not in names
