"""tests.handlers.tabular.test_leakage_safe_expert — 누수 차단 전문가 버전 회귀 가드.

2026-06-15 (HJ, 마스터 권한) — 4단계 보드에서 스케일 민감 모델(LR)만 부풀던 누수를
구조적으로 차단한 5개 Fix 의 회귀 가드. 각 테스트는 "수정 없으면 실패, 수정 있으면 통과".

- Fix 1: training_executor._leakage_split_bounds 가 tabular/anomaly 두 키 네이밍 모두 인정.
- Fix 2: preprocessor._transform_only 가 val/test 를 train 통계로만 변환(자기 통계 누수 금지)
         + encode 후 train/val 컬럼 스키마 일치.
- Fix 5: preprocessor.fit_transform_train_val 가 폴드별 누수 없는 전처리(스키마 일치) 제공.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ada.core.state import PipelineState
from agents.handlers.tabular import preprocessor as pp


def _state(target: str = "y", category: str = "tabular_ml") -> PipelineState:
    return PipelineState(job_id="t-leak", file_id="f", category=category, target_column=target)


# ──────────────────────────────────────────────────────────────────────────────
# Fix 1 — 경계 키 정합 (tabular / anomaly 키 모두 인정)
# ──────────────────────────────────────────────────────────────────────────────
class TestLeakageSplitBoundsKeyCompat:
    def test_tabular_keys(self):
        from agents.training_executor import _leakage_split_bounds

        st = _state(category="tabular_ml").with_update(
            category_extras={
                "tabular": {"leakage_safe_split": {"train_row_count_for_reorder": 80, "val_row_count": 20}}
            }
        )
        assert _leakage_split_bounds(st) == (80, 20)

    def test_anomaly_keys(self):
        from agents.training_executor import _leakage_split_bounds

        st = _state(category="anomaly_detection").with_update(
            category_extras={"anomaly_detection": {"leakage_safe_split": {"n_train": 70, "n_val": 30}}}
        )
        # 수정 전: anomaly 는 n_train/n_val 만 기록 → None → 무작위 재분할 누수 폴백.
        assert _leakage_split_bounds(st) == (70, 30)

    def test_incomplete_returns_none(self):
        from agents.training_executor import _leakage_split_bounds

        st = _state(category="tabular_ml").with_update(
            category_extras={"tabular": {"leakage_safe_split": {"train_row_count_for_reorder": 80}}}
        )
        assert _leakage_split_bounds(st) is None


# ──────────────────────────────────────────────────────────────────────────────
# Fix 2 — _transform_only 가 train 통계로만 변환
# ──────────────────────────────────────────────────────────────────────────────
class TestTransformOnlyUsesTrainStats:
    def test_impute_numeric_uses_train_median_not_val(self):
        """val 의 NaN 은 val 자기 median 이 아니라 train median 으로 채워야 한다."""
        st = _state()
        plan = [{"name": "impute_numeric", "strategy": "median", "params": {}}]
        df_train = pd.DataFrame({"x": [10.0, 10.0, 10.0, np.nan], "y": [0, 1, 0, 1]})
        df_train_proc, st2 = pp.apply(df_train, plan, st)
        artifacts = st2.category_extras["tabular"]["preprocess_artifacts"]

        # val median(x)=1000 이지만 train median(=10)으로 채워져야 함
        df_val = pd.DataFrame({"x": [1000.0, 1000.0, np.nan], "y": [1, 0, 1]})
        out = pp._transform_only(df_val, plan, artifacts, st2)
        assert out["x"].iloc[2] == pytest.approx(10.0), "val NaN 이 train median 이 아닌 값으로 채워짐 — 누수"

    def test_impute_categorical_uses_train_mode_not_val(self):
        """val 의 결측 범주는 train mode 로 채워야 한다."""
        st = _state()
        plan = [{"name": "impute_categorical", "strategy": "most_frequent", "params": {}}]
        # train mode = 'a' (3개)
        df_train = pd.DataFrame({"c": ["a", "a", "a", "b", None], "y": [0, 1, 0, 1, 0]})
        _, st2 = pp.apply(df_train, plan, st)
        artifacts = st2.category_extras["tabular"]["preprocess_artifacts"]
        # val mode = 'z' (2개) 이지만 train mode('a')로 채워야 함
        df_val = pd.DataFrame({"c": ["z", "z", None], "y": [1, 0, 1]})
        out = pp._transform_only(df_val, plan, artifacts, st2)
        assert out["c"].iloc[2] == "a", "val 결측이 train mode('a') 가 아닌 값으로 채워짐 — 누수"

    def test_encode_categorical_schema_matches_train(self):
        """미관측 카테고리가 있어도 encode 후 train/val 컬럼 스키마가 일치해야 한다."""
        st = _state()
        plan = [{"name": "encode_categorical", "params": {"high_card_threshold": 50}}]
        df_train = pd.DataFrame({"c": ["a", "b", "a", "c"], "y": [0, 1, 0, 1]})
        df_train_proc, st2 = pp.apply(df_train, plan, st)
        artifacts = st2.category_extras["tabular"]["preprocess_artifacts"]
        # val: 미관측 'd' 포함, train 의 'c' 없음 → 수정 전이면 컬럼 불일치(c_d 생성/c_c 누락)
        df_val = pd.DataFrame({"c": ["a", "d", "b"], "y": [1, 0, 1]})
        out = pp._transform_only(df_val, plan, artifacts, st2)
        train_cols = {c for c in df_train_proc.columns if c != "y"}
        val_cols = {c for c in out.columns if c != "y"}
        assert val_cols == train_cols, f"encode 후 train/val 컬럼 불일치 — train={train_cols} val={val_cols}"


# ──────────────────────────────────────────────────────────────────────────────
# Fix 5 — fit_transform_train_val (폴드별 누수 없는 전처리)
# ──────────────────────────────────────────────────────────────────────────────
class TestFitTransformTrainVal:
    def test_schema_consistent_with_unseen_category(self):
        st = _state()
        rng = np.random.RandomState(0)
        df_tr = pd.DataFrame({"x": rng.normal(0, 1, 60), "c": rng.choice(["a", "b"], 60), "y": rng.choice([0, 1], 60)})
        # val 에만 'z' 카테고리 + 분포 다른 x
        df_va = pd.DataFrame(
            {"x": rng.normal(5, 1, 20), "c": rng.choice(["a", "b", "z"], 20), "y": rng.choice([0, 1], 20)}
        )
        plan = [
            {"name": "impute_numeric", "strategy": "median", "params": {}},
            {"name": "encode_categorical", "params": {"high_card_threshold": 50}},
            {"name": "scale_numeric", "method": "robust", "params": {}},
        ]
        tr_proc, va_proc = pp.fit_transform_train_val(df_tr, df_va, plan, st)
        assert list(tr_proc.columns) == list(va_proc.columns), "fit_transform_train_val 컬럼 불일치"
        assert len(tr_proc) == 60 and len(va_proc) == 20
