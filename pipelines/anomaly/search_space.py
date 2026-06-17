"""anomaly.search_space — Optuna 탐색 공간 (P1-1, 2026-06-16, NY 영역).

기존엔 이 파일이 없어 HyperparameterTunerAgent 가 ``hpo_skip_no_search_space`` 로
anomaly 튜닝을 통째 건너뛰었다. 본 파일로 튜닝을 활성화한다.

설계(에이전트 자동 판단 — "정답에 가까운 선택"):
  - objective 는 roc_auc(점수 순위 기반)라 **contamination 은 AUC 에 영향이 없다**
    (임계만 바꿈). 따라서 탐색은 점수 자체를 바꾸는 **모델 구조 파라미터**만 한다.
  - 서버 성능 제약 — 무거운 모델(AutoEncoder/TranAD/AnomalyTransformer)은 탐색하지
    않고 기본값(torch 학습 비용 회피). 비모수 모델(COPOD/ECOD)은 튜닝할 구조가 없어
    빈 dict.
  - 레이블이 없는 순수 비지도면 objective(AUC) 가 정의되지 않아 튜너가 0 을 받고
    기본 파라미터로 귀결된다(무해). 레이블이 있는 준지도에서 실효를 낸다.

인터페이스: ``get_search_space(model_name, trial)`` — 일반 trial·FixedTrial 양쪽 동작.
미지원/무거운/비모수 모델명 → 빈 dict(raise 안 함) → 어떤 model_name 이 와도 안전.
"""

from __future__ import annotations

from typing import Any


def get_search_space(model_name: str, trial: Any) -> dict[str, Any]:
    if model_name == "IsolationForest":
        return {
            "n_estimators": trial.suggest_int("n_estimators", 50, 300),
            "max_samples": trial.suggest_float("max_samples", 0.5, 1.0),
            "max_features": trial.suggest_float("max_features", 0.5, 1.0),
            "random_state": 42,
        }
    if model_name == "LOF":
        return {
            "n_neighbors": trial.suggest_int("n_neighbors", 5, 50),
            "leaf_size": trial.suggest_int("leaf_size", 10, 50),
        }
    if model_name == "OneClassSVM":
        return {
            "nu": trial.suggest_float("nu", 0.01, 0.5),
            "gamma": trial.suggest_categorical("gamma", ["scale", "auto"]),
        }
    if model_name == "HBOS":
        return {
            "n_bins": trial.suggest_int("n_bins", 5, 50),
            "alpha": trial.suggest_float("alpha", 0.1, 0.5),
        }
    # COPOD/ECOD(비모수)·AutoEncoder/TranAD/AnomalyTransformer(무거움) → 기본값
    return {}
