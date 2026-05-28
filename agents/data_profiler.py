"""agents.data_profiler — DataProfilerAgent (Day 0 dispatcher 패턴).

ADR-008 L3.3: 업로드 df 의 PII 컬럼 자동 마스킹 + state.category_extras['_pii']
mapping merge. 핸들러는 마스킹된 df 받음.

수정 권한: HJ 단독 (dispatcher).
"""

from __future__ import annotations

from typing import Any

import agents.handlers.anomaly  # noqa: F401
import agents.handlers.tabular  # noqa: F401
import agents.handlers.timeseries  # noqa: F401
from ada.core.state import PipelineState
from agents.base import BaseAgent
from agents.handlers import get_handler
from agents.handlers.common.shared import (
    basic_dataframe_profile,
    load_dataframe_from_state,
)


class DataProfilerAgent(BaseAgent):
    """4 카테고리 공통 dispatcher."""

    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            try:
                df = load_dataframe_from_state(state)
            except Exception as e:
                return state.with_update(
                    error=f"파일 로딩 실패: {e}",
                    validation={"is_valid": False, "errors": [str(e)], "warnings": []},
                    next_agent="error_recovery",
                )

            # ADR-008 L3.3 — 업로드 df 의 PII 컬럼 자동 마스킹
            df, pii_extras = _anonymize_uploaded_df(df, state)

            profile = basic_dataframe_profile(df, target_column=state.target_column)

            handler = get_handler(state.category, "profile")
            if handler is not None:
                try:
                    extra = handler(df, state)
                    if isinstance(extra, dict):
                        profile.update(extra)
                except Exception as e:
                    self.logger.warning("profiler_handler_failed", category=state.category, error=str(e))

            merged_extras = _merge_pii_extras(state.category_extras, pii_extras)
            return state.with_update(
                data_profile=profile,
                category_extras=merged_extras,
                next_agent="schema_validator",
            )


# ==============================================================
# ADR-008 L3.3 — 헬퍼 (모듈 레벨, 테스트 용이)
# ==============================================================


def _anonymize_uploaded_df(df: Any, state: PipelineState) -> tuple[Any, dict[str, Any]]:
    """업로드 df 의 PII 컬럼 자동 마스킹.

    Returns:
        (마스킹된 df, extras={"mapping": {...}, "columns": [...]})
    """
    try:
        from ada.security.guardrails import PIIAnonymizer
    except Exception:
        return df, {}
    try:
        anon = PIIAnonymizer()
        cols = anon.detect_pii_columns(df)
        if not cols:
            return df, {}
        masked_df, mapping = anon.anonymize_df(df, pii_columns=cols)
        return masked_df, {"mapping": mapping, "columns": cols}
    except Exception:
        return df, {}


def _merge_pii_extras(current_extras: dict[str, Any] | None, new_pii: dict[str, Any]) -> dict[str, Any]:
    """state.category_extras 에 새 PII mapping/columns 를 merge.

    기존 _pii (텍스트 mapping) 보존 + df mapping 추가 + df_columns 노출.
    """
    extras = dict(current_extras or {})
    if not new_pii:
        return extras
    existing = extras.get("_pii") or {}
    merged_mapping = {**(existing.get("mapping") or {}), **(new_pii.get("mapping") or {})}
    extras["_pii"] = {
        **existing,
        "mapping": merged_mapping,
        "df_columns": new_pii.get("columns") or [],
        "redaction": existing.get("redaction") or "***",
    }
    return extras
