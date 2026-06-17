"""agents.feature_engineer — Day 0 dispatcher 패턴.

카테고리별 step 적용은 ``handlers/{cat}/preprocessor.apply(df, plan, state)`` 가 담당.
수정 권한: **HJ 단독** (dispatcher).
"""

from __future__ import annotations

import uuid

import agents.handlers.anomaly  # noqa: F401
import agents.handlers.tabular  # noqa: F401
import agents.handlers.timeseries  # noqa: F401
from ada.core.state import PipelineState
from agents.base import BaseAgent
from agents.handlers import get_handler
from agents.handlers.common.shared import load_dataframe_from_state
from tools.minio_tool import get_minio_client


# HJ 2026-06-11 — frontend G3 모달 라이브 피드용. before/after 컬럼 비교 + plan step 명을 Redis 에 publish.
# eda_agent.py 의 패턴 그대로. Redis 실패해도 본 흐름 영향 없음.
def _safe_publish_stage_partial(job_id: str | None, partial: dict) -> None:
    if not job_id or not isinstance(partial, dict) or not partial:
        return
    try:
        from orchestrator.runner import publish_stage_partial as _psp

        _psp(job_id, partial)
    except Exception:  # noqa: BLE001
        pass


# HJ 2026-06-11 — 전처리 plan step 이름 → 사용자 친화 한국어 라벨.
# 매핑되지 않은 step 명은 원문 그대로 노출.
_STEP_KO: dict[str, str] = {
    "polynomial_features": "다항 피처 (x², xy)",
    "interaction_terms": "교호작용 항 (x1 × x2)",
    "target_encoding": "타깃 인코딩",
    "frequency_encoding": "빈도 인코딩",
    "hash": "해시 인코딩",
    "hash_encoding": "해시 인코딩",
    "onehot": "원핫 인코딩",
    "ordinal": "순서형 인코딩",
    "binning": "구간화 (binning)",
    "log_transform": "로그 변환",
    "boxcox": "Box-Cox 변환",
    "scale_standard": "표준 스케일링 (z-score)",
    "scale_minmax": "MinMax 스케일링",
    "scale_robust": "Robust 스케일링",
    "impute_numeric": "수치 결측 보간",
    "impute_categorical": "범주 결측 보간",
    "outlier_clip": "이상치 클리핑",
    "drop_high_missing": "고결측 컬럼 제거",
    "drop_constant": "상수 컬럼 제거",
    "drop_duplicates": "중복 행 제거",
}


def _leakage_safe_fallback(df, plan, state):
    """HJ 2026-06-15 — Fix 4: apply_split 예외 시 누수 있는 full apply() 대신 인라인 안전 분할.

    위치 기반 train/val 분할 → train 으로만 apply()(fit) → val 은 카테고리 transform-only.
    성공 시 (df_concat, new_state) 반환(leakage_safe_split 경계 기록 → training 위치분할 소비).
    미지원·실패·출력 비정상이면 **None** 반환 → 호출측이 기존 full apply() 폴백(무회귀).

    완전 가드: 모든 예외를 삼키고 None 을 돌려, 이 경로가 어떤 경우에도 기존 동작보다
    나쁘게 만들지 않는다(최악의 경우 = 오늘과 동일).
    """
    try:
        import pandas as pd  # noqa: WPS433

        cat = getattr(state, "category", "") or ""
        if df is None or len(df) < 8:
            return None
        apply_handler = get_handler(cat, "apply")
        if apply_handler is None:
            return None

        # transform-only 콜러블 결정 (카테고리별)
        kind = None
        to_fn = None
        if cat.startswith("tabular"):
            from agents.handlers.tabular.preprocessor import _transform_only as _to  # noqa: WPS433

            kind, to_fn = "tabular", _to
        else:
            ah = get_handler(cat, "apply_transform")
            if ah is not None:
                kind, to_fn = "apply_transform", ah
        if to_fn is None:
            return None

        split = max(1, int(len(df) * 0.8))
        df_train = df.iloc[:split].reset_index(drop=True)
        df_val = df.iloc[split:].reset_index(drop=True)
        if len(df_train) == 0 or len(df_val) == 0:
            return None

        res = apply_handler(df_train, plan or [], state)
        if isinstance(res, tuple) and len(res) == 2:
            df_train_proc, state2 = res
        else:
            df_train_proc, state2 = res, state

        cat_key = "tabular" if cat.startswith("tabular") else cat
        cat_block = (getattr(state2, "category_extras", None) or {}).get(cat_key, {}) or {}
        artifacts = cat_block.get("preprocess_artifacts") or cat_block.get("preprocessor_artifacts") or {}

        if kind == "tabular":
            df_val_proc = to_fn(df_val, plan or [], artifacts, state2)
        else:
            x_val = to_fn(df_val, artifacts)
            df_val_proc = pd.DataFrame(x_val, columns=list(df_train_proc.columns))

        # 컬럼 정합 강제 (train 스키마 기준)
        if list(df_val_proc.columns) != list(df_train_proc.columns):
            df_val_proc = df_val_proc.reindex(columns=list(df_train_proc.columns), fill_value=0)

        n_tr = int(len(df_train_proc))
        n_val = int(len(df_val_proc))
        if n_tr <= 0 or n_val <= 0 or df_train_proc.shape[1] == 0:
            return None

        df_concat = pd.concat([df_train_proc, df_val_proc], axis=0, ignore_index=True)

        extras = dict(getattr(state2, "category_extras", None) or {})
        cat_extras = dict(extras.get(cat_key, {}))
        meta = dict(cat_extras.get("leakage_safe_split") or {})
        meta.update(
            {
                "method": "inline_positional_fallback",
                "train_row_count_for_reorder": n_tr,
                "val_row_count": n_val,
                "n_train": n_tr,
                "n_val": n_val,
            }
        )
        cat_extras["leakage_safe_split"] = meta
        extras[cat_key] = cat_extras
        state2 = state2.with_update(category_extras=extras)
        return df_concat, state2
    except Exception:  # noqa: BLE001 — 어떤 실패든 None → 기존 full apply() 폴백(무회귀)
        return None


# ── 자동 피처선택 (P1-2, HJ 2026-06-16) ──────────────────────────
# 고차원·중복 피처를 에이전트가 스스로 정리(사용자 개입 0). 회귀 위험을 최소화하기 위해
# 무감독·누수0·보수적으로만 한다:
#   · 타깃과 무관한 상수(분산 0)·완전중복(|corr|≥0.99)만 제거 → 타깃 기반 선택의 누수 없음.
#   · tabular 만 적용(timeseries 는 lag 자기상관, anomaly 는 PCA 로 이미 차원관리).
#   · 수치 피처 20개 미만이면 skip(선택 의미 없음), 50% 초과 제거는 위험으로 보고 skip.
#   · 어떤 예외든 원본 df 반환(graceful) → "오늘보다 나쁠 수 없음".
_FS_MIN_FEATURES = 20
_FS_CORR_DUP = 0.99
_FS_MAX_DROP_RATIO = 0.5


def _auto_feature_select(df: "Any", target_col: "str | None") -> "tuple[Any, dict]":  # noqa: F821
    import numpy as np  # noqa: WPS433

    try:
        num = df.select_dtypes(include=[np.number])
        feat_cols = [c for c in num.columns if c != target_col]
        if len(feat_cols) < _FS_MIN_FEATURES:
            return df, {"applied": False, "reason": "few_features", "n_features": len(feat_cols)}

        # 1) 상수(분산 0 또는 비유한)
        stds = num[feat_cols].std(numeric_only=True)
        const = [c for c in feat_cols if (not np.isfinite(stds.get(c, 0.0))) or float(stds.get(c, 0.0)) == 0.0]

        # 2) 완전중복(|corr|≥0.99) — 상삼각 스캔, 먼저 나온 컬럼 유지
        remain = [c for c in feat_cols if c not in const]
        dup: list[str] = []
        if len(remain) >= 2:
            corr = num[remain].corr().abs()
            cols = list(corr.columns)
            seen: set[str] = set()
            for i in range(len(cols)):
                if cols[i] in seen:
                    continue
                for j in range(i + 1, len(cols)):
                    if cols[j] in seen:
                        continue
                    if float(corr.iloc[i, j]) >= _FS_CORR_DUP:
                        seen.add(cols[j])
                        dup.append(cols[j])

        dropped = list(dict.fromkeys(const + dup))
        if not dropped:
            return df, {"applied": True, "dropped": [], "n_dropped": 0}
        if len(dropped) > _FS_MAX_DROP_RATIO * len(feat_cols):
            return df, {"applied": False, "reason": "too_aggressive", "would_drop": len(dropped)}

        df2 = df.drop(columns=[c for c in dropped if c in df.columns])
        return df2, {
            "applied": True,
            "dropped": dropped,
            "n_dropped": len(dropped),
            "n_const": len(const),
            "n_dup": len(dup),
        }
    except Exception as e:  # noqa: BLE001 — 어떤 실패든 원본 유지(무회귀)
        return df, {"applied": False, "reason": f"error:{e}"}


class FeatureEngineerAgent(BaseAgent):
    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            try:
                df = load_dataframe_from_state(state, prefer_processed=False)
            except Exception as e:
                return state.with_update(error=f"데이터 로딩 실패: {e}", next_agent="error_recovery")

            # HJ 2026-06-11 — 파생 피처 추적: handler 실행 전 원본 컬럼 캡처.
            # frontend G3 모달이 before/after 비교로 신규 컬럼·증가량 노출.
            _before_cols: list[str] = []
            try:
                _before_cols = [str(c) for c in df.columns]
                _safe_publish_stage_partial(
                    state.job_id,
                    {
                        "g3_phase": "feature_engineer_start",
                        "g3_status": f"피처 엔지니어링 진행 중 — 원본 {len(_before_cols)}개 컬럼에 변환 적용",
                        "fe_before_count": len(_before_cols),
                    },
                )
            except Exception as e:  # noqa: BLE001
                self.logger.debug("fe_before_capture_failed", error=str(e))

            # Day 11 (jh) — leakage-safe 진입점 우선 시도.
            # apply_split 이 등록돼 있으면 split-first → train fit → val transform
            # 흐름으로 fitted statistics 가 train 에만 갇히도록 강제.
            # 미등록이면 기존 apply 폴백 (회귀 방지).
            split_handler = get_handler(state.category, "apply_split")
            handler = get_handler(state.category, "apply")
            used_leakage_safe = False
            if split_handler is not None:
                try:
                    result = split_handler(df, state.preprocessing_plan or [], state)
                    if isinstance(result, tuple) and len(result) == 4:
                        # (df_train_proc, df_val_proc, df_test_proc, new_state)
                        import pandas as _pd  # noqa: WPS433

                        df_tr, df_val, df_test, state = result
                        n_tr = int(len(df_tr))
                        n_val = int(len(df_val))
                        n_test = int(len(df_test))
                        df = _pd.concat([df_tr, df_val, df_test], axis=0, ignore_index=True)
                        try:
                            extras = dict(state.category_extras or {})
                            cat_key = "tabular" if state.category.startswith("tabular") else state.category
                            cat_extras = dict(extras.get(cat_key, {}))
                            split_meta = dict(cat_extras.get("leakage_safe_split") or {})
                            split_meta["train_row_count_for_reorder"] = n_tr
                            split_meta["val_row_count"] = n_val
                            split_meta["test_row_count"] = n_test
                            cat_extras["leakage_safe_split"] = split_meta
                            extras[cat_key] = cat_extras
                            state = state.with_update(category_extras=extras)
                        except Exception:
                            pass
                        used_leakage_safe = True
                    elif isinstance(result, tuple) and len(result) == 3:
                        # (df_train_proc, df_val_proc, new_state) — 2분할 폴백
                        import pandas as _pd  # noqa: WPS433

                        df_tr, df_val, state = result
                        n_tr = int(len(df_tr))
                        n_val = int(len(df_val))
                        df = _pd.concat([df_tr, df_val], axis=0, ignore_index=True)
                        try:
                            extras = dict(state.category_extras or {})
                            cat_key = "tabular" if state.category.startswith("tabular") else state.category
                            cat_extras = dict(extras.get(cat_key, {}))
                            split_meta = dict(cat_extras.get("leakage_safe_split") or {})
                            split_meta["train_row_count_for_reorder"] = n_tr
                            # HJ 2026-06-15 — Fix 1: val_row_count 도 기록해야 _leakage_split_bounds 가
                            #   경계를 완성(둘 다 필요)한다. 누락 시 None → 무작위 재분할 누수 폴백.
                            split_meta["val_row_count"] = n_val
                            cat_extras["leakage_safe_split"] = split_meta
                            extras[cat_key] = cat_extras
                            state = state.with_update(category_extras=extras)
                        except Exception:
                            pass
                        used_leakage_safe = True
                    elif isinstance(result, tuple) and len(result) == 2:
                        df, state = result
                        used_leakage_safe = True
                    else:
                        df = result
                        used_leakage_safe = True
                except Exception as e:
                    self.logger.warning(
                        "feature_engineer_apply_split_failed_fallback_apply",
                        category=state.category,
                        error=str(e),
                    )
                    used_leakage_safe = False

            if not used_leakage_safe and handler is not None:
                # HJ 2026-06-15 — Fix 4: full apply()(전체 fit_transform=누수) 직전, 인라인 안전 분할
                #   폴백을 먼저 시도. 성공 시 누수 없이 진행, 실패(None)면 기존 full apply()로 폴백.
                _safe = _leakage_safe_fallback(df, state.preprocessing_plan or [], state)
                if _safe is not None:
                    df, state = _safe
                    used_leakage_safe = True
                    self.logger.info("feature_engineer_inline_safe_fallback_used", category=state.category)

            if not used_leakage_safe and handler is not None:
                try:
                    result = handler(df, state.preprocessing_plan or [], state)
                    if isinstance(result, tuple) and len(result) == 2:
                        df, state = result
                    else:
                        df = result
                except Exception as e:
                    self.logger.warning("feature_engineer_handler_failed", category=state.category, error=str(e))

            # 자동 피처선택 (P1-2) — tabular 무감독 안전 제거(상수·완전중복). 누수 0, graceful.
            if str(state.category).startswith("tabular"):
                _df_fs, _fs_meta = _auto_feature_select(df, state.target_column)
                if _fs_meta.get("applied") and _fs_meta.get("n_dropped"):
                    df = _df_fs
                    self.logger.info(
                        "auto_feature_select",
                        n_dropped=_fs_meta.get("n_dropped"),
                        n_const=_fs_meta.get("n_const"),
                        n_dup=_fs_meta.get("n_dup"),
                    )

            # HJ 2026-06-11 — handler 적용 후 신규 컬럼 추출 + plan step 명 한국어 매핑 → publish.
            # 사용자가 G3 모달에서 어떤 파생 피처가 어떻게 생성됐는지 라이브로 확인.
            try:
                _after_cols = [str(c) for c in df.columns]
                _before_set = set(_before_cols)
                _new_cols = [c for c in _after_cols if c not in _before_set]
                plan_raw = state.preprocessing_plan or []
                _step_names: list[str] = []
                for s in plan_raw:
                    if isinstance(s, dict):
                        nm = s.get("name") or s.get("op") or ""
                        if nm:
                            _step_names.append(_STEP_KO.get(str(nm), str(nm)))
                _safe_publish_stage_partial(
                    state.job_id,
                    {
                        "g3_phase": "feature_engineer_done",
                        "g3_status": (
                            f"피처 엔지니어링 완료 — 원본 {len(_before_cols)}개 → "
                            f"{len(_after_cols)}개 (신규 {len(_new_cols)}개)"
                        ),
                        "fe_before_count": len(_before_cols),
                        "fe_after_count": len(_after_cols),
                        "fe_new_columns": _new_cols[:30],
                        "fe_applied_steps": _step_names[:20],
                    },
                )
            except Exception as e:  # noqa: BLE001
                self.logger.warning("fe_partial_publish_failed", error=str(e))

            object_name = f"processed/{state.job_id}/{uuid.uuid4().hex}.parquet"
            get_minio_client().save_dataframe(df, object_name, fmt="parquet")
            new_state = state.with_update(preprocessed_data_id=object_name, next_agent="gate_model_strategy")

            # Phase 1.4 — ReportContext ④ features 적립.
            # 핸들러가 명시 created 리스트를 안 주므로 최종 컬럼 수만 적립.
            try:
                final_count = int(df.shape[1])
                schema_after = {str(c): str(df[c].dtype) for c in df.columns}
                new_state = self.contribute_to_context(
                    new_state,
                    "features",
                    {"final_feature_count": final_count},
                )
                # 전처리 schema_after 보강
                new_state = self.contribute_to_context(
                    new_state,
                    "preprocessing",
                    {"schema_after": schema_after},
                )
            except Exception as e:
                self.logger.warning("contribute_features_failed", error=str(e))
            return new_state
