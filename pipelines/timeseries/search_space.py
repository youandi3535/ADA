"""pipelines.timeseries.search_space — Optuna 탐색 공간 (CS 담당, cs-day6 v3 디벨롭).

방법론 5-2 — HPO 는 시계열 교차검증(walk-forward) **안에서** 튜닝한다.
본 모듈은 HyperparameterTunerAgent 가 importlib 로 동적 로드하여
``get_search_space(model_name, trial) -> dict`` 시그니처로 호출한다.

지원 모델 (9종, pipeline.SUPPORTED_MODELS 와 동기):
  ARIMA / SARIMA / SARIMAX / Prophet / ETS / seasonal_naive
  Informer / TFT / PatchTST

설계 원칙
─────────────────────────────────────────────────────────────────
1. **horizon 은 trial 가 결정하지 않는다** — horizon 은 도메인 변수.
   tuner 가 호출 시 state.category_extras["timeseries"]["horizon"] 을
   params 로 주입하면 train_with_cv 가 그 값으로 gap 산출.
2. **계절성 주기 s 는 categorical** — {7, 12, 30} 중에서 선택 (헌장
   2-4 ACF 가리키는 주기). 365 는 학습 비용이 커서 HPO 에서 제외.
3. **seasonal_naive 는 빈 dict** — 기준선 모델이라 튜닝 불필요
   (방법론 4-2·6-5 "못 이기면 채택 금지" 의 그 기준선).
4. **DL 의 max_steps 는 CPU 보수적** — pipeline.py 가 CPU 환경에서
   max_steps ≤ 8 클립하므로 search 범위도 [4, 32] 로 보수적.
5. **R-1006 정합** — 모든 trial 결과는 walk-forward 안에서 평균±분산
   판정 (tuner 의 n_splits=3 기본).
"""

from __future__ import annotations

from typing import Any


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
    # ─── 고전 통계 모델 ─────────────────────────────────────────────
    if model_name == "ARIMA":
        p = trial.suggest_int("p", 0, 3)
        d = trial.suggest_int("d", 0, 2)
        q = trial.suggest_int("q", 0, 3)
        return {
            "order": (p, d, q),
            "trend": trial.suggest_categorical("trend", ["n", "c", "t", "ct"]),
        }

    if model_name == "SARIMA":
        p = trial.suggest_int("p", 0, 2)
        d = trial.suggest_int("d", 0, 1)
        q = trial.suggest_int("q", 0, 2)
        P = trial.suggest_int("P", 0, 2)
        D = trial.suggest_int("D", 0, 1)
        Q = trial.suggest_int("Q", 0, 2)
        s = trial.suggest_categorical("seasonal_period", [7, 12, 30])
        return {
            "order": (p, d, q),
            "seasonal_order": (P, D, Q, int(s)),
        }

    if model_name == "SARIMAX":
        # SARIMAX 은 SARIMA 와 동일 파라미터 공간. exog 는 외부 주입
        # (pipeline._extract_exog 가 params["exog_columns" or "exog_indices"] 로 읽음).
        p = trial.suggest_int("p", 0, 2)
        d = trial.suggest_int("d", 0, 1)
        q = trial.suggest_int("q", 0, 2)
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
        return {
            "changepoint_prior_scale": trial.suggest_float("changepoint_prior_scale", 1e-3, 0.5, log=True),
            "seasonality_prior_scale": trial.suggest_float("seasonality_prior_scale", 1e-2, 10.0, log=True),
            "seasonality_mode": trial.suggest_categorical("seasonality_mode", ["additive", "multiplicative"]),
        }

    # ─── 지수평활 ETS / Holt-Winters (헌장 6-1 기준선) ─────────────────
    if model_name == "ETS":
        # ExponentialSmoothing — statsmodels.tsa.holtwinters
        trend = trial.suggest_categorical("trend", [None, "add", "mul"])
        seasonal = trial.suggest_categorical("seasonal", [None, "add", "mul"])
        # seasonal=mul 일 때 양수 데이터 필요 — pipeline 에서 검증
        seasonal_periods = trial.suggest_categorical("seasonal_periods", [7, 12, 30])
        damped = trial.suggest_categorical("damped_trend", [False, True])
        return {
            "trend": trend,
            "seasonal": seasonal,
            "seasonal_periods": int(seasonal_periods),
            "damped_trend": bool(damped),
        }

    # ─── seasonal_naive 기준선 (헌장 4-2·6-5) ─────────────────────────
    # 기준선은 튜닝하지 않는다. 항상 빈 dict — pipeline 이 default period 사용.
    if model_name == "seasonal_naive":
        return {}

    # ─── DL (Informer / TFT / PatchTST) — CPU 보수적 ─────────────────
    if model_name in ("Informer", "TFT", "PatchTST"):
        return {
            "input_size": trial.suggest_categorical("input_size", [12, 24, 48]),
            "max_steps": trial.suggest_int("max_steps", 4, 32),
            "hidden_size": trial.suggest_categorical("hidden_size", [32, 64, 128]),
        }

    raise ValueError(f"Unknown timeseries model for search_space: {model_name}")
