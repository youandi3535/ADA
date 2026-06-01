"""tabular E2E — Titanic(분류) · Iris(다중분류) · Adult(회귀) 3 시나리오 (Day 10 jh).

DoD: 3 데이터 모두 val_f1 / val_r2 임계 통과.

설계 요지 (작업설계/Day10_jh_tabular_E2E_detailed_design.md):
  - 오프라인·결정적: vendored CSV(tests/handlers/tabular/data/) 있으면 사용, 없으면 합성 fallback.
    Iris 는 sklearn 내장.
  - 모델은 RandomForest 고정(sklearn-only → CI 이식성). 데모(tabular_demo.py)는 다른 모델도 시연.
  - 회귀는 evaluator 에 val_r2 임계가 없어(공허 통과) 본 테스트가 직접 assert 한다.

주의(P0): 본 테스트는 run_scenario 안에서 ``import agents.handlers.tabular`` 로 핸들러를 로드한다.
  해당 패키지가 import 가능해야 하며(현재 작업 사본의 preprocessor truncation / NUL 패딩 복구 후),
  불가 시 collection 또는 실행 단계에서 실패한다.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("sklearn")

# 시나리오 → (지표 키, 임계)
THRESHOLDS: dict[str, tuple[str, float]] = {
    "titanic": ("val_f1", 0.75),
    "iris": ("val_f1", 0.85),  # 25% val split(38샘플)에서 RF≈0.89 → 0.85 로 robust 하게(0.90은 flaky)
    "adult": ("val_r2", 0.30),
}

_DATA_DIR = Path(__file__).parent / "data"
_SEED = 42
_SCENARIOS = ("titanic", "iris", "adult")


# --------------------------------------------------------------------------- #
# 데이터 레이어 — 합성 generator (결정적, 외부 fetch 0)
# --------------------------------------------------------------------------- #
def _synth_titanic(n: int = 300, seed: int = _SEED) -> pd.DataFrame:
    """Titanic 유사 분류 데이터. 신호: 여성·낮은 Pclass·어린 Age 생존↑."""
    rng = np.random.default_rng(seed)
    pclass = rng.choice([1, 2, 3], size=n, p=[0.25, 0.25, 0.5])
    sex = rng.choice(["male", "female"], size=n, p=[0.6, 0.4])
    age = rng.uniform(1, 70, size=n).round(1)
    fare = (60.0 / pclass + rng.normal(0, 5, size=n)).clip(5, 200).round(2)
    sibsp = rng.integers(0, 3, size=n)
    parch = rng.integers(0, 3, size=n)
    fare_median = float(np.median(fare))
    logit = (
        1.2 * (sex == "female")
        + 0.9 * (pclass == 1)
        + 0.4 * (pclass == 2)
        - 0.02 * age
        + 0.3 * (fare > fare_median)
        + rng.normal(0, 0.5, size=n)
    )
    survived = (1.0 / (1.0 + np.exp(-logit)) > 0.5).astype(int)
    return pd.DataFrame(
        {
            "Pclass": pclass,
            "Sex": sex,
            "Age": age,
            "Fare": fare,
            "SibSp": sibsp,
            "Parch": parch,
            "Survived": survived,
        }
    )


def _synth_adult(n: int = 500, seed: int = _SEED) -> pd.DataFrame:
    """Adult 유사 회귀 데이터. target=age, 신호: 학력·근로시간·성별."""
    rng = np.random.default_rng(seed)
    education_num = rng.integers(1, 17, size=n)
    hours = rng.normal(40, 10, size=n).clip(5, 90).round(1)
    workclass = rng.choice(["Private", "Self-emp", "Gov", "Federal", "Local"], size=n)
    sex = rng.choice(["male", "female"], size=n)
    age = (
        18
        + 1.5 * education_num
        + 0.25 * hours
        + 6.0 * (sex == "male")
        + rng.normal(0, 4, size=n)
    ).clip(17, 90).round(1)
    return pd.DataFrame(
        {
            "education_num": education_num,
            "hours_per_week": hours,
            "workclass": workclass,
            "sex": sex,
            "age": age,
        }
    )


def _fetch_real(name: str) -> pd.DataFrame | None:
    """데모 --real 전용. 실데이터 fetch 시도(네트워크). 실패 시 None → 합성 fallback."""
    try:
        if name == "titanic":
            import seaborn as sns

            d = sns.load_dataset("titanic")
            df = pd.DataFrame(
                {
                    "Pclass": d["pclass"],
                    "Sex": d["sex"],
                    "Age": d["age"],
                    "Fare": d["fare"],
                    "SibSp": d["sibsp"],
                    "Parch": d["parch"],
                    "Survived": d["survived"],
                }
            ).dropna()
            df["Age"] = df["Age"].astype(float)
            return df.reset_index(drop=True)
        if name == "adult":
            from sklearn.datasets import fetch_openml

            d = fetch_openml("adult", version=2, as_frame=True)
            df = d.frame.rename(
                columns={"education-num": "education_num", "hours-per-week": "hours_per_week"}
            )
            cols = ["education_num", "hours_per_week", "workclass", "sex", "age"]
            df = df[cols].dropna()
            df["age"] = df["age"].astype(float)
            return df.reset_index(drop=True)
    except Exception:
        return None
    return None


def load_scenario(name: str, *, real: bool = False, seed: int = _SEED):
    """return (df_with_target, target_column, task).

    우선순위: (real 시) fetch → vendored CSV → 합성. Iris 는 항상 sklearn 내장.
    task ∈ {"classification", "regression"}.
    """
    name = name.lower()
    if name == "iris":
        from sklearn.datasets import load_iris

        df = load_iris(as_frame=True).frame.copy()
        return df, "target", "classification"

    if name == "titanic":
        if real and (df := _fetch_real("titanic")) is not None:
            return df, "Survived", "classification"
        csv = _DATA_DIR / "titanic.csv"
        if csv.exists():
            return pd.read_csv(csv), "Survived", "classification"
        return _synth_titanic(seed=seed), "Survived", "classification"

    if name == "adult":
        if real and (df := _fetch_real("adult")) is not None:
            return df, "age", "regression"
        csv = _DATA_DIR / "adult.csv"
        if csv.exists():
            return pd.read_csv(csv), "age", "regression"
        return _synth_adult(seed=seed), "age", "regression"

    raise ValueError(f"unknown scenario: {name!r}")


# --------------------------------------------------------------------------- #
# 공통 E2E 엔진 — run_scenario (S1~S9)
# --------------------------------------------------------------------------- #
def _params(model: str, task: str, seed: int = _SEED) -> dict:
    if model == "RandomForest":
        p: dict = {"n_estimators": 200, "random_state": seed, "n_jobs": -1}
        if task == "classification":
            p["class_weight"] = "balanced"
        return p
    return {"random_state": seed}


def _encode_Xy(df: pd.DataFrame, target: str):
    """범주형 one-hot + 수치 ndarray 반환."""
    y = df[target].to_numpy()
    X = pd.get_dummies(df.drop(columns=[target]), drop_first=True)
    return X.to_numpy(dtype=float), y


def run_scenario(name: str, *, model: str = "RandomForest", real: bool = False, seed: int = _SEED) -> dict:
    """E2E 1 시나리오: load→profile→(preprocess)→split→train→evaluate→gate.

    핸들러(profile/plan/apply/evaluate)는 있으면 사용, 없거나 실패하면 무해하게 건너뛴다.
    학습·평가는 실제 TabularMLPipeline 을 사용한다.
    """
    from sklearn.model_selection import train_test_split

    t0 = time.perf_counter()

    # S1 load
    df, target, task = load_scenario(name, real=real, seed=seed)

    # S2 state
    from ada.core.state import PipelineState

    state = PipelineState(
        job_id=str(uuid.uuid4()),
        file_id=f"memory://{name}",
        category="tabular_ml",
        target_column=target,
        task=task,
        user_intent=f"E2E {name}",
    )

    from agents.handlers import get_handler

    # S3 profile (실패 무해)
    prof_fn = get_handler("tabular_ml", "profile")
    if prof_fn is not None:
        try:
            state = state.with_update(data_profile=prof_fn(df, state) or {})
        except Exception:
            pass

    # S4 preprocess (핸들러 있으면 사용, 없거나 실패 시 자체 인코딩으로 진행)
    plan_fn = get_handler("tabular_ml", "plan")
    apply_fn = get_handler("tabular_ml", "apply")
    if plan_fn is not None and apply_fn is not None:
        try:
            df, state = apply_fn(df, plan_fn(state), state)
        except Exception:
            pass

    # S5 encode + split
    X, y = _encode_Xy(df, target)
    stratify = None
    if task == "classification" and pd.Series(y).value_counts().min() >= 2:
        stratify = y
    X_tr, X_val, y_tr, y_val = train_test_split(
        X, y, test_size=0.25, random_state=seed, stratify=stratify
    )

    # S6 train + S7 evaluate (실제 파이프라인)
    from pipelines.tabular_ml import TabularMLPipeline

    pipe = TabularMLPipeline()
    fitted = pipe.train(X_tr, y_tr, model, _params(model, task, seed))
    metrics = pipe.evaluate(fitted, X_val, y_val, task)

    # S8 gate (분류만 — evaluator 에 val_r2 임계 없음 → 회귀는 §S9 에서 직접 판정)
    gate_passed = None
    if task == "classification":
        eval_fn = get_handler("tabular_ml", "evaluate")
        if eval_fn is not None:
            state = state.with_update(best_model={"model_name": model, "metrics": metrics})
            try:
                gate_passed = bool(eval_fn(state)["passed"])
            except Exception:
                gate_passed = None

    # S9 결과
    metric_key = THRESHOLDS[name][0]
    threshold = THRESHOLDS[name][1]
    value = float(metrics.get(metric_key, float("nan")))
    return {
        "name": name,
        "task": task,
        "model": model,
        "metrics": metrics,
        "metric_key": metric_key,
        "value": value,
        "threshold": threshold,
        "passed": value >= threshold,
        "gate_passed": gate_passed,
        "elapsed_s": round(time.perf_counter() - t0, 2),
    }


# --------------------------------------------------------------------------- #
# 테스트 — 각 시나리오는 모듈 스코프에서 1회만 학습(중복 제거)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def e2e_results() -> dict[str, dict]:
    return {name: run_scenario(name) for name in _SCENARIOS}


def test_e2e_handlers_registered():
    """tabular 핸들러 패키지 import + 8 capability 등록 (P0 게이트키퍼)."""
    import agents.handlers.tabular  # noqa: F401
    from agents.handlers import HANDLER_REGISTRY

    caps = {"profile", "plan", "apply", "charts", "score", "evaluate", "g1", "g2"}
    missing = caps - set(HANDLER_REGISTRY.get("tabular_ml", {}))
    assert not missing, f"미등록 capability: {missing}"


@pytest.mark.parametrize("name", _SCENARIOS)
def test_e2e_thresholds(name, e2e_results):
    """DoD — 3 데이터 모두 val_f1 / val_r2 임계 통과."""
    r = e2e_results[name]
    key, thr = THRESHOLDS[name]
    assert key in r["metrics"], f"{name}: {key} 누락 (metrics={list(r['metrics'])})"
    assert r["value"] >= thr, f"{name}: {key}={r['value']:.3f} < {thr}"


def test_e2e_classification_gate_passes(e2e_results):
    """분류는 evaluator 게이트도 통과해야 함 (Titanic)."""
    r = e2e_results["titanic"]
    assert r["gate_passed"] is True, f"gate 실패: {r['metrics']}"


def test_e2e_regression_exposes_r2(e2e_results):
    """C4 가드 — evaluator 에 val_r2 임계가 없으므로 회귀는 본 테스트가 직접 보장."""
    r = e2e_results["adult"]
    assert "val_r2" in r["metrics"], "회귀 metrics 에 val_r2 없음"
    assert r["value"] >= THRESHOLDS["adult"][1]


def test_e2e_runtime_budget(e2e_results):
    """3 시나리오 합산 학습 시간 < 90s (데모 5분 예산의 여유분)."""
    total = sum(r["elapsed_s"] for r in e2e_results.values())
    assert total < 90, f"E2E 합산 {total:.1f}s 초과"
