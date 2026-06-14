"""pipelines.timeseries.search_space — Optuna 탐색 공간 (CS 담당, cs-day6 v3 + 과적합 방어 보강).

방법론 5-2 — HPO 는 시계열 교차검증(walk-forward) **안에서** 튜닝한다.
본 모듈은 HyperparameterTunerAgent 가 importlib 로 동적 로드하여
``get_search_space(model_name, trial) -> dict`` 시그니처로 호출한다.

지원 모델 (6종, pipeline.SUPPORTED_MODELS 와 동기):
  ARIMA / SARIMA / SARIMAX / Prophet / ETS / seasonal_naive

설계 원칙
─────────────────────────────────────────────────────────────────
1. **horizon 은 trial 가 결정하지 않는다** — horizon 은 도메인 변수.
   tuner 가 호출 시 state.category_extras["timeseries"]["horizon"] 을
   params 로 주입하면 train_with_cv 가 그 값으로 gap 산출.
2. **계절성 주기 s 는 categorical** — {7, 12, 30} 중에서 선택 (헌장
   2-4 ACF 가리키는 주기). 365 는 학습 비용이 커서 HPO 에서 제외.
3. **seasonal_naive 는 빈 dict** — 기준선 모델이라 튜닝 불필요
   (방법론 4-2·6-5 "못 이기면 채택 금지" 의 그 기준선).
4. **R-1006 정합** — 모든 trial 결과는 walk-forward 안에서 평균±분산
   판정 (tuner 의 n_splits=3 기본).

과적합 방어 (2026-06-05, OF1·OF2·OF3 디벨롭)
─────────────────────────────────────────────────────────────────
OF1: ARIMA/SARIMA order 데이터 길이 적응 — trial.study.user_attrs["n_rows"]
     주입 시 짧은 시계열엔 자동으로 (p+q+P+Q) 합계 상한 부과. 미주입 시 기본.
OF3: Prophet changepoint_prior_scale 상한 0.5 → 0.1 보수화 (노이즈 과적합 방지).
"""

from __future__ import annotations

from typing import Any


def _n_rows_hint(trial: Any) -> int:
    """trial.study.user_attrs["n_rows"] 에서 데이터 길이 힌트 추출.

    tuner 가 study.set_user_attr("n_rows", n) 으로 주입했을 때만 활용.
    미주입 시 0 반환 — 호출측은 기본 범위 사용.
    """
    try:
        attrs = getattr(getattr(trial, "study", None), "user_attrs", None) or {}
        return int(attrs.get("n_rows", 0) or 0)
    except Exception:
        return 0


def get_search_space(model_name: str, trial: Any) -> dict[str, Any]:
    """모델별 Optuna trial 파라미터 dict 반환.

    Parameters
    ----------
    model_name : str
        pipeline.SUPPORTED_MODELS 중 하나.
    trial : optuna.Trial
        HyperparameterTunerAgent 가 전달.

    Returns
    -------
    dict[str, Any]
        TimeSeriesPipeline.train 의 ``params`` 인자로 그대로 전달.
    """
    n_rows = _n_rows_hint(trial)

    # ─── 고전 통계 모델 ─────────────────────────────────────────────
    if model_name == "ARIMA":
        # OF1 — n_rows 적응 order 상한 (과적합 방어)
        if 0 < n_rows < 100:
            p_max, d_max, q_max = 1, 1, 1
        elif n_rows < 300:
            p_max, d_max, q_max = 2, 1, 2
        else:
            p_max, d_max, q_max = 3, 2, 3
        p = trial.suggest_int("p", 0, p_max)
        d = trial.suggest_int("d", 0, d_max)
        q = trial.suggest_int("q", 0, q_max)
        return {
            "order": (p, d, q),
            "trend": trial.suggest_categorical("trend", ["n", "c", "t", "ct"]),
        }

    if model_name == "SARIMA":
        # OF1 — n_rows 적응
        if 0 < n_rows < 200:
            p_max, q_max, P_max, Q_max = 1, 1, 1, 1
        else:
            p_max, q_max, P_max, Q_max = 2, 2, 2, 2
        p = trial.suggest_int("p", 0, p_max)
        d = trial.suggest_int("d", 0, 1)
        q = trial.suggest_int("q", 0, q_max)
        P = trial.suggest_int("P", 0, P_max)
        D = trial.suggest_int("D", 0, 1)
        Q = trial.suggest_int("Q", 0, Q_max)
        s = trial.suggest_categorical("seasonal_period", [7, 12, 30])
        return {
            "order": (p, d, q),
            "seasonal_order": (P, D, Q, int(s)),
        }

    if model_name == "SARIMAX":
        # SARIMAX 은 SARIMA 와 동일 파라미터 공간. exog 는 외부 주입
        # (pipeline._extract_exog 가 params["exog_columns" or "exog_indices"] 로 읽음).
        # OF1 — n_rows 적응
        if 0 < n_rows < 200:
            p_max, q_max = 1, 1
        else:
            p_max, q_max = 2, 2
        p = trial.suggest_int("p", 0, p_max)
        d = trial.suggest_int("d", 0, 1)
        q = trial.suggest_int("q", 0, q_max)
        P = trial.suggest_int("P", 0, 1)
        D = trial.suggest_int("D", 0, 1)
        Q = trial.suggest_int("Q", 0, 1)
        s = trial.suggest_categorical("seasonal_period", [7, 12, 30])
        return {
            "order": (p, d, q),
            "seasonal_order": (P, D, Q, int(s)),
        }

    # ─── Prophet ────────────────────────────────────────────────────
    if model_name == "Prophet":
        # OF3 — changepoint_prior_scale 상한 0.5 → 0.1 (노이즈 과적합 방지)
        return {
            "changepoint_prior_scale": trial.suggest_float("changepoint_prior_scale", 1e-3, 0.1, log=True),
            "seasonality_prior_scale": trial.suggest_float("seasonality_prior_scale", 1e-2, 10.0, log=True),
            "seasonality_mode": trial.suggest_categorical("seasonality_mode", ["additive", "multiplicative"]),
        }

    # ─── 지수평활 ETS / Holt-Winters (헌장 6-1 기준선) ─────────────────
    if model_name == "ETS":
        trend = trial.suggest_categorical("trend", [None, "add", "mul"])
        seasonal = trial.suggest_categorical("seasonal", [None, "add", "mul"])
        seasonal_periods = trial.suggest_categorical("seasonal_periods", [7, 12, 30])
        damped = trial.suggest_categorical("damped_trend", [False, True])
        return {
            "trend": trend,
            "seasonal": seasonal,
            "seasonal_periods": int(seasonal_periods),
            "damped_trend": bool(damped),
        }

    # ─── seasonal_naive 기준선 (헌장 4-2·6-5) ─────────────────────────
    if model_name == "seasonal_naive":
        return {}

    # ════════════════════════════════════════════════════════════════════
    # Phase F (2026-06-14, B 길) — 신규 16 종 파라미터
    # ═══════════════════════════════════════════════════════════════
    if model_name == "STL":
        return {
            "seasonal_periods": trial.suggest_categorical("seasonal_periods", [7, 12, 30]),
            "arima_order": (
                trial.suggest_int("stl_arima_p", 0, 2),
                trial.suggest_int("stl_arima_d", 0, 1),
                trial.suggest_int("stl_arima_q", 0, 2),
            ),
        }
    if model_name == "VAR":
        var_max = min(10, max(2, n_rows // 50)) if n_rows > 0 else 5
        return {
            "maxlags": trial.suggest_int("var_maxlags", 1, var_max),
            "ic": trial.suggest_categorical("var_ic", ["aic", "bic", "hqic"]),
        }
    if model_name == "VARMA":
        return {"order": (trial.suggest_int("varma_p", 0, 2), trial.suggest_int("varma_q", 0, 2))}
    if model_name == "GARCH":
        return {
            "p": trial.suggest_int("garch_p", 1, 2),
            "q": trial.suggest_int("garch_q", 1, 2),
            "egarch": trial.suggest_categorical("egarch", [False, True]),
        }
    if model_name == "AutoARIMA":
        return {"season_length": trial.suggest_categorical("season_length", [7, 12, 30])}
    if model_name == "AutoETS":
        return {"season_length": trial.suggest_categorical("season_length", [7, 12, 30])}
    if model_name == "NeuralProphet":
        return {
            "epochs": trial.suggest_int("np_epochs", 5, 20),
            "n_lags": trial.suggest_int("np_n_lags", 0, 7),
        }
    if model_name == "LightGBM":
        n_est_max = 100 if 0 < n_rows < 200 else 400
        leaves_max = 15 if 0 < n_rows < 200 else 63
        return {
            "n_estimators": trial.suggest_int("lgb_n_estimators", 50, n_est_max),
            "learning_rate": trial.suggest_float("lgb_lr", 1e-3, 0.3, log=True),
            "num_leaves": trial.suggest_int("lgb_leaves", 7, leaves_max),
            "max_depth": trial.suggest_int("lgb_max_depth", -1, 10),
        }
    if model_name == "XGBoost":
        n_est_max = 100 if 0 < n_rows < 200 else 400
        depth_max = 4 if 0 < n_rows < 200 else 10
        return {
            "n_estimators": trial.suggest_int("xgb_n_estimators", 50, n_est_max),
            "learning_rate": trial.suggest_float("xgb_lr", 1e-3, 0.3, log=True),
            "max_depth": trial.suggest_int("xgb_max_depth", 3, depth_max),
        }
    if model_name == "CatBoost":
        n_iter_max = 100 if 0 < n_rows < 200 else 400
        depth_max = 4 if 0 < n_rows < 200 else 8
        return {
            "iterations": trial.suggest_int("cb_iterations", 50, n_iter_max),
            "learning_rate": trial.suggest_float("cb_lr", 1e-3, 0.3, log=True),
            "depth": trial.suggest_int("cb_depth", 3, depth_max),
        }
    if model_name == "RandomForest":
        return {
            "n_estimators": trial.suggest_int("rf_n_estimators", 100, 500),
            "max_depth": trial.suggest_categorical("rf_max_depth", [None, 5, 10, 20]),
        }
    if model_name == "Ridge":
        return {"alpha": trial.suggest_float("ridge_alpha", 1e-3, 100.0, log=True)}
    if model_name == "Lasso":
        return {
            "alpha": trial.suggest_float("lasso_alpha", 1e-4, 10.0, log=True),
            "max_iter": trial.suggest_int("lasso_max_iter", 1000, 10000),
        }
    if model_name in ("TCN", "NHiTS", "NBEATS"):
        return {
            "input_chunk_length": trial.suggest_int("dl_input_chunk", 7, 28),
            "output_chunk_length": trial.suggest_int("dl_output_chunk", 1, 14),
            "n_epochs": trial.suggest_int("dl_n_epochs", 10, 50),
            "batch_size": trial.suggest_categorical("dl_batch", [16, 32, 64]),
            "dropout": trial.suggest_float("dl_dropout", 0.0, 0.3),
        }
    if model_name in ("LSTM", "GRU", "RNN", "DeepAR"):
        return {
            "input_chunk_length": trial.suggest_int("rnn_input_chunk", 7, 28),
            "hidden_dim": trial.suggest_categorical("rnn_hidden", [8, 16, 32]),
            "n_rnn_layers": trial.suggest_int("rnn_layers", 1, 2),
            "training_length": trial.suggest_int("rnn_training_len", 14, 40),
            "n_epochs": trial.suggest_int("rnn_n_epochs", 10, 50),
            "batch_size": trial.suggest_categorical("rnn_batch", [16, 32, 64]),
        }

    raise ValueError(f"Unknown timeseries model for search_space: {model_name}")
