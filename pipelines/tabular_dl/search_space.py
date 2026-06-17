"""tabular_dl.search_space — Optuna 탐색 공간 (P1-1, 2026-06-16).

기존엔 이 파일이 없어 HyperparameterTunerAgent 가 ``hpo_skip_no_search_space`` 로
tabular_dl 튜닝을 통째 건너뛰었다. 본 파일로 튜닝을 활성화한다.

설계(에이전트 자동 판단):
  - 실제로 ``pipeline._train_transformer`` 가 소비하는 파라미터만 노출한다:
    ``lr`` · ``epochs`` · ``batch_size``. (model_cfg 의 layers/heads/dropout 은 현재
    기본값 고정이라 탐색 대상이 아니다 — 노출해도 무시되어 trial 만 낭비.)
  - 서버 성능 제약(무거운 학습 불가) → epochs/batch_size 범위를 작게 유지(경량).
  - TabPFN 은 사전학습 모델이라 HPO 의미 없음 → 빈 dict(튜너가 기본값으로 학습).
  - 미지원/fallback 모델명 → 빈 dict(raise 하지 않음). 튜너는 빈 dict 를 기본
    파라미터 시그널로 처리하므로 어떤 model_name 이 와도 안전하다.

인터페이스: HyperparameterTunerAgent 가 ``get_search_space(model_name, trial)`` 호출
(일반 Optuna trial 및 FixedTrial 양쪽에서 동작).
"""

from __future__ import annotations

from typing import Any

# 사전학습/탐색 무의미 모델 — 빈 dict 시그널
_NO_HPO_MODELS = ("TabPFN",)
_TRANSFORMER_MODELS = ("TabTransformer", "FTTransformer")


def get_search_space(model_name: str, trial: Any) -> dict[str, Any]:
    if model_name in _NO_HPO_MODELS:
        return {}
    if model_name in _TRANSFORMER_MODELS:
        return {
            "lr": trial.suggest_float("lr", 1e-4, 1e-2, log=True),
            "epochs": trial.suggest_int("epochs", 10, 40),
            "batch_size": trial.suggest_categorical("batch_size", [128, 256, 512]),
        }
    return {}  # 미지원/fallback(RandomForest 등) → 기본 파라미터로 학습
