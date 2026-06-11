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
                    if isinstance(result, tuple) and len(result) == 3:
                        # (df_train_proc, df_val_proc, new_state) 시그니처
                        import pandas as _pd  # noqa: WPS433

                        df_tr, df_val, state = result
                        n_tr = int(len(df_tr))
                        df = _pd.concat([df_tr, df_val], axis=0, ignore_index=True)
                        # train 인덱스를 state extras 에 기록 → training_executor 가 동일 split 재현
                        try:
                            extras = dict(state.category_extras or {})
                            cat_key = "tabular" if state.category.startswith("tabular") else state.category
                            cat_extras = dict(extras.get(cat_key, {}))
                            split_meta = dict(cat_extras.get("leakage_safe_split") or {})
                            split_meta["train_row_count_for_reorder"] = n_tr
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
                try:
                    result = handler(df, state.preprocessing_plan or [], state)
                    if isinstance(result, tuple) and len(result) == 2:
                        df, state = result
                    else:
                        df = result
                except Exception as e:
                    self.logger.warning("feature_engineer_handler_failed", category=state.category, error=str(e))

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
