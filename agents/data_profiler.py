"""agents.data_profiler -- DataProfilerAgent (Day 0 dispatcher pattern).

- File loading / statistics profile : library (pandas/numpy)
- PII detection                      : LLM  / masking : library (PIIAnonymizer)
- Category / target detection        : LLM
- Domain analysis                    : LLM  (컬럼 의미·도메인·데이터셋 요약)

수정 권한: HJ 단독 (dispatcher).
"""

from __future__ import annotations

import json as _json
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

_PII_SYSTEM_PROMPT = (
    "You are a data privacy expert. "
    "Identify which columns likely contain PII (names, emails, phone numbers, "
    "addresses, ID numbers, SSNs, etc.). "
    "Return ONLY a JSON array of column name strings. "
    'Example: ["full_name", "email"] -- return [] if none.'
)

_CATEGORY_SYSTEM_PROMPT = (
    "You are a data science expert. Classify this dataset into exactly one of:\n"
    '- "tabular_ml"        : structured tabular data for ML classification or regression\n'
    '- "tabular_dl"        : structured tabular data requiring deep learning\n'
    '- "timeseries"        : data with a time/date dimension for forecasting\n'
    '- "anomaly_detection" : data for detecting outliers or anomalies\n\n'
    "Also identify the most likely target column to predict. "
    "For anomaly_detection set target_column to null.\n\n"
    "Return ONLY JSON (no markdown):\n"
    '{"category": "tabular_ml", "target_column": "price", "reason": "brief"}'
)

_DOMAIN_SYSTEM_PROMPT = (
    "You are an expert data analyst. "
    "Given column names, data types, and sample rows from a dataset, analyze:\n"
    "1. Which domain/industry this dataset belongs to (e.g. e-commerce, healthcare, finance, logistics, etc.)\n"
    "2. What each column means in plain language\n"
    "3. A 1-2 sentence Korean summary of what this dataset is about\n"
    "4. Whether a clear prediction target exists, and why\n\n"
    "Return ONLY JSON (no markdown), all text values in Korean:\n"
    '{"domain": "e-commerce", '
    '"dataset_summary": "이 데이터셋은 ...", '
    '"column_meanings": {"col_name": "의미 설명", ...}, '
    '"target_insight": "Survived 컬럼은 이진 분류의 타겟으로 적합합니다."}'
)


class DataProfilerAgent(BaseAgent):
    """4-category common dispatcher."""

    uses_llm = True
    model_name = "claude-sonnet-4-6"

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            # ① File loading -- library
            try:
                df = load_dataframe_from_state(state)
            except Exception as e:
                return state.with_update(
                    error=f"file load failed: {e}",
                    validation={"is_valid": False, "errors": [str(e)], "warnings": []},
                    next_agent="error_recovery",
                )

            # ② PII detection -- LLM  /  masking -- library
            df, pii_extras = await self._llm_anonymize_df(df)

            # ③ Category / target detection -- LLM (only when unspecified)
            category = state.category
            target_column = state.target_column
            detection: dict[str, Any] = {}
            if (not category) or category in ("pending", "auto") or category not in CATEGORIES:
                try:
                    generic = basic_dataframe_profile(df, target_column=None)
                    category, target_column, detection = await self._llm_detect_category(
                        generic, df, state.user_intent or state.user_question or ""
                    )
                except Exception as e:
                    self.logger.warning("llm_category_detection_failed", error=str(e))
                    category, target_column = "tabular_ml", None
                if category not in CATEGORIES:
                    category = "tabular_ml"
                await self._persist_detection(state, category, target_column)

            # ③.5 Domain analysis -- LLM (컬럼 의미·도메인·데이터셋 요약)
            domain_analysis: dict[str, Any] = {}
            try:
                domain_analysis = await self._llm_domain_analysis(
                    df, category, target_column, state.user_intent or state.user_question or ""
                )
            except Exception as e:
                self.logger.warning("llm_domain_analysis_failed", error=str(e))

            # ④ Full statistics profile -- library
            profile = basic_dataframe_profile(df, target_column=target_column)
            if detection:
                profile["category_detection"] = detection
            if domain_analysis:
                profile["domain_analysis"] = domain_analysis

            # ⑤ Category-specific handler -- library (best-effort)
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

    # ------------------------------------------------------------------
    # LLM helpers
    # ------------------------------------------------------------------

    async def _llm_detect_pii(self, df: Any) -> list[str]:
        """LLM-based PII column detection. Returns [] on failure."""
        cols = list(map(str, df.columns))
        try:
            sample = df.head(3).fillna("").astype(str).to_dict(orient="records")
        except Exception:
            sample = []
        user_prompt = (
            f"Column names: {cols}\nSample data (first 3 rows): {_json.dumps(sample, ensure_ascii=False)[:2000]}"
        )
        raw = await self._call_llm(
            system_prompt=_PII_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=300,
            temperature=0.0,
            json_mode=True,
        )
        result = self._parse_json(raw)
        if isinstance(result, list):
            pii_cols = result
        elif isinstance(result, dict):
            pii_cols = result.get("pii_columns", [])
        else:
            pii_cols = []
        return [c for c in pii_cols if c in df.columns]

    async def _llm_anonymize_df(self, df: Any) -> tuple[Any, dict[str, Any]]:
        """PII detection via LLM, masking via library. Returns original df on failure."""
        try:
            pii_cols = await self._llm_detect_pii(df)
            if not pii_cols:
                return df, {}
            from ada.security.guardrails import PIIAnonymizer

            anon = PIIAnonymizer()
            masked_df, mapping = anon.anonymize_df(df, pii_columns=pii_cols)
            return masked_df, {"mapping": mapping, "columns": pii_cols}
        except Exception as e:
            self.logger.warning("llm_pii_anonymize_fallback", error=str(e))
            return df, {}

    async def _llm_domain_analysis(self, df: Any, category: str, target_column: Any, intent: str) -> dict[str, Any]:
        """LLM-based domain understanding: 컬럼 의미·도메인·데이터셋 요약."""
        try:
            sample = df.head(5).fillna("").astype(str).to_dict(orient="records")
        except Exception:
            sample = []
        cols = list(map(str, df.columns))
        try:
            dtypes = {c: str(t) for c, t in df.dtypes.items()}
        except Exception:
            dtypes = {}
        user_prompt = (
            f"columns: {cols}\n"
            f"dtypes: {_json.dumps(dtypes, ensure_ascii=False)}\n"
            f"sample_rows (first 5): {_json.dumps(sample, ensure_ascii=False)[:3000]}\n"
            f"detected_category: {category}\n"
            f"detected_target: {target_column or 'none'}\n"
            f"user_intent: {intent or 'none'}"
        )
        raw = await self._call_llm(
            system_prompt=_DOMAIN_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=800,
            temperature=0.2,
            json_mode=True,
        )
        parsed = self._parse_json(raw)
        if not isinstance(parsed, dict):
            return {}
        return {
            "domain": parsed.get("domain", ""),
            "dataset_summary": parsed.get("dataset_summary", ""),
            "column_meanings": parsed.get("column_meanings", {}),
            "target_insight": parsed.get("target_insight", ""),
        }

    async def _llm_detect_category(
        self, profile: dict[str, Any], df: Any, intent: str
    ) -> tuple[str, Any, dict[str, Any]]:
        """LLM-based category / target detection."""
        try:
            sample = df.head(3).fillna("").astype(str).to_dict(orient="records")
        except Exception:
            sample = []
        user_prompt = (
            f"columns: {profile.get('columns', [])}\n"
            f"dtypes: {_json.dumps(profile.get('dtypes', {}), ensure_ascii=False)}\n"
            f"sample_rows: {_json.dumps(sample, ensure_ascii=False)[:2000]}\n"
            f"user_intent: {intent or 'none'}"
        )
        raw = await self._call_llm(
            system_prompt=_CATEGORY_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=300,
            temperature=0.0,
            json_mode=True,
        )
        parsed = self._parse_json(raw)
        category = parsed.get("category", "tabular_ml")
        target_column = parsed.get("target_column") or None
        reason = parsed.get("reason", "")
        detection = {
            "detected_category": category,
            "detected_target": target_column,
            "reason": reason,
            "signals": {"llm_inferred": True},
        }
        return category, target_column, detection

    # ------------------------------------------------------------------

    async def _persist_detection(self, state: PipelineState, category: str, target_column: Any) -> None:
        """Persist detected category/target to Job row. best-effort."""
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
        except Exception as e:
            self.logger.warning("persist_detection_failed", error=str(e))


# ==============================================================
# Module-level helpers
# ==============================================================


def _anonymize_uploaded_df(df: Any, state: Any) -> tuple[Any, dict[str, Any]]:
    """동기 PII 익명화 래퍼 — 테스트 및 레거시 호출용.

    컬럼명 휴리스틱으로 PII 컬럼을 탐지(LLM 없음)하여 동기 환경에서도 동작한다.
    """
    import re

    _PII_PAT = re.compile(
        r"(email|phone|tel|mobile|ssn|주민|이메일|전화|핸드폰)",
        re.IGNORECASE,
    )
    pii_cols = [c for c in df.columns if _PII_PAT.search(str(c))]
    if not pii_cols:
        return df, {}
    try:
        from ada.security.guardrails import PIIAnonymizer  # noqa: WPS433

        anon = PIIAnonymizer()
        masked_df, mapping = anon.anonymize_df(df, pii_columns=pii_cols)
        return masked_df, {"mapping": mapping, "columns": pii_cols}
    except Exception:  # noqa: BLE001
        return df, {}


def _merge_pii_extras(current_extras: dict[str, Any] | None, new_pii: dict[str, Any]) -> dict[str, Any]:
    """Merge new PII mapping/columns into state.category_extras."""
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
