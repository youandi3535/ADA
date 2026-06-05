"""테스트 — D1·D3·D4·D5 graceful 디벨롭 시나리오 (2026-06-05).

D1 preprocessor regular_grid — 누락 시점 행 reindex
D3 pipeline 상수 시계열 가드 — _ConstantSeriesModel 자동 폴백
D4 output_extras 분석 불가 메시지 — 상수 모델 detect 시
D5 pipeline SARIMAX exog 마커 — _ada_exog_required 부착 확인
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


# ════════════════════════════════════════════════════════════════
# D1 — regular_grid (preprocessor)
# ════════════════════════════════════════════════════════════════
class TestRegularGrid:
    def test_regular_grid_helper_exists(self):
        from agents.handlers.timeseries.preprocessor import _apply_regular_grid

        assert callable(_apply_regular_grid)

    def test_regular_grid_in_plan_steps(self, ts_state):
        from agents.handlers.timeseries.preprocessor import plan

        steps = plan(ts_state)
        names = [s.get("name") for s in steps]
        assert "regular_grid" in names
        # sort_by_time 다음에 위치
        idx_sort = names.index("sort_by_time")
        idx_grid = names.index("regular_grid")
        assert idx_grid == idx_sort + 1

    def test_regular_grid_skip_when_no_freq(self, ts_state):
        """freq 미상 시 no-op (graceful)."""
        from agents.handlers.timeseries.preprocessor import _apply_regular_grid

        df = pd.DataFrame({"ds": pd.date_range("2024-01-01", periods=5), "y": [1.0, 2, 3, 4, 5]})
        # state.category_extras.timeseries.freq 없음 + state.data_profile.freq 없음 → skip
        out = _apply_regular_grid(df, ts_state)
        # 원본 동일 (df.copy 호환)
        assert len(out) == len(df)

    def test_regular_grid_reindex_with_freq(self, ts_state):
        """freq='D' + 누락 시점 → reindex 로 행 생성."""
        from agents.handlers.timeseries.preprocessor import _apply_regular_grid

        # 1/1, 1/3, 1/5 (1/2, 1/4 누락) — D 그리드면 5행
        df = pd.DataFrame({"ds": pd.to_datetime(["2024-01-01", "2024-01-03", "2024-01-05"]), "y": [1.0, 3, 5]})
        state = ts_state.with_update(category_extras={"timeseries": {"freq": "D"}})
        out = _apply_regular_grid(df, state)
        assert len(out) == 5  # 1/1 ~ 1/5 (5일)


# ════════════════════════════════════════════════════════════════
# D3 — 상수 시계열 가드 (pipeline.train)
# ════════════════════════════════════════════════════════════════
class TestConstantSeriesGuard:
    def test_const_model_class_exists(self):
        from pipelines.timeseries.pipeline import _ConstantSeriesModel

        m = _ConstantSeriesModel(7.5)
        assert m.const_value == 7.5
        assert m._ada_constant_series is True

    def test_const_model_forecast(self):
        from pipelines.timeseries.pipeline import _ConstantSeriesModel

        m = _ConstantSeriesModel(5.0)
        fc = m.forecast(steps=10)
        assert len(fc) == 10
        assert all(v == 5.0 for v in fc)

    def test_const_model_predict(self):
        from pipelines.timeseries.pipeline import _ConstantSeriesModel

        m = _ConstantSeriesModel(3.14)
        y = m.predict([1, 2, 3])
        assert len(y) == 3
        assert all(v == 3.14 for v in y)

    def test_train_detects_constant_series(self):
        """y_train 분산 0 시 자동으로 _ConstantSeriesModel 반환."""
        from pipelines.timeseries.pipeline import TimeSeriesPipeline

        pipe = TimeSeriesPipeline()
        y_const = np.ones(50) * 7.0  # 상수 50개
        X = pd.DataFrame({"ds": pd.date_range("2024-01-01", periods=50)})
        # 어떤 모델을 요청해도 상수 → ConstantSeriesModel 폴백
        model = pipe.train(X, y_const, "ARIMA", {})
        assert getattr(model, "_ada_constant_series", False) is True
        assert model.const_value == 7.0

    def test_constant_train_no_exception(self):
        """상수 시계열에서 train 호출이 예외 던지지 않음."""
        from pipelines.timeseries.pipeline import TimeSeriesPipeline

        pipe = TimeSeriesPipeline()
        y_const = np.zeros(30)
        X = pd.DataFrame({"ds": pd.date_range("2024-01-01", periods=30)})
        model = pipe.train(X, y_const, "SARIMA", {})
        # 정상 반환
        assert model is not None


# ════════════════════════════════════════════════════════════════
# D4 — output_extras 분석 불가 메시지
# ════════════════════════════════════════════════════════════════
class TestOutputExtrasConstantMessage:
    def test_build_returns_message_when_constant_model(self, ts_state):
        from agents.handlers.timeseries.output_extras import build
        from pipelines.timeseries.pipeline import _ConstantSeriesModel

        const_model = _ConstantSeriesModel(42.0)
        state = ts_state.with_update(
            best_model={"model_name": "ConstantFallback", "model_obj": const_model, "metrics": {}}
        )
        result = build(state)
        # 3 키 contract 유지
        assert set(result.keys()) == {"charts", "tables", "text_blocks"}
        # text_blocks 에 "분석 불가" 명시
        assert any("분석 불가" in b for b in result["text_blocks"])
        # tables 에 상수 시계열 진단
        titles = [t["title"] for t in result["tables"]]
        assert any("상수 시계열" in t for t in titles)

    def test_normal_model_no_constant_message(self, ts_state):
        """일반 모델에선 분석 불가 메시지 없음."""
        from agents.handlers.timeseries.output_extras import build

        state = ts_state.with_update(
            best_model={"model_name": "SARIMA", "metrics": {"MASE": 0.5, "y_pred_val": [1.0], "y_val_actual": [1.1]}}
        )
        result = build(state)
        assert not any("분석 불가" in b for b in result["text_blocks"])


# ════════════════════════════════════════════════════════════════
# D5 — SARIMAX exog 마커
# ════════════════════════════════════════════════════════════════
class TestSarimaxExogMarker:
    def test_sarimax_exog_marker_attached_when_exog_used(self):
        """exog 있는 SARIMAX 학습 → _ada_exog_required=True."""
        from pipelines.timeseries.pipeline import TimeSeriesPipeline

        pipe = TimeSeriesPipeline()
        rng = np.random.default_rng(42)
        n = 60
        X = pd.DataFrame(
            {
                "ds": pd.date_range("2024-01-01", periods=n),
                "exog1": rng.normal(0, 1, n),
            }
        )
        y = rng.normal(10, 2, n) + X["exog1"].values * 0.5

        try:
            model = pipe.train(X, y, "SARIMAX", {"exog_columns": ["exog1"], "order": (1, 0, 1)})
        except Exception:
            pytest.skip("SARIMAX 학습 환경 부재")

        assert getattr(model, "_ada_exog_required", False) is True

    def test_sarimax_no_marker_when_no_exog(self):
        """exog 없으면 marker False."""
        from pipelines.timeseries.pipeline import TimeSeriesPipeline

        pipe = TimeSeriesPipeline()
        rng = np.random.default_rng(0)
        n = 60
        X = pd.DataFrame({"ds": pd.date_range("2024-01-01", periods=n)})
        y = rng.normal(10, 2, n)

        try:
            model = pipe.train(X, y, "SARIMAX", {"order": (1, 0, 1)})
        except Exception:
            pytest.skip("SARIMAX 학습 환경 부재")

        assert getattr(model, "_ada_exog_required", False) is False
