"""Phase A~G 검증 테스트 — 26 종 SUPPORTED_MODELS 확장 + EXPERT_DIMENSIONS + search_space.

본 테스트는 라이브러리 미설치 환경에서도 실행 가능하도록 import 만 확인하고
실제 fit/predict 는 stub trial 로만 수행 (라이브러리 호출 없음).
"""

from __future__ import annotations

import importlib.util


def _load(module_path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, module_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pipeline_supported_models_26():
    """pipeline.SUPPORTED_MODELS 가 26 종이고 MODEL_FAMILY 와 키 정합."""
    pp = _load("pipelines/timeseries/pipeline.py", "_pp")
    assert len(pp.TimeSeriesPipeline.SUPPORTED_MODELS) == 26
    assert len(pp.TimeSeriesPipeline.MODEL_FAMILY) == 26
    assert set(pp.TimeSeriesPipeline.SUPPORTED_MODELS) == set(pp.TimeSeriesPipeline.MODEL_FAMILY.keys())
    # family 분포 — stat 9 / auto 4 / ml 6 / dl 7
    fam = pp.TimeSeriesPipeline.MODEL_FAMILY
    counts = {f: sum(1 for v in fam.values() if v == f) for f in ("stat", "auto", "ml", "dl")}
    assert counts == {"stat": 9, "auto": 4, "ml": 6, "dl": 7}


def test_pipeline_new_branches_present():
    """신규 19 종 모델 분기가 _train_dispatch 에 존재."""
    pp_src = open("pipelines/timeseries/pipeline.py", encoding="utf-8").read()
    new_models = [
        "STL",
        "VAR",
        "VARMA",
        "GARCH",
        "AutoARIMA",
        "AutoETS",
        "NeuralProphet",
        "LightGBM",
        "XGBoost",
        "CatBoost",
        "RandomForest",
        "Ridge",
        "Lasso",
        "TCN",
        "NHiTS",
        "NBEATS",
        "LSTM",
        "GRU",
        "DeepAR",
    ]
    for m in new_models:
        assert f'model_name == "{m}"' in pp_src, f"분기 누락: {m}"


def test_models_stat_classes_exist():
    """models_stat.py 의 4 wrapper 클래스 노출."""
    ms = _load("pipelines/timeseries/models_stat.py", "_ms")
    for cls in ("STLModel", "VARModel", "VARMAModel", "GARCHModel"):
        assert hasattr(ms, cls), f"models_stat 누락: {cls}"


def test_models_auto_classes_exist():
    ma = _load("pipelines/timeseries/models_auto.py", "_ma")
    for cls in ("AutoARIMAModel", "AutoETSModel", "NeuralProphetModel"):
        assert hasattr(ma, cls), f"models_auto 누락: {cls}"


def test_models_ml_classes_exist():
    mm = _load("pipelines/timeseries/models_ml.py", "_mm")
    for cls in ("LightGBMModel", "XGBoostModel", "CatBoostModel", "RandomForestModel", "RidgeModel", "LassoModel"):
        assert hasattr(mm, cls), f"models_ml 누락: {cls}"


def test_models_dl_classes_exist():
    md = _load("pipelines/timeseries/models_dl.py", "_md")
    for cls in ("TCNModel", "NHiTSModel", "NBEATSModel", "LSTMModel", "GRUModel", "RNNModel", "DeepARModel"):
        assert hasattr(md, cls), f"models_dl 누락: {cls}"


def test_search_space_20_new_models():
    """search_space.get_search_space 가 신규 20 종 모델에 dict 반환."""
    ss = _load("pipelines/timeseries/search_space.py", "_ss")

    class _Trial:
        study = None

        def suggest_int(self, name, lo, hi):
            return lo

        def suggest_float(self, name, lo, hi, log=False):
            return lo

        def suggest_categorical(self, name, choices):
            return choices[0]

    new_models = [
        "STL",
        "VAR",
        "VARMA",
        "GARCH",
        "AutoARIMA",
        "AutoETS",
        "NeuralProphet",
        "LightGBM",
        "XGBoost",
        "CatBoost",
        "RandomForest",
        "Ridge",
        "Lasso",
        "TCN",
        "NHiTS",
        "NBEATS",
        "LSTM",
        "GRU",
        "RNN",
        "DeepAR",
    ]
    for m in new_models:
        r = ss.get_search_space(m, _Trial())
        assert isinstance(r, dict), f"{m}: dict 반환 X"


def test_selector_expert_dimensions_26():
    """selector.EXPERT_DIMENSIONS 4 차원 × 26 모델 완전 매칭."""
    sel = _load("agents/handlers/timeseries/selector.py", "_sel")
    assert len(sel.SUPPORTED_MODELS) == 26
    assert set(sel.EXPERT_DIMENSIONS.keys()) == {
        "interpretability",
        "robustness",
        "uncertainty_quality",
        "retraining_cost",
    }
    for dim, tbl in sel.EXPERT_DIMENSIONS.items():
        for m in sel.SUPPORTED_MODELS:
            assert m in tbl, f"{dim} 차원 {m} 누락"
            assert 0.0 <= tbl[m] <= 1.0, f"{dim}.{m} 범위 벗어남"


def test_selector_candidate_pool_includes_new_models():
    """selector 의 recipe_key 별 candidates 풀이 신규 모델 포함."""
    sel_src = open("agents/handlers/timeseries/selector.py", encoding="utf-8").read()
    # 단기 예측 candidates 에 신규 ML/STL 포함
    assert "LightGBM" in sel_src
    assert "STL" in sel_src
    assert "AutoARIMA" in sel_src
    # 다변량 신호에서 VAR/VARMA 추가 분기
    assert "VAR" in sel_src
    # 변동성 신호에서 GARCH 추가
    assert "GARCH" in sel_src
    # n_rows>=500 시 DL 합류
    assert "TCN" in sel_src


def test_requirements_includes_new_libs():
    """handlers-timeseries.txt 에 신규 라이브러리 포함."""
    req = open("requirements/handlers-timeseries.txt", encoding="utf-8").read()
    for lib in (
        "arch",
        "statsforecast",
        "neuralprophet",
        "lightgbm",
        "xgboost",
        "catboost",
        "scikit-learn",
        "darts",
        "torch",
    ):
        assert lib in req, f"requirements 누락: {lib}"
