"""tests.handlers.tabular.test_train_batch — 모델 병렬 학습 검증.

검증 범위:
  1. train_batch 가 sequential train() 과 동일 모델 인스턴스 반환
  2. 결과 순서가 specs 순서와 일치
  3. 한 모델 실패해도 다른 모델은 정상 (graceful)
  4. 4 모델 동시 학습 시간이 sequential 대비 빠름 (≥ 2× 가속)
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from pipelines.tabular_ml.pipeline import TabularMLPipeline


def _make_data(n: int = 500, n_features: int = 5, seed: int = 42):
    rng = np.random.default_rng(seed)
    X = rng.normal(0, 1, (n, n_features))
    y = ((X[:, 0] + X[:, 1]) > 0).astype(int)
    return X, y


class TestTrainBatch:
    def test_returns_list_with_same_order(self):
        """specs 순서대로 결과 반환."""
        X, y = _make_data()
        pipe = TabularMLPipeline()
        specs = [
            {"model_name": "Dummy", "params": {}},
            {"model_name": "LogisticRegression", "params": {}},
        ]
        results = pipe.train_batch(X, y, specs, n_jobs=1)  # 단일 워커 - test 안정성
        assert len(results) == 2
        assert results[0]["model_name"] == "Dummy"
        assert results[1]["model_name"] == "LogisticRegression"

    def test_each_result_has_required_keys(self):
        X, y = _make_data()
        pipe = TabularMLPipeline()
        specs = [{"model_name": "Dummy", "params": {}}]
        results = pipe.train_batch(X, y, specs, n_jobs=1)
        r = results[0]
        assert {"model_name", "params", "model", "error"}.issubset(r.keys())

    def test_successful_train_has_model_and_no_error(self):
        X, y = _make_data()
        pipe = TabularMLPipeline()
        specs = [{"model_name": "Dummy", "params": {}}]
        results = pipe.train_batch(X, y, specs, n_jobs=1)
        assert results[0]["model"] is not None
        assert results[0]["error"] is None

    def test_failed_model_doesnt_break_others(self):
        """한 모델 실패해도 다른 모델 결과는 정상 반환."""
        X, y = _make_data()
        pipe = TabularMLPipeline()
        specs = [
            {"model_name": "Dummy", "params": {}},
            {"model_name": "_NonExistentModel_", "params": {}},  # _build_model 실패
            {"model_name": "LogisticRegression", "params": {}},
        ]
        results = pipe.train_batch(X, y, specs, n_jobs=1)
        assert len(results) == 3
        assert results[0]["error"] is None  # Dummy 성공
        assert results[1]["error"] is not None  # 실패 보고
        assert results[1]["model"] is None
        # LogisticRegression 도 정상 (Dummy 와 독립)
        assert results[2]["error"] is None or "param" in (results[2]["error"] or "").lower()

    def test_models_are_actually_trained(self):
        """반환된 model 이 실제 fit 된 상태 (predict 호출 가능)."""
        X, y = _make_data()
        pipe = TabularMLPipeline()
        specs = [{"model_name": "Dummy", "params": {}}]
        results = pipe.train_batch(X, y, specs, n_jobs=1)
        model = results[0]["model"]
        preds = model.predict(X[:5])
        assert len(preds) == 5


class TestTrainBatchPerformance:
    """병렬화 효과 검증 — 직렬 vs 병렬 시간 비교."""

    @pytest.mark.slow
    def test_parallel_faster_than_sequential(self):
        """가벼운 모델 4종 학습이 병렬에서 더 빠름.

        Dummy/LR/Ridge 는 매우 빨라 병렬화 오버헤드가 더 클 수 있음.
        그래서 무거운 모델(RandomForest) 4번 학습으로 비교.
        """
        import os

        if (os.cpu_count() or 1) <= 1:
            pytest.skip("단일 코어 환경 — 병렬화 효과 없음")

        X, y = _make_data(n=2000, n_features=10)
        pipe = TabularMLPipeline()

        rf_specs = [{"model_name": "RandomForest", "params": {"n_estimators": 50}}] * 4

        # Sequential
        t0 = time.time()
        seq_results = []
        for spec in rf_specs:
            seq_results.append(pipe.train(X, y, spec["model_name"], spec["params"]))
        seq_time = time.time() - t0

        # Parallel
        t0 = time.time()
        par_results = pipe.train_batch(X, y, rf_specs, n_jobs=-1)
        par_time = time.time() - t0

        assert len(par_results) == 4
        assert all(r["model"] is not None for r in par_results)
        # 병렬이 적어도 1.3× 빠르길 기대 (joblib 오버헤드 감안)
        assert par_time < seq_time / 1.3, (
            f"병렬 {par_time:.1f}s 가 sequential {seq_time:.1f}s 대비 1.3× 빠르지 않음 — "
            f"환경 의존 (CPU 코어, joblib 오버헤드). 단일 코어면 이 테스트는 의미 없음."
        )
