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
from ada.core.state import CATEGORIES, PipelineState
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

            # ── 게이트 주도 설계: category 미지정 시 데이터 기반 자동 탐지 ──
            #   사용자는 탭1에서 category/target 을 입력하지 않음 → 여기서 추정하고
            #   G1 게이트에서 사용자가 확인/override 한다.
            category = state.category
            target_column = state.target_column
            detection: dict[str, Any] = {}
            if (not category) or category in ("pending", "auto") or category not in CATEGORIES:
                try:
                    generic = basic_dataframe_profile(df, target_column=None)
                    category, target_column, detection = _detect_category(
                        generic, state.user_intent or state.user_question or ""
                    )
                except Exception as e:  # noqa: BLE001
                    self.logger.warning("category_detection_failed", error=str(e))
                    category, target_column = "tabular_ml", None
                # 최후 방어 — schema_validator 가 'pending'/무효 category 로 죽지 않도록 보장
                if category not in CATEGORIES:
                    category = "tabular_ml"
                await self._persist_detection(state, category, target_column)

            # 감지된 target 반영해 프로파일 산출 (schema_validator 의 has_target 검증용)
            profile = basic_dataframe_profile(df, target_column=target_column)
            if detection:
                profile["category_detection"] = detection
                if detection.get("date_col"):
                    profile.setdefault("date_col", detection["date_col"])

            handler = get_handler(category, "profile")
            if handler is not None:
                try:
                    extra = handler(df, state.with_update(category=category, target_column=target_column))
                    if isinstance(extra, dict):
                        profile.update(extra)
                except Exception as e:
                    self.logger.warning("profiler_handler_failed", category=category, error=str(e))

            merged_extras = _merge_pii_extras(state.category_extras, pii_extras)
            return state.with_update(
                category=category,
                target_column=target_column,
                data_profile=profile,
                category_extras=merged_extras,
                next_agent="schema_validator",
            )

    async def _persist_detection(self, state: PipelineState, category: str, target_column: Any) -> None:
        """감지된 category/target 을 Job 행에 반영 (distiller·상태조회 일관성). best-effort."""
        if self.session is None:
            return
        try:
            import uuid as _uuid

            from ada.db.models import Job

            jid = _uuid.UUID(state.job_id) if isinstance(state.job_id, str) else state.job_id
            job = await self.session.get(Job, jid)
            if job is not None:
                job.category = category
                if target_column:
                    job.target_column = target_column
                await self.session.flush()
        except Exception as e:  # noqa: BLE001
            self.logger.warning("persist_detection_failed", error=str(e))


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


# ==============================================================
# 게이트 주도 — category/target 자동 탐지 (G1 제안용)
# ==============================================================

_TARGET_NAME_HINTS = (
    "target",
    "label",
    "class",
    "outcome",
    "result",
    "survived",
    "churn",
    "default",
    "fraud",
    "price",
    "sales",
    "정답",
    "타깃",
    "레이블",
    "라벨",
    "결과",
    "종속",
)
_DATE_NAME_HINTS = ("date", "time", "timestamp", "datetime", "날짜", "일자", "시간", "period", "ds")
_TS_INTENT = ("시계열", "예측", "forecast", "time series", "timeseries", "추세", "계절", "미래", "향후")
_ANOM_INTENT = ("이상", "anomaly", "outlier", "비정상", "fraud", "사기", "결함", "불량")


def _detect_category(profile: dict[str, Any], intent: str) -> tuple[str, Any, dict[str, Any]]:
    """범용 프로파일 + 의도로 4 카테고리 중 하나와 target 후보를 추정.

    완벽할 필요 없음 — G1 게이트에서 사용자가 확인/override 한다.
    반환: (category, target_column|None, detection_info)
    """
    cols = [str(c) for c in (profile.get("columns") or [])]
    dtypes = {str(k): str(v).lower() for k, v in (profile.get("dtypes") or {}).items()}
    low = (intent or "").lower()

    # 날짜 컬럼 (dtype → 이름)
    date_col = next((c for c in cols if "datetime" in dtypes.get(c, "")), None)
    if date_col is None:
        date_col = next((c for c in cols if any(h in c.lower() for h in _DATE_NAME_HINTS)), None)

    # 타깃 후보 (이름 힌트 → 마지막 컬럼 관례)
    target = next((c for c in cols if any(h in c.lower() for h in _TARGET_NAME_HINTS)), None)
    if target is None and cols and cols[-1] != date_col:
        target = cols[-1]

    numeric_cols = [c for c in cols if any(t in dtypes.get(c, "") for t in ("int", "float")) and c != date_col]
    ts_kw = any(k in low for k in _TS_INTENT)
    anom_kw = any(k in low for k in _ANOM_INTENT)

    if anom_kw:
        category, target = "anomaly_detection", None
    elif date_col and (ts_kw or len(cols) <= 3):
        category = "timeseries"
        if not (target and target in numeric_cols and target != date_col):
            target = numeric_cols[0] if numeric_cols else None
    elif target is not None:
        category = "tabular_ml"
    elif date_col:
        category = "timeseries"
        target = numeric_cols[0] if numeric_cols else None
    else:
        category, target = "anomaly_detection", None

    return (
        category,
        target,
        {
            "detected_category": category,
            "detected_target": target,
            "date_col": date_col,
            "signals": {"has_date": bool(date_col), "ts_keyword": ts_kw, "anomaly_keyword": anom_kw},
            "note": "G1 게이트에서 사용자 확인/override 가능",
        },
    )
