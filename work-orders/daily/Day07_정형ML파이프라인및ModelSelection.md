# Day 7 — 정형 ML 파이프라인 + Model Selection Agent
> 프로젝트: Adaptive AutoAI Pipeline Agent | 2주 스프린트 Day 7/14

---

## 📋 오늘의 목표

4개 ML 프레임워크(RandomForest, XGBoost, LightGBM, CatBoost)를 지원하는 `TabularMLPipeline`을 구현하고, Optuna 탐색 공간을 정의하며, Claude Sonnet 4.6을 사용하여 데이터 특성과 과거 성공 패턴을 기반으로 상위 3개 모델을 선정하는 `ModelSelectionAgent`를 완성한다. Titanic 데이터 기준으로 `val_f1 >= 0.70` 달성이 핵심 완료 기준이다.

---

## 👤 담당자

- **B** 주도 (전체 작업)
- 코드 리뷰: A (ModelSelectionAgent LLM 프롬프트), C (MLflow 연동)
- 단위 테스트: B + D

---

## ✅ 작업 목록

### 1. pipelines/tabular_ml/pipeline.py 구현

- [ ] `TabularMLPipeline(BasePipeline)` 클래스 작성
- [ ] `SUPPORTED_MODELS` 딕셔너리 정의:
  ```python
  SUPPORTED_MODELS = {
      "RandomForest": {
          "classification": RandomForestClassifier,
          "regression": RandomForestRegressor,
      },
      "XGBoost": {
          "classification": XGBClassifier,
          "regression": XGBRegressor,
      },
      "LightGBM": {
          "classification": LGBMClassifier,
          "regression": LGBMRegressor,
      },
      "CatBoost": {
          "classification": CatBoostClassifier,
          "regression": CatBoostRegressor,
      },
  }
  ```

- [ ] `train(self, X_train, y_train, model_name: str, params: dict) -> Any` 구현:
  1. `task = "classification" if len(set(y_train)) <= 20 else "regression"` 자동 판단
  2. `SUPPORTED_MODELS[model_name][task](**params)` 모델 인스턴스 생성
  3. `model.fit(X_train, y_train)` 학습
  4. MLflow `run` 시작 후 params 로깅: `mlflow.log_params(params)`
  5. MLflow `run_id` 저장: `self.mlflow_run_id = run.info.run_id`
  6. 학습된 모델 객체 반환

- [ ] `evaluate(self, model, X_val, y_val, task: str) -> dict` 구현:
  ```python
  # classification 메트릭
  if task == "classification":
      return {
          "val_accuracy": accuracy_score(y_val, y_pred),
          "val_f1": f1_score(y_val, y_pred, average="weighted"),
          "val_precision": precision_score(y_val, y_pred, average="weighted"),
          "val_recall": recall_score(y_val, y_pred, average="weighted"),
          "val_roc_auc": roc_auc_score(y_val, y_pred_proba, multi_class="ovr")
                          if hasattr(model, "predict_proba") else None,
      }
  # regression 메트릭
  else:
      return {
          "val_rmse": float(np.sqrt(mean_squared_error(y_val, y_pred))),
          "val_r2": float(r2_score(y_val, y_pred)),
          "val_mae": float(mean_absolute_error(y_val, y_pred)),
          "val_mape": float(mean_absolute_percentage_error(y_val, y_pred)),
      }
  ```
  - 모든 메트릭을 `mlflow.log_metrics(metrics)` 로 MLflow에 기록
  - CatBoost 모델은 `verbose=False` 설정 필수 (로그 억제)

- [ ] `predict(self, model, X) -> np.ndarray` 구현:
  - `model.predict(X)` 반환

- [ ] `save_model(self, model, job_id: str, model_name: str) -> str` 구현:
  - `minio.save_model(model, f"models/{job_id}/{model_name}.joblib")` 저장
  - MLflow에 모델 아티팩트 로깅: `mlflow.sklearn.log_model(model, model_name)`
  - MinIO 경로 반환

- [ ] `train_with_cv(self, X, y, model_name, params, n_splits=5, task="classification") -> dict` 구현:
  - StratifiedKFold(분류) 또는 KFold(회귀) 교차검증
  - 폴드별 메트릭 수집 후 평균 반환
  - `{"mean_f1": ..., "std_f1": ..., "fold_scores": [...]}` 형식

### 2. pipelines/tabular_ml/search_space.py 구현

- [ ] `get_search_space(model_name: str, trial: optuna.Trial) -> dict` 함수 작성
- [ ] **RandomForest** 탐색 공간:
  ```python
  "RandomForest": {
      "n_estimators": trial.suggest_int("n_estimators", 100, 500),
      "max_depth": trial.suggest_int("max_depth", 3, 15),
      "min_samples_split": trial.suggest_int("min_samples_split", 2, 10),
      "min_samples_leaf": trial.suggest_int("min_samples_leaf", 1, 5),
      "max_features": trial.suggest_categorical("max_features", ["sqrt", "log2", None]),
      "class_weight": trial.suggest_categorical("class_weight", ["balanced", None]),
  }
  ```

- [ ] **XGBoost** 탐색 공간:
  ```python
  "XGBoost": {
      "learning_rate": trial.suggest_float("learning_rate", 1e-3, 0.3, log=True),
      "n_estimators": trial.suggest_int("n_estimators", 100, 500),
      "max_depth": trial.suggest_int("max_depth", 3, 10),
      "subsample": trial.suggest_float("subsample", 0.6, 1.0),
      "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
      "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
      "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
      "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
      "eval_metric": "logloss",    # 분류
      "use_label_encoder": False,
  }
  ```

- [ ] **LightGBM** 탐색 공간:
  ```python
  "LightGBM": {
      "learning_rate": trial.suggest_float("learning_rate", 1e-3, 0.3, log=True),
      "n_estimators": trial.suggest_int("n_estimators", 100, 1000),
      "num_leaves": trial.suggest_int("num_leaves", 20, 300),
      "min_child_samples": trial.suggest_int("min_child_samples", 5, 100),
      "feature_fraction": trial.suggest_float("feature_fraction", 0.5, 1.0),
      "bagging_fraction": trial.suggest_float("bagging_fraction", 0.5, 1.0),
      "bagging_freq": trial.suggest_int("bagging_freq", 1, 7),
      "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
      "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
      "verbose": -1,
  }
  ```

- [ ] **CatBoost** 탐색 공간:
  ```python
  "CatBoost": {
      "learning_rate": trial.suggest_float("learning_rate", 1e-3, 0.3, log=True),
      "iterations": trial.suggest_int("iterations", 100, 500),
      "depth": trial.suggest_int("depth", 3, 10),
      "l2_leaf_reg": trial.suggest_float("l2_leaf_reg", 1e-8, 10.0, log=True),
      "border_count": trial.suggest_int("border_count", 32, 255),
      "verbose": 0,
  }
  ```

- [ ] 미지원 모델명 시 `ValueError` 발생
- [ ] `MODEL_NAMES = list(get_search_space.__code__.co_consts)` 지원 모델 목록 상수

### 3. agents/model_selection.py 구현

- [ ] `ModelSelectionAgent(BaseAgent)` 클래스 작성
- [ ] `model_name = "claude-sonnet-4-6"` 설정
- [ ] `__call__(self, state: PipelineState) -> PipelineState` 구현:
  1. `state.data_profile` 에서 데이터 특성 추출 (rows, cols, dtype 분포, 결측률)
  2. `success_patterns` 테이블에서 동일 category의 과거 성공 config 조회
  3. LLM 호출하여 상위 3개 모델 추천
  4. 추천 결과를 `state.model_candidates` 에 저장
  5. `next_agent="hyperparameter_tuner"` 설정

- [ ] LLM 시스템 프롬프트:
  ```
  당신은 AutoML 모델 선택 전문가입니다.
  데이터 프로파일과 과거 성공 패턴을 분석하여
  최적의 ML 모델 3개를 추천하세요.
  
  선택 가능한 모델: RandomForest, XGBoost, LightGBM, CatBoost
  
  고려 요소:
  - 데이터 크기 (rows): 소규모(<1K) → RandomForest, 대규모(>10K) → XGBoost/LightGBM
  - 피처 수 (cols): 고차원(>100) → LightGBM/XGBoost (feature selection 강점)
  - 결측값 비율: 높음(>20%) → XGBoost/LightGBM (내장 처리)
  - 범주형 피처 많음 → CatBoost
  - 불균형 데이터 → class_weight 지원하는 모델 우선
  
  응답 형식 (JSON만):
  {
    "candidates": [
      {"model_name": "XGBoost", "reason": "...", "estimated_f1": 0.82},
      {"model_name": "LightGBM", "reason": "...", "estimated_f1": 0.80},
      {"model_name": "RandomForest", "reason": "...", "estimated_f1": 0.76}
    ]
  }
  ```

- [ ] `_build_user_prompt(self, state, success_patterns) -> str` 헬퍼:
  ```python
  def _build_user_prompt(self, state, patterns):
      profile = state.data_profile
      return f"""
      === 데이터 프로파일 ===
      행 수: {profile['rows']}
      열 수: {profile['cols']}
      task: {state.task}
      target_column: {state.target_column}
      결측값 있는 컬럼: {sum(1 for v in profile['missing'].values() if v > 0)}
      수치형 컬럼: {sum(1 for v in profile['dtypes'].values() if 'float' in v or 'int' in v)}
      범주형 컬럼: {sum(1 for v in profile['dtypes'].values() if v == 'object')}
      
      === 과거 성공 패턴 (동일 카테고리) ===
      {patterns or "없음"}
      """
  ```

- [ ] `_query_success_patterns(self, category: str) -> str` 헬퍼:
  - `success_patterns` 테이블에서 `category` 기준 상위 3개 패턴 조회
  - JSON 형식으로 직렬화하여 반환

### 4. 단위 테스트 및 통합 테스트 작성

- [ ] `tests/pipelines/test_tabular_ml.py` 작성:
  - Titanic CSV 로딩 (pytest fixture)
  - 전처리: 범주형 인코딩, 결측값 처리
  - `TabularMLPipeline().train()` 4개 모델 각각 테스트
  - `TabularMLPipeline().evaluate()` 에서 `val_f1 >= 0.70` 확인
  - MLflow run 기록 확인 (mlflow.get_run)

- [ ] `tests/pipelines/test_search_space.py` 작성:
  - `get_search_space("RandomForest", trial)` 에서 키 목록 검증
  - `get_search_space("XGBoost", trial)` 에서 `learning_rate` 범위 검증
  - 미지원 모델명 시 `ValueError` 발생 확인

- [ ] `tests/agents/test_model_selection.py` 작성:
  - LLM 응답 mock
  - `state.model_candidates` 에 3개 항목 포함 확인
  - 각 후보에 `model_name`, `reason` 키 포함 확인
  - 성공 패턴 DB 쿼리 mock

---

## 🏗️ 구현 명세

### pipelines/tabular_ml/pipeline.py 전체 구조

```python
# pipelines/tabular_ml/pipeline.py
import numpy as np
import mlflow
import mlflow.sklearn
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import (
    accuracy_score, f1_score, precision_score, recall_score,
    mean_squared_error, r2_score, mean_absolute_error,
    mean_absolute_percentage_error,
)
from xgboost import XGBClassifier, XGBRegressor
from lightgbm import LGBMClassifier, LGBMRegressor
from catboost import CatBoostClassifier, CatBoostRegressor
from pipelines.base import BasePipeline
from tools.minio_tool import MinIOClient
from shared.config import settings
from shared.logger import get_logger

logger = get_logger("TabularMLPipeline")


class TabularMLPipeline(BasePipeline):

    SUPPORTED_MODELS = {
        "RandomForest": {"classification": RandomForestClassifier,
                         "regression": RandomForestRegressor},
        "XGBoost":      {"classification": XGBClassifier,
                         "regression": XGBRegressor},
        "LightGBM":     {"classification": LGBMClassifier,
                         "regression": LGBMRegressor},
        "CatBoost":     {"classification": CatBoostClassifier,
                         "regression": CatBoostRegressor},
    }

    def train(self, X_train, y_train, model_name: str, params: dict):
        if model_name not in self.SUPPORTED_MODELS:
            raise ValueError(f"미지원 모델: {model_name}")

        # task 자동 판단
        unique_vals = len(set(y_train))
        task = "classification" if unique_vals <= 20 else "regression"

        # 모델 생성 및 학습
        ModelClass = self.SUPPORTED_MODELS[model_name][task]

        # CatBoost verbose 억제
        if model_name == "CatBoost":
            params.setdefault("verbose", 0)

        model = ModelClass(**params)
        model.fit(X_train, y_train)

        # MLflow 기록
        with mlflow.start_run(nested=True) as run:
            mlflow.log_params(params)
            mlflow.log_param("model_name", model_name)
            mlflow.log_param("task", task)
            self.mlflow_run_id = run.info.run_id
            mlflow.sklearn.log_model(model, artifact_path=model_name)

        return model

    def evaluate(self, model, X_val, y_val, task: str) -> dict:
        y_pred = model.predict(X_val)

        if task == "classification":
            metrics = {
                "val_accuracy":  float(accuracy_score(y_val, y_pred)),
                "val_f1":        float(f1_score(y_val, y_pred, average="weighted",
                                                zero_division=0)),
                "val_precision": float(precision_score(y_val, y_pred, average="weighted",
                                                       zero_division=0)),
                "val_recall":    float(recall_score(y_val, y_pred, average="weighted",
                                                    zero_division=0)),
            }
        else:
            metrics = {
                "val_rmse": float(np.sqrt(mean_squared_error(y_val, y_pred))),
                "val_r2":   float(r2_score(y_val, y_pred)),
                "val_mae":  float(mean_absolute_error(y_val, y_pred)),
            }

        if self.mlflow_run_id:
            with mlflow.start_run(run_id=self.mlflow_run_id):
                mlflow.log_metrics(metrics)

        return metrics

    def predict(self, model, X) -> np.ndarray:
        return model.predict(X)

    def save_model(self, model, job_id: str, model_name: str) -> str:
        minio = MinIOClient()
        object_name = f"models/{job_id}/{model_name}.joblib"
        return minio.save_model(model, object_name)

    def train_with_cv(self, X, y, model_name: str, params: dict,
                      n_splits: int = 5, task: str = "classification") -> dict:
        from sklearn.model_selection import StratifiedKFold, KFold, cross_val_score

        if task == "classification":
            cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
            scoring = "f1_weighted"
        else:
            cv = KFold(n_splits=n_splits, shuffle=True, random_state=42)
            scoring = "r2"

        ModelClass = self.SUPPORTED_MODELS[model_name][task]
        model = ModelClass(**params)
        scores = cross_val_score(model, X, y, cv=cv, scoring=scoring, n_jobs=-1)

        return {
            "mean_score": float(scores.mean()),
            "std_score":  float(scores.std()),
            "fold_scores": scores.tolist(),
            "scoring": scoring,
        }
```

### pipelines/tabular_ml/search_space.py 전체 구조

```python
# pipelines/tabular_ml/search_space.py
import optuna

SUPPORTED_MODEL_NAMES = ["RandomForest", "XGBoost", "LightGBM", "CatBoost"]


def get_search_space(model_name: str, trial: optuna.Trial) -> dict:
    """Optuna Trial 기반 하이퍼파라미터 탐색 공간 반환"""

    if model_name == "RandomForest":
        return {
            "n_estimators":      trial.suggest_int("n_estimators", 100, 500),
            "max_depth":         trial.suggest_int("max_depth", 3, 15),
            "min_samples_split": trial.suggest_int("min_samples_split", 2, 10),
            "min_samples_leaf":  trial.suggest_int("min_samples_leaf", 1, 5),
            "max_features":      trial.suggest_categorical("max_features",
                                                           ["sqrt", "log2"]),
            "n_jobs":            -1,
            "random_state":      42,
        }

    elif model_name == "XGBoost":
        return {
            "learning_rate":    trial.suggest_float("learning_rate", 1e-3, 0.3, log=True),
            "n_estimators":     trial.suggest_int("n_estimators", 100, 500),
            "max_depth":        trial.suggest_int("max_depth", 3, 10),
            "subsample":        trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
            "reg_alpha":        trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
            "reg_lambda":       trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
            "n_jobs":           -1,
            "random_state":     42,
            "verbosity":        0,
        }

    elif model_name == "LightGBM":
        return {
            "learning_rate":    trial.suggest_float("learning_rate", 1e-3, 0.3, log=True),
            "n_estimators":     trial.suggest_int("n_estimators", 100, 1000),
            "num_leaves":       trial.suggest_int("num_leaves", 20, 300),
            "min_child_samples":trial.suggest_int("min_child_samples", 5, 100),
            "feature_fraction": trial.suggest_float("feature_fraction", 0.5, 1.0),
            "bagging_fraction": trial.suggest_float("bagging_fraction", 0.5, 1.0),
            "bagging_freq":     trial.suggest_int("bagging_freq", 1, 7),
            "reg_alpha":        trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
            "reg_lambda":       trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
            "n_jobs":           -1,
            "random_state":     42,
            "verbose":          -1,
        }

    elif model_name == "CatBoost":
        return {
            "learning_rate": trial.suggest_float("learning_rate", 1e-3, 0.3, log=True),
            "iterations":    trial.suggest_int("iterations", 100, 500),
            "depth":         trial.suggest_int("depth", 3, 10),
            "l2_leaf_reg":   trial.suggest_float("l2_leaf_reg", 1e-8, 10.0, log=True),
            "border_count":  trial.suggest_int("border_count", 32, 255),
            "random_seed":   42,
            "verbose":       0,
        }

    else:
        raise ValueError(f"미지원 모델: {model_name}. "
                         f"지원 목록: {SUPPORTED_MODEL_NAMES}")
```

### agents/model_selection.py 전체 구조

```python
# agents/model_selection.py
from agents.base import BaseAgent
from shared.state import PipelineState
from shared.logger import get_logger

logger = get_logger("ModelSelectionAgent")

SYSTEM_PROMPT = """
당신은 AutoML 모델 선택 전문가입니다.
데이터 프로파일과 과거 성공 패턴을 분석하여
최적의 ML 모델 3개를 추천하세요.

선택 가능한 모델: RandomForest, XGBoost, LightGBM, CatBoost

고려 요소:
- 데이터 크기 (rows): 소규모(<1K) → RandomForest, 대규모(>10K) → XGBoost/LightGBM
- 피처 수 (cols): 고차원(>100) → LightGBM (feature selection 내장)
- 결측값 비율: 높음(>20%) → XGBoost/LightGBM (내장 결측 처리)
- 범주형 피처 다수 → CatBoost (원핫 인코딩 불필요)
- 불균형 데이터 → class_weight 지원 모델 우선

반드시 JSON만 응답:
{
  "candidates": [
    {"model_name": "XGBoost", "reason": "...", "estimated_f1": 0.82},
    {"model_name": "LightGBM", "reason": "...", "estimated_f1": 0.80},
    {"model_name": "RandomForest", "reason": "...", "estimated_f1": 0.76}
  ]
}
"""


class ModelSelectionAgent(BaseAgent):
    model_name = "claude-sonnet-4-6"

    def __call__(self, state: PipelineState) -> PipelineState:
        success_patterns = self._query_success_patterns(state.category)
        user_prompt = self._build_user_prompt(state, success_patterns)

        response_text = self._call_llm(SYSTEM_PROMPT, user_prompt, max_tokens=2048)
        parsed = self._parse_json(response_text)

        candidates = [c["model_name"] for c in parsed.get("candidates", [])]

        return state.model_copy(update={
            "model_candidates": candidates[:3],
            "next_agent": "hyperparameter_tuner",
        })

    def _build_user_prompt(self, state: PipelineState, patterns: str) -> str:
        profile = state.data_profile or {}
        missing_cols = sum(1 for v in profile.get("missing", {}).values() if v > 0.05)
        cat_cols = sum(1 for v in profile.get("dtypes", {}).values() if v == "object")
        num_cols = sum(1 for v in profile.get("dtypes", {}).values()
                       if any(t in v for t in ("float", "int")))

        return f"""
=== 데이터 프로파일 ===
행 수: {profile.get('rows', 'unknown')}
열 수: {profile.get('cols', 'unknown')}
수치형 컬럼: {num_cols}개
범주형 컬럼: {cat_cols}개
결측값 있는 컬럼(>5%): {missing_cols}개
task 유형: {state.task}
target_column: {state.target_column or '없음'}
메모리 사용량: {profile.get('memory_mb', 0):.1f} MB

=== 과거 성공 패턴 (동일 카테고리: {state.category}) ===
{patterns or '기록 없음 (최초 실행)'}

위 정보를 바탕으로 최적 모델 3개를 추천해주세요.
"""

    def _query_success_patterns(self, category: str) -> str:
        """success_patterns 테이블에서 동일 카테고리 상위 3개 조회"""
        try:
            from shared.db import AsyncSessionLocal
            from shared.models import SuccessPattern
            from sqlalchemy import select
            import asyncio, json

            async def _query():
                async with AsyncSessionLocal() as session:
                    result = await session.execute(
                        select(SuccessPattern)
                        .where(SuccessPattern.category == category)
                        .order_by(SuccessPattern.success_count.desc())
                        .limit(3)
                    )
                    patterns = result.scalars().all()
                    return [
                        {"description": p.description, "config": p.config,
                         "success_count": p.success_count}
                        for p in patterns
                    ]

            patterns = asyncio.get_event_loop().run_until_complete(_query())
            return json.dumps(patterns, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("success_patterns 조회 실패", error=str(e))
            return ""
```

### tests/pipelines/test_tabular_ml.py 구조

```python
# tests/pipelines/test_tabular_ml.py
import pytest
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from pipelines.tabular_ml.pipeline import TabularMLPipeline


@pytest.fixture(scope="module")
def titanic_data():
    df = pd.read_csv("tests/fixtures/titanic.csv")
    # 기본 전처리
    df = df[["Pclass", "Sex", "Age", "Fare", "Survived"]].dropna()
    df["Sex"] = LabelEncoder().fit_transform(df["Sex"])
    X = df.drop("Survived", axis=1).values
    y = df["Survived"].values
    return train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)


@pytest.mark.parametrize("model_name", ["RandomForest", "XGBoost", "LightGBM", "CatBoost"])
def test_train_and_evaluate(titanic_data, model_name):
    X_train, X_val, y_train, y_val = titanic_data
    pipeline = TabularMLPipeline()

    # 기본 파라미터로 학습
    default_params = {
        "RandomForest": {"n_estimators": 100, "random_state": 42, "n_jobs": -1},
        "XGBoost":      {"n_estimators": 100, "random_state": 42, "verbosity": 0},
        "LightGBM":     {"n_estimators": 100, "random_state": 42, "verbose": -1},
        "CatBoost":     {"iterations": 100, "random_seed": 42, "verbose": 0},
    }

    model = pipeline.train(X_train, y_train, model_name, default_params[model_name])
    metrics = pipeline.evaluate(model, X_val, y_val, task="classification")

    assert "val_f1" in metrics
    assert metrics["val_f1"] >= 0.70, (
        f"{model_name} val_f1={metrics['val_f1']:.4f} < 0.70 기준 미달"
    )
    assert 0.0 <= metrics["val_accuracy"] <= 1.0


def test_supported_models():
    assert set(TabularMLPipeline.SUPPORTED_MODELS.keys()) == {
        "RandomForest", "XGBoost", "LightGBM", "CatBoost"
    }


def test_unsupported_model_raises():
    pipeline = TabularMLPipeline()
    with pytest.raises(ValueError, match="미지원 모델"):
        pipeline.train([[1, 2]], [0], "InvalidModel", {})
```

---

## 📁 생성/수정 파일 목록

```
프로젝트 루트/
├── pipelines/
│   ├── __init__.py
│   ├── base.py                         # (Day 4에서 작성, Day 7에서 검토)
│   ├── factory.py                      # (Day 4에서 작성)
│   └── tabular_ml/
│       ├── __init__.py
│       ├── pipeline.py                 # [B] TabularMLPipeline 구현
│       └── search_space.py             # [B] Optuna 탐색 공간 정의
├── agents/
│   └── model_selection.py              # [B] ModelSelectionAgent (Claude Sonnet 4.6)
└── tests/
    ├── pipelines/
    │   ├── test_tabular_ml.py          # [B+D] 파이프라인 단위 테스트
    │   └── test_search_space.py        # [B+D] 탐색 공간 단위 테스트
    └── agents/
        └── test_model_selection.py     # [B+D] ModelSelectionAgent 단위 테스트
```

---

## 🔗 의존성 & 선행 조건

- **Day 4 완료 필수**: `pipelines/base.py`, `pipelines/factory.py` (BasePipeline 추상 클래스)
- **Day 5 완료 필수**: `tools/minio_tool.py` (모델 저장용 MinIOClient)
- scikit-learn 설치 확인 (`pip show scikit-learn`)
- xgboost 설치 확인 (`pip show xgboost`)
- lightgbm 설치 확인 (`pip show lightgbm`)
- catboost 설치 확인 (`pip show catboost`)
- optuna 설치 확인 (`pip show optuna`)
- mlflow 설치 확인 (`pip show mlflow`)
- MLflow 컨테이너 healthy, 실험 `ada-tabular-ml` 존재 확인
- `tests/fixtures/titanic.csv` 파일 존재 확인

---

## ✔️ 완료 기준 (Done Criteria)

- [ ] `pytest tests/pipelines/test_tabular_ml.py -v` — 4개 모델 전부 통과, `val_f1 >= 0.70` 달성
- [ ] `pytest tests/pipelines/test_search_space.py -v` — 탐색 공간 검증 전부 통과
- [ ] `pytest tests/agents/test_model_selection.py -v` — 3개 후보 정상 반환 확인
- [ ] `python -c "from pipelines.tabular_ml.pipeline import TabularMLPipeline; print(list(TabularMLPipeline.SUPPORTED_MODELS.keys()))"` 4개 모델명 출력
- [ ] `python -c "from pipelines.tabular_ml.search_space import get_search_space; import optuna; t=optuna.create_study().ask(); print(get_search_space('XGBoost', t))"` 성공
- [ ] MLflow UI(http://localhost:5000) 에서 `ada-tabular-ml` 실험에 run 기록 확인
- [ ] `ModelSelectionAgent` 호출 시 `state.model_candidates` 에 정확히 3개 항목 반환
- [ ] CatBoost 학습 중 verbose 출력 없음 확인 (로그 억제)

---

## ⚠️ 주의사항 & 제약

### AGENTS.md 룰 (Day 7 적용)

- **R-201**: 모든 모델 학습 결과는 MLflow에 run 기록 필수. `mlflow.log_params()` + `mlflow.log_metrics()` 양쪽 모두 기록
- **R-202**: 학습된 모델 파일은 반드시 MinIO에 저장 후 `models` 테이블에 경로 기록
- **R-203**: job당 `is_best=True` 모델은 1개만 존재. 업데이트 시 기존 best 플래그 해제 필수
- **R-301**: Optuna 탐색은 기본 50 trials. Day 8 HyperparameterTunerAgent에서 적용
- **R-302**: 교차검증은 StratifiedKFold(분류) / KFold(회귀) 기본 5-fold

### 모델별 주의사항

- **XGBoost**: `use_label_encoder=False` 필수 (XGBoost 1.6+ 경고 억제), `verbosity=0`
- **LightGBM**: `verbose=-1` 필수 (학습 중 콘솔 출력 억제)
- **CatBoost**: `verbose=0` 필수, `random_seed` (XGBoost/LightGBM은 `random_state`)
- **RandomForest**: `n_jobs=-1` 설정하여 모든 CPU 코어 사용

### MLflow 연동 주의사항

- `mlflow.start_run(nested=True)` 사용 이유: HyperparameterTuner가 상위 run을 생성할 예정
- `mlflow_run_id` 를 `self` 에 저장하는 것은 thread-safe 하지 않음 — Day 8에서 run_id를 PipelineState로 전달하는 방식으로 리팩토링 예정
- MLflow 서버 미기동 시 `mlflow.exceptions.MlflowException` 발생 → 로깅만 skip, 학습은 계속 진행

### 성능 목표

- Titanic 데이터 기준 `val_f1 >= 0.70` 달성 (기본 파라미터, 전처리 포함)
- 기본 파라미터 학습 시간: RandomForest < 5초, XGBoost < 10초, LightGBM < 8초, CatBoost < 15초
- Optuna 50 trials 탐색 시간(Day 8): 모델별 10~30분 예상

### 데이터 전처리 주의사항 (테스트 픽스처 전처리)

- Titanic 테스트 시 결측값 처리 필수 (`Age` 컬럼 등)
- 범주형 변수(`Sex`, `Embarked`) → 수치형 인코딩 필수 (XGBoost/LightGBM/RandomForest 요구)
- CatBoost는 범주형 그대로 처리 가능하나 테스트에서는 통일하여 수치형 사용
- `train_test_split(stratify=y)` 로 클래스 비율 유지

### PipelineFactory 연동

- `TabularMLPipeline` 은 `pipelines/factory.py` 의 `PIPELINE_REGISTRY["tabular_ml"]` 에 등록되어야 함
- Day 4에서 작성한 `PipelineFactory.create("tabular_ml")` 호출 시 `TabularMLPipeline()` 반환 확인

---

## 🆕 v2 확장 작업 (마스터 설계서 §7 · §4-B)

> Day7 의 v2 핵심: (1) **MethodologyProposerAgent (G2)** 신설 — EDA 직후 ML/DL/시계열/이상탐지/하이브리드를 비교 제안. (2) **ModelSelectionAgent v2** 가 **트랜스포머 우선** 정책으로 Top-3 후보를 선정.

### 1. `agents/eda_agent.py` 확장 — EDA 결과의 LLM 친화적 요약

- [ ] EDA 결과(차트 목록, 상관관계 인사이트, 분포 특이점)를 `state.eda_summary_text` 에 저장 (G2 제안의 컨텍스트)

### 2. `agents/proposers/methodology_proposer.py` — MethodologyProposerAgent (G2)

- [ ] BaseGateAgent 상속, gate_code='G2', Claude Sonnet 4.6 (응답 길이 중요)
- [ ] `build_proposals(state)` 시스템 프롬프트:
  ```
  당신은 데이터 분석 방법론 전문가입니다.
  데이터 프로파일과 EDA 인사이트를 분석하여
  적합한 방법론 후보 3~4개를 비교표 형식 JSON으로 응답:
  [
    {
      "method": "tabular_ml | tabular_dl | timeseries |
                 anomaly_detection | hybrid_ml_dl",
      "title": "표시명",
      "why": "이 방법론이 적합한 이유",
      "fit_score": 0.0~1.0,
      "transformer_available": true,
      "expected_primary_metric": "val_f1=0.83",
      "interpretability": "high|medium|low",
      "cost": "low|medium|high",
      "rationale_for_recommendation_rank": 1
    }, ...
  ]
  ```
- [ ] 정확히 1순위 추천을 표시 (rank=1)

### 3. `pipelines/registry.py` 신규 — 트랜스포머 레지스트리 (8종)

```python
TRANSFORMER_REGISTRY = {
    "tabular_ml":        ["TabTransformer", "FTTransformer", "TabPFN"],
    "tabular_dl":        ["FTTransformer", "TabPFN"],
    "timeseries":        ["Informer", "TFT", "PatchTST"],
    "anomaly_detection": ["TranAD", "AnomalyTransformer"],
}
TREE_REGISTRY = {
    "tabular_ml": ["RandomForest", "XGBoost", "LightGBM", "CatBoost"],
    "tabular_dl": [],
    "timeseries": ["Prophet", "ARIMA", "SARIMA"],
    "anomaly_detection": ["IsolationForest", "LOF", "OneClassSVM"],
}
SPECIALTY_REGISTRY = {
    "tabular_ml": ["LogisticRegression"],
    "tabular_dl": ["MLP", "TabNet"],
    "timeseries": ["LSTM"],
    "anomaly_detection": ["AutoEncoder"],
}
```
*(트랜스포머 8종: TabTransformer / FTTransformer / TabPFN / Informer / TFT / PatchTST / TranAD / AnomalyTransformer)*

### 4. `agents/model_selection.py` v2 확장

- [ ] v1의 LLM 제안에 더해 **R-403 강제** 적용:
  ```python
  def __call__(self, state):
      llm_candidates = self._llm_propose(state)        # v1 로직
      # 트랜스포머가 후보에 없으면 강제 주입
      if not any(c in TRANSFORMER_REGISTRY[state.category] for c in llm_candidates):
          transformer_pick = TRANSFORMER_REGISTRY[state.category][0]
          llm_candidates = [transformer_pick] + llm_candidates[:2]
      # 최종 Top-3
      return state.model_copy(update={"model_candidates": llm_candidates[:3]})
  ```
- [ ] LLM 응답에 `transformer_used: bool` 메타 포함 강제

### 5. 자체학습 KB warm start 사용

- [ ] `ModelSelectionAgent` 가 후보 선정 시 `SelfLearningClient.fetch_recipes(category, ['recipe','success_pattern'])` 결과를 컨텍스트에 주입
- [ ] 응답에 `referenced_past_jobs: [...]` 포함 (재현성/감사 추적)

### 6. 완료 기준 (v2 추가)

- [ ] G2 응답 JSON에 transformer_available=true 인 안이 최소 1개
- [ ] tabular_ml 카테고리 ModelSelection 결과의 model_candidates 에 TabTransformer/FTTransformer/TabPFN 중 1개 이상 포함
- [ ] 동일 데이터셋 2회차 분석 시 ModelSelection 응답에 `referenced_past_jobs` 비어있지 않음

### 7. 주의사항 (v2)

- TabPFN 은 ≤ 10000행 / ≤ 100특성에서만 동작 — 룰 R-201 추가: 데이터 크기 체크 후 자동 제외
- Transformer 후보가 데이터 부족으로 동작 불가능한 경우(예: 시계열 < 200개 시점에서 Informer/TFT) MethodologyProposer 단계에서 미리 제외
- G2 응답이 4개일 수 있음 (3~4) — UI 동적 처리
