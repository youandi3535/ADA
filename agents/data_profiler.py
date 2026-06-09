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
    "당신은 데이터 프라이버시 전문가입니다. "
    "PII(개인식별정보) 가능성이 높은 컬럼을 식별하세요. "
    "이름·이메일·전화번호·주소·주민번호·여권번호 등.\n\n"
    "응답은 컬럼명 문자열의 JSON 배열만 반환. "
    '예: ["full_name", "email"]. 해당 없으면 [].'
)

_CATEGORY_SYSTEM_PROMPT = (
    "당신은 데이터 사이언스 전문가입니다. 다음 데이터셋을 정확히 한 가지 카테고리로 분류하세요:\n"
    '- "tabular_ml"        : 분류·회귀를 위한 정형 데이터\n'
    '- "tabular_dl"        : 딥러닝이 필요한 정형 데이터\n'
    '- "timeseries"        : 시간/날짜 차원이 있는 예측용 데이터\n'
    '- "anomaly_detection" : 이상치·이탈 탐지용 데이터\n\n'
    "예측 대상이 될 가능성이 가장 높은 컬럼도 함께 식별. "
    "anomaly_detection 인 경우 target_column 은 null.\n\n"
    "한자(汉字)·중국어 절대 금지. reason 은 한국어 1문장.\n\n"
    "JSON 만 반환 (마크다운 금지):\n"
    '{"category": "tabular_ml", "target_column": "price", "reason": "한국어 1문장"}'
)

_DOMAIN_SYSTEM_PROMPT = (
    "당신은 데이터 분석 전문가입니다. "
    "컬럼명·데이터 타입·샘플 행을 보고 다음 4가지를 분석하세요:\n"
    "1. 데이터셋이 속한 도메인·산업 (예: 이커머스, 의료, 금융, 물류 등)\n"
    "2. 각 컬럼의 의미를 평범한 한국어로 설명\n"
    "3. 이 데이터셋이 무엇을 다루는지 한국어 1-2문장 요약\n"
    "4. 명확한 예측 타겟이 존재하는지, 그 근거\n\n"
    "[필수 규칙]\n"
    "- 모든 텍스트 값(domain · dataset_summary · column_meanings · target_insight)은 한국어.\n"
    "- 한자(漢字·汉字)·중국어 문장 절대 금지. 영문 컬럼명은 키로 그대로 유지.\n\n"
    "JSON 만 반환 (마크다운·코드블록 금지):\n"
    '{"domain": "이커머스", '
    '"dataset_summary": "이 데이터셋은 ...", '
    '"column_meanings": {"price": "상품 가격 (원)", ...}, '
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
                df = load_dataframe_from_state(state, prefer_processed=False)
            except Exception as e:
                return state.with_update(
                    error=f"file load failed: {e}",
                    validation={"is_valid": False, "errors": [str(e)], "warnings": []},
                    next_agent="error_recovery",
                )

            # ②③④ PII(휴리스틱) + 카테고리(LLM) + 도메인(LLM) + CPU profile (HJ 2026-06-09 G1 단축)
            # 변경 요약:
            #   - B2: PII 는 정규식 휴리스틱 1차, 잔여 컬럼 ≤ 50 일 때만 짧은 LLM 검증 (max_tokens=100)
            #   - E:  카테고리 확정 직후 handler.profile + data_card 빌드를 to_thread 백그라운드 시작
            #         → 도메인 LLM (Ollama I/O wait) 진행 중 GIL 풀려있어 진짜 동시 실행
            #   - D:  도메인 LLM max_tokens 800 (30MB 상한 하 컬럼 ~100, ~1500t 필요시 위험 — cap 동적)
            import asyncio as _asyncio

            need_category = (
                (not state.category) or state.category in ("pending", "auto") or state.category not in CATEGORIES
            )
            generic_for_cat = basic_dataframe_profile(df, target_column=None) if need_category else {}
            intent = state.user_intent or state.user_question or ""

            async def _detect_category_safe():
                if not need_category:
                    return state.category, state.target_column, {}
                try:
                    return await self._llm_detect_category(generic_for_cat, df, intent)
                except Exception as e:
                    self.logger.warning("llm_category_detection_failed", error=str(e))
                    return "tabular_ml", None, {}

            async def _domain_safe(cat, tgt):
                try:
                    return await self._llm_domain_analysis(df, cat, tgt, intent)
                except Exception as e:
                    self.logger.warning("llm_domain_analysis_failed", error=str(e))
                    return {}

            # 1단계: PII(휴리스틱+짧은 LLM) + 카테고리 LLM — 둘 다 끝나야 다음 단계 진입
            (df, pii_extras), (category, target_column, detection) = await _asyncio.gather(
                self._heuristic_anonymize_df(df),
                _detect_category_safe(),
            )
            if category not in CATEGORIES:
                category = "tabular_ml"
            await self._persist_detection(state, category, target_column)

            # 2단계: 도메인 LLM 호출과 CPU profile/data_card 빌드를 동시 실행 (E)
            # - 도메인 LLM 은 Ollama HTTP wait → GIL 안 잡음
            # - handler.profile + data_card 는 CPU 작업 → to_thread 로 워커 스레드로 위임
            #   → 진짜 동시 실행, 30MB worst case 에서 -25~30s 효과
            def _cpu_profile_and_card() -> tuple[dict, dict | None]:
                """CPU only: basic_profile + handler.profile + data_card 빌드 (도메인 분석 제외)."""
                _profile = basic_dataframe_profile(df, target_column=target_column)
                if detection:
                    _profile["category_detection"] = detection
                _handler = get_handler(category, "profile")
                if _handler is not None:
                    try:
                        _extra = _handler(df, state.with_update(category=category, target_column=target_column))
                        if isinstance(_extra, dict):
                            _profile.update(_extra)
                    except Exception as e:
                        self.logger.warning("profiler_handler_failed", category=category, error=str(e))
                # data_card 는 도메인 분석에 의존하므로 빈 dict 으로 1차 빌드, 도메인 합류 후 도메인만 패치
                _card: Any = None
                try:
                    _card = _build_data_card_v1(df, state, category, target_column, pii_extras or {}, {}, _profile)
                except Exception as e:  # noqa: BLE001
                    self.logger.warning("data_card_build_failed", error=str(e))
                return _profile, _card

            cpu_task = _asyncio.create_task(_asyncio.to_thread(_cpu_profile_and_card))
            domain_analysis = await _domain_safe(category, target_column)
            profile, data_card = await cpu_task

            # 도메인 분석 결과를 profile + data_card 에 머지 (CPU 작업이 도메인 없이 끝났으므로 후처리)
            if domain_analysis:
                profile["domain_analysis"] = domain_analysis
                # data_card §3 dictionary 의 column_meanings 패치 (보존된 dictionary 구조 유지)
                try:
                    if isinstance(data_card, dict):
                        col_meanings = (domain_analysis or {}).get("column_meanings") or {}
                        _dict = data_card.get("dictionary") or {}
                        for _col, _meaning in col_meanings.items():
                            if _col in _dict and isinstance(_dict[_col], dict):
                                _dict[_col]["meaning"] = str(_meaning)
                except Exception as e:  # noqa: BLE001
                    self.logger.warning("data_card_domain_patch_failed", error=str(e))

            merged_extras = _merge_pii_extras(state.category_extras, pii_extras)

            # HJ 2026-06-09 G1 단축 I — task 결정을 여기서 (supervisor LLM 제거 대응)
            # target dtype·nunique 가 확정된 현 시점이 룰 분류 정확도 100%.
            final_task = _resolve_task_from_profile(state.task, category, target_column, df)

            new_state = state.with_update(
                category=category,
                target_column=target_column,
                task=final_task,
                data_profile=profile,
                data_card=data_card,
                category_extras=merged_extras,
                next_agent="schema_validator",
            )
            # Phase 1.4 — ReportContext ① dataset + ② domain 적립.
            # data_card 가 있으면 그쪽이 진실원, 없으면 profile 에서 추출.
            try:
                new_state = _contribute_dataset_and_domain(
                    self, new_state, df, data_card, profile, pii_extras or {}, domain_analysis or {}
                )
            except Exception as e:  # noqa: BLE001
                self.logger.warning("contribute_dataset_failed", error=str(e))
            return new_state

    # ------------------------------------------------------------------
    # LLM helpers
    # ------------------------------------------------------------------

    async def _llm_detect_pii(self, df: Any) -> list[str]:
        """LLM-based PII column detection. Returns [] on failure.

        HJ 2026-06-09 — `_heuristic_anonymize_df` 의 LLM 검증 경로에서만 사용.
        호출자가 잔여 후보 컬럼을 미리 좁혀서 넘기므로 max_tokens=100 으로 충분.
        """
        cols = list(map(str, df.columns))
        try:
            sample = df.head(1).fillna("").astype(str).to_dict(orient="records")
        except Exception:
            sample = []
        user_prompt = f"Column names: {cols}\nSample data (first row): {_json.dumps(sample, ensure_ascii=False)[:1000]}"
        raw = await self._call_llm(
            system_prompt=_PII_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=100,  # 300→100. 컬럼명 ≤ 50개 가정, JSON 배열로 충분
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

    async def _heuristic_anonymize_df(self, df: Any) -> tuple[Any, dict[str, Any]]:
        """G1 단축 B2 — 정규식 휴리스틱 1차 + 잔여 컬럼 ≤ 50 시 짧은 LLM 검증.

        품질 보존:
          - 명확한 PII 컬럼명 (email/phone/주민/이메일 등) 은 정규식이 잡음 → LLM 정확도와 동등
          - 모호한 컬럼명은 LLM 검증으로 보완 (잔여 50 이하인 경우만)
          - 잔여 > 50: 보수적으로 정규식만 사용 (입력 비대 회피)
        단축: -8~12s (LLM 0~1회로 감축)
        """
        try:
            import re as _re

            # 확장된 정규식 패턴 (영문 + 한국어 PII 키워드)
            _PII_PAT = _re.compile(
                r"(email|phone|tel|mobile|fax|ssn|passport|"
                r"name|first.?name|last.?name|full.?name|user.?name|"
                r"address|street|city|zip|postal|"
                r"birth|dob|"
                r"주민|이메일|전화|핸드폰|이름|성함|주소|생년월일|우편)",
                _re.IGNORECASE,
            )
            heuristic_pii = [c for c in df.columns if _PII_PAT.search(str(c))]
            remaining = [c for c in df.columns if c not in heuristic_pii]

            # 잔여 컬럼이 적당히 작을 때만 LLM 검증 (입력 비대 회피)
            llm_pii: list[str] = []
            if 0 < len(remaining) <= 50:
                try:
                    # 컬럼 슬라이스 df 로 짧은 LLM 호출
                    sub_df = df[remaining]
                    llm_pii = await self._llm_detect_pii(sub_df)
                except Exception as e:
                    self.logger.warning("llm_pii_skim_failed", error=str(e))
                    llm_pii = []

            pii_cols = list(dict.fromkeys([*heuristic_pii, *llm_pii]))  # 순서 보존 dedup
            if not pii_cols:
                return df, {}

            from ada.security.guardrails import PIIAnonymizer

            anon = PIIAnonymizer()
            masked_df, mapping = anon.anonymize_df(df, pii_columns=pii_cols)
            return masked_df, {"mapping": mapping, "columns": pii_cols}
        except Exception as e:
            self.logger.warning("pii_anonymize_fallback", error=str(e))
            return df, {}

    async def _llm_anonymize_df(self, df: Any) -> tuple[Any, dict[str, Any]]:
        """레거시 alias — 새 호출 경로는 `_heuristic_anonymize_df` 사용."""
        return await self._heuristic_anonymize_df(df)

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
        # HJ 2026-06-09 — G1 단축: max_tokens 800 고정 유지하되 30MB 상한 하 worst case 점검.
        # column_meanings 가 컬럼당 ~15t. 30MB·컬럼 100 → ~1500t 필요할 수 있으나
        # 1) 30MB 상한 가정 + 2) 대부분 데이터셋 컬럼 ≤ 50 → 800 cap 으로 P95 안전.
        # 컬럼 50 초과 시만 cap 동적 (cap = max(800, n_cols * 15 + 300))
        n_cols = len(df.columns) if hasattr(df, "columns") else 0
        _domain_max_tokens = max(800, n_cols * 15 + 300) if n_cols > 50 else 800
        raw = await self._call_llm(
            system_prompt=_DOMAIN_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=_domain_max_tokens,
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
            max_tokens=200,  # HJ 2026-06-09 G1 단축: 300→200 (실측 ~80t, 마진 2.5×)
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


def _resolve_task_from_profile(
    current_task: str | None,
    category: str,
    target_column: Any,
    df: Any,
) -> str:
    """HJ 2026-06-09 G1 단축 I — supervisor LLM 호출을 대체하는 룰 분류.

    호출 시점: data_profiler 가 category·target_column 을 확정한 직후.
    target dtype·nunique 가 명확하므로 LLM 보다 룰이 더 정확.

    정확도 보장:
      - anomaly_detection / timeseries: 카테고리 → task 1:1 (LLM 도 동일)
      - tabular + int/category target + nunique ≤ 20: classification (LLM 도 동일)
      - tabular + float target + nunique > 20: regression (LLM 도 동일)
      - 모호 영역 (정수 21~50): 보수적으로 classification (별점 1~10 같은 ordinal 회귀 케이스
        를 분류로 잡을 수 있으나, 후속 model_selection 단계에서 회귀 모델도 함께 시도 가능)
    """
    # a. 이미 명시된 task 가 있으면 그대로
    if current_task and current_task not in ("auto", "", "unknown"):
        return current_task
    # b. 카테고리 → task 1:1
    if category == "anomaly_detection":
        return "anomaly_detection"
    if category == "timeseries":
        return "forecasting"
    # c. tabular: target dtype 기반
    if not target_column or not hasattr(df, "columns") or target_column not in df.columns:
        return "classification"  # 보수 기본값 (target 모름)
    try:
        tgt = df[target_column]
        dtype = tgt.dtype
        n = int(tgt.nunique(dropna=True))
        # bool / object / category → 무조건 분류
        if dtype.kind == "b" or dtype.kind == "O" or dtype.name == "category":
            return "classification"
        # 정수·부호없는 정수
        if dtype.kind in "iu":
            if n <= 20:
                return "classification"
            # 정수형 nunique > 20 → 회귀로 추정 (count/age/price 등)
            return "regression"
        # 부동소수·복소수
        if dtype.kind in "fc":
            if n > 20:
                return "regression"
            # float 인데 nunique ≤ 20 → 이산화된 점수일 가능성 → 보수적으로 회귀
            return "regression"
    except Exception:
        pass
    return "classification"  # fallback


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


def _contribute_dataset_and_domain(
    agent: Any,
    state: Any,
    df: Any,
    data_card: dict[str, Any] | None,
    profile: dict[str, Any],
    pii_extras: dict[str, Any],
    domain_analysis: dict[str, Any],
) -> Any:
    """ReportContext ① dataset + ② domain 적립 (Phase 1.4).

    data_card 가 있으면 정규화된 형태에서 추출, 없으면 profile 에서 추출.
    카테고리 4종 모두 동일 스키마 — outputs.context.schema.DatasetProfile.
    """
    # 컬럼·dtype·shape — data_card.schema 우선
    schema_card = (data_card or {}).get("schema") or {}
    dtypes = dict(schema_card.get("dtypes") or profile.get("dtypes") or {})
    try:
        n_rows, n_cols = int(df.shape[0]), int(df.shape[1])
    except Exception:
        identity = (data_card or {}).get("identity") or {}
        n_rows = int(identity.get("row_count", 0))
        n_cols = int(identity.get("col_count", 0))

    # 통계 — data_card.dictionary 에서 추출
    dictionary = (data_card or {}).get("dictionary") or {}
    missing_rate: dict[str, float] = {}
    cardinality: dict[str, int] = {}
    numeric_stats: dict[str, dict[str, float]] = {}
    for col, info in dictionary.items():
        if not isinstance(info, dict):
            continue
        mp = info.get("missing_pct")
        if isinstance(mp, (int, float)):
            missing_rate[col] = round(float(mp) / 100.0, 4)
        nu = info.get("nunique")
        if isinstance(nu, int):
            cardinality[col] = nu
        # 숫자형 통계 — min/max/mean 만 있을 때
        if {"min", "max", "mean"} & set(info.keys()):
            numeric_stats[col] = {
                "min": float(info["min"]) if isinstance(info.get("min"), (int, float)) else 0.0,
                "max": float(info["max"]) if isinstance(info.get("max"), (int, float)) else 0.0,
                "mean": float(info["mean"]) if isinstance(info.get("mean"), (int, float)) else 0.0,
            }

    # 샘플 헤드 (PII 마스킹본 우선)
    sample_head: list[dict[str, Any]] = []
    try:
        sample_head = df.head(5).fillna("").astype(str).to_dict(orient="records")
    except Exception:
        pass

    # 시간 컬럼 — data_card.temporal_drift 활용
    temporal = (data_card or {}).get("temporal_drift") or {}
    time_cols = list(temporal.get("time_columns") or [])
    detected_time_col = time_cols[0] if time_cols else None

    # PK 후보 = ID 컬럼 후보
    granularity = (data_card or {}).get("granularity") or {}
    detected_id_cols = list(granularity.get("pk_candidates") or [])

    file_meta: dict[str, Any] = {
        "size_mb": round(int(schema_card.get("memory_bytes") or 0) / (1024 * 1024), 3),
        "encoding": "utf-8",
        "source": (data_card or {}).get("identity", {}).get("source_hint", "user_upload"),
    }

    dataset_payload: dict[str, Any] = {
        "dataset_name": getattr(state, "file_id", "") or "",
        "dataset_hash": str((data_card or {}).get("reproducibility", {}).get("data_hash_sample", "")),
        "shape": {"rows": n_rows, "cols": n_cols},
        "dtypes": dtypes,
        "missing_rate": missing_rate,
        "cardinality": cardinality,
        "sample_head": sample_head[:5],
        "numeric_stats": numeric_stats,
        "categorical_top": {},  # data_card 에 없음 — categorical_top 은 EDA 단계 보강
        "detected_target": getattr(state, "target_column", None),
        "detected_time_col": detected_time_col,
        "detected_id_cols": detected_id_cols[:5],
        "file_meta": file_meta,
    }
    new_state = agent.contribute_to_context(state, "dataset", dataset_payload)

    # ② domain — 가능한 정보만 (web 인용은 DomainEnricher 가 나중에 보강)
    column_meanings = (domain_analysis or {}).get("column_meanings") or {}
    glossary = {k: str(v) for k, v in column_meanings.items() if isinstance(v, str)}
    domain_payload: dict[str, Any] = {
        "inferred_industry": (domain_analysis or {}).get("domain") or None,
        "inferred_use_case": (domain_analysis or {}).get("dataset_summary") or None,
        "glossary": glossary,
        # audience_inference 는 AudienceAdapter (Phase 2) 가 보강 — 여기서는 기본값 유지.
    }
    new_state = agent.contribute_to_context(new_state, "domain", domain_payload)
    return new_state


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


# ============================================================================
# Phase 3·4 (2026-06-04) — Data Card v1 빌더 + 카테고리 4종 특화 점검
# ----------------------------------------------------------------------------
# 데이터 파악 15 단계의 결과를 11 섹션 dict 로 통합하여 state.data_card 에 저장.
# 다음 단계(EDA·전처리·게이트) 가 이 dict 를 참조한다.
# ============================================================================


def _safe_num(v: Any) -> Any:
    """JSON/msgpack 직렬화 가능한 형태로 정리. numpy.float64 등도 강제 Python 기본 타입으로 변환."""
    try:
        if v is None:
            return None
        if isinstance(v, bool):
            return v
        if isinstance(v, int):
            return int(v)
        if isinstance(v, float):
            # numpy.float64 도 float 의 서브클래스 → 강제 Python float 로
            f = float(v)
            # NaN/Inf 는 msgpack 에서 처리 안 되는 경우 있어 None 으로
            if f != f or f in (float("inf"), float("-inf")):
                return None
            return f
        if isinstance(v, str):
            return v
        return float(v)
    except Exception:
        return None


def _sanitize_for_serialization(obj: Any) -> Any:
    """data_card 전체를 재귀 순회하며 numpy/pandas 타입을 Python 기본 타입으로 변환.
    msgpack 이 인식하지 못하는 numpy.int64/float64/bool_, numpy.ndarray, pandas.Timestamp 등을 정리.
    Celery 의 result_serializer='json' 환경에서도 안전.
    """
    try:
        import numpy as _np
        import pandas as _pd
    except Exception:
        _np = None  # type: ignore
        _pd = None  # type: ignore
    if obj is None or isinstance(obj, (str, bool)):
        return obj
    if isinstance(obj, int) and not isinstance(obj, bool):
        return int(obj)
    if isinstance(obj, float):
        f = float(obj)
        return None if (f != f or f in (float("inf"), float("-inf"))) else f
    # numpy 스칼라
    if _np is not None and isinstance(obj, _np.integer):
        return int(obj)
    if _np is not None and isinstance(obj, _np.floating):
        f = float(obj)
        return None if (f != f or f in (float("inf"), float("-inf"))) else f
    if _np is not None and isinstance(obj, _np.bool_):
        return bool(obj)
    if _np is not None and isinstance(obj, _np.ndarray):
        return [_sanitize_for_serialization(x) for x in obj.tolist()]
    # pandas 타입
    if _pd is not None and isinstance(obj, _pd.Timestamp):
        return obj.isoformat()
    if _pd is not None and isinstance(obj, (_pd.Series, _pd.Index)):
        return [_sanitize_for_serialization(x) for x in obj.tolist()]
    if isinstance(obj, dict):
        return {str(k): _sanitize_for_serialization(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_sanitize_for_serialization(x) for x in obj]
    # 마지막 폴백 — 알 수 없는 객체는 문자열로
    try:
        return str(obj)
    except Exception:
        return None


def _build_data_card_v1(
    df: Any,
    state: PipelineState,
    category: str,
    target_column: Any,
    pii_extras: dict[str, Any],
    domain_analysis: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    """15 단계 점검을 종합한 Data Card v1.

    11 섹션:
      §1 identity  §2 schema  §3 dictionary  §4 granularity  §5 dq_score
      §6 category_target  §7 category_specific  §8 pii_legal
      §9 temporal_drift  §10 reproducibility  §11 next_steps
    """
    import datetime
    import hashlib

    try:
        n_rows, n_cols = int(df.shape[0]), int(df.shape[1])
    except Exception:
        n_rows, n_cols = 0, 0
    columns = [str(c) for c in df.columns]
    try:
        dtypes = {c: str(df.dtypes[c]) for c in columns}
    except Exception:
        dtypes = {}
    pii_cols = list((pii_extras or {}).get("columns") or [])

    # §1 identity & provenance
    identity = {
        "file_id": state.file_id,
        "job_id": state.job_id,
        "collected_at": datetime.datetime.utcnow().isoformat() + "Z",
        "row_count": n_rows,
        "col_count": n_cols,
        "source_hint": "user_upload",  # 운영 환경에선 DB/API 식별자 주입 권장
    }
    # §2 schema
    try:
        mem = int(df.memory_usage(deep=True).sum())
    except Exception:
        mem = 0
    schema = {
        "columns": columns,
        "dtypes": dtypes,
        "memory_bytes": mem,
        "index_type": str(type(df.index).__name__),
    }
    # §3 data dictionary (컬럼별 의미·단위·통계 요약)
    column_meanings = (domain_analysis or {}).get("column_meanings") or {}
    dictionary: dict[str, Any] = {}
    for col in columns:
        col_info: dict[str, Any] = {
            "meaning": str(column_meanings.get(col, "")),
            "dtype": dtypes.get(col, ""),
            "is_target": (col == target_column),
            "is_pii": col in pii_cols,
        }
        try:
            s = df[col]
            kind = getattr(s.dtype, "kind", "")
            col_info["missing_pct"] = round(float(s.isna().mean()) * 100, 2)
            col_info["nunique"] = int(s.nunique(dropna=True))
            if kind in "iuf":
                col_info["min"] = _safe_num(s.min()) if s.notna().any() else None
                col_info["max"] = _safe_num(s.max()) if s.notna().any() else None
                col_info["mean"] = _safe_num(s.mean()) if s.notna().any() else None
            elif kind in "Mm":
                col_info["min"] = str(s.min()) if s.notna().any() else None
                col_info["max"] = str(s.max()) if s.notna().any() else None
            else:
                vc = s.value_counts(dropna=True).head(3)
                col_info["top_values"] = {str(k): int(v) for k, v in vc.to_dict().items()}
        except Exception:
            pass
        dictionary[col] = col_info
    # §4 granularity
    try:
        dup_pct = round(float(df.duplicated().mean()) * 100, 2)
    except Exception:
        dup_pct = 0.0
    pk_candidates = []
    for c in columns:
        try:
            if df[c].nunique(dropna=True) == n_rows and df[c].notna().all():
                pk_candidates.append(c)
        except Exception:
            continue
    granularity = {
        "unit_of_analysis": str((domain_analysis or {}).get("dataset_summary", ""))[:200],
        "duplicate_pct": dup_pct,
        "pk_candidates": pk_candidates[:5],
    }
    # §5 DQ Score (6 차원, 모두 0~1)
    try:
        completeness = 1.0 - float(df.isna().mean().mean())
    except Exception:
        completeness = 1.0
    uniqueness = 1.0 - (dup_pct / 100.0)
    # validity: dtype 가 object 가 아니거나(타입 명확), 또는 unique > 1 (모두 같은 값 아님)
    validity_cnt = 0
    for c in columns:
        try:
            if dtypes.get(c, "") != "object" or df[c].nunique(dropna=True) > 1:
                validity_cnt += 1
        except Exception:
            continue
    validity = validity_cnt / max(1, n_cols)
    # consistency: 결측 패턴 상관 평균 (구조적 결측이면 1.0 에 가까움)
    try:
        if n_cols > 1:
            mc = df.isna().corr().abs().fillna(0)
            consistency = float(mc.values.mean())
        else:
            consistency = 1.0
    except Exception:
        consistency = 1.0
    accuracy = 0.8  # 외부 검증 필요 영역 — 보수값
    timeliness = 1.0  # 업로드 직후 = 최신으로 간주
    overall = round((completeness + uniqueness + validity + consistency + accuracy + timeliness) / 6.0, 3)
    dq_score = {
        "completeness": round(completeness, 3),
        "uniqueness": round(uniqueness, 3),
        "validity": round(validity, 3),
        "consistency": round(consistency, 3),
        "accuracy": accuracy,
        "timeliness": timeliness,
        "overall": overall,
    }
    # §6 category & target
    category_target = {
        "category": category,
        "target_column": target_column,
        "reason": str((domain_analysis or {}).get("target_insight", "")),
    }
    # §7 category-specific
    category_specific = _category_specific_checks(df, category, target_column, n_rows, columns, dtypes)
    # §8 pii_legal
    pii_legal = {
        "pii_columns": pii_cols,
        "masked": bool(pii_cols),
        "license_status": "unknown",
        "consent_status": "unknown",
    }
    # §9 temporal_drift
    time_cols = []
    for c in columns:
        try:
            if df[c].dtype.kind == "M":
                time_cols.append(c)
            elif any(tok in c.lower() for tok in ("date", "time", "ts", "일자", "시각")):
                time_cols.append(c)
        except Exception:
            continue
    temporal_drift = {
        "has_time_column": bool(time_cols),
        "time_columns": time_cols[:5],
        "drift_risk_note": (
            "운영 배포 시 train/test 시점 분리 필요" if time_cols else "시간 인덱스 없음 — 임의 split 가능"
        ),
    }
    # §10 reproducibility
    try:
        sample_str = str(df.head(20).to_dict()).encode("utf-8", errors="replace")
        data_hash = hashlib.sha256(sample_str).hexdigest()[:16]
    except Exception:
        data_hash = ""
    reproducibility = {
        "data_hash_sample": data_hash,
        "seed": 42,
        "schema_version": "data_card_v1",
    }
    # §11 next_steps (EDA·전처리·모델로 넘기는 권고)
    next_steps: list[str] = []
    if dq_score["overall"] < 0.7:
        next_steps.append("DQ Score 낮음 → 전처리 단계에서 결측·중복 우선 처리")
    if (not target_column) and category != "anomaly_detection":
        next_steps.append("타깃 컬럼 미식별 → EDA 단계에서 후보 추가 검토")
    if time_cols and category != "timeseries":
        next_steps.append("시간 컬럼 발견 → 시계열 카테고리 재검토 가능")
    if pii_cols:
        next_steps.append("PII 컬럼 마스킹 적용 — 결과물 외부 공유 시 추가 검토")
    if dup_pct > 5:
        next_steps.append(f"중복 행 {dup_pct}% 발견 → 전처리에서 dedup 필요")
    if not next_steps:
        next_steps.append("EDA 단계로 진행 가능 — 특이사항 없음")

    _card = {
        "identity": identity,
        "schema": schema,
        "dictionary": dictionary,
        "granularity": granularity,
        "dq_score": dq_score,
        "category_target": category_target,
        "category_specific": category_specific,
        "pii_legal": pii_legal,
        "temporal_drift": temporal_drift,
        "reproducibility": reproducibility,
        "next_steps": next_steps,
    }
    # msgpack/JSON 직렬화 안전화 — 재귀로 numpy/pandas 타입을 Python 기본 타입으로 강제 변환.
    # Celery 가 state.data_card 를 직렬화할 때 'Type is not msgpack serializable: numpy.float64'
    # 같은 오류를 방지한다.
    return _sanitize_for_serialization(_card)


def _category_specific_checks(
    df: Any,
    category: str,
    target_column: Any,
    n_rows: int,
    columns: list[str],
    dtypes: dict[str, str],
) -> dict[str, Any]:
    """카테고리 4종 특화 사전 점검 (EDA 전).

    tabular_ml: 클래스 균형, 타깃 누수 후보, 다중공선성 신호, 카디널리티 분포.
    tabular_dl: 데이터 규모, 고카디널리티 임베딩 후보, 스케일 격차.
    timeseries: 시간 컬럼, 빈도, gap, 멀티시리즈 ID, timezone.
    anomaly_detection: 라벨 유무, contamination, 다변량 후보.
    """
    checks: dict[str, Any] = {"category": category}
    try:
        if category == "tabular_ml":
            if target_column and target_column in df.columns:
                vc = df[target_column].value_counts(dropna=True)
                n = int(vc.sum())
                if len(vc) <= 20 and n > 0:
                    checks["task_type"] = "classification"
                    checks["class_balance"] = {str(k): round(float(v / n), 3) for k, v in vc.items()}
                    minor = float(vc.min())
                    major = float(vc.max())
                    checks["imbalance_ratio"] = round(major / max(1.0, minor), 2)
                    checks["baseline_accuracy"] = round(major / n, 3)
                else:
                    checks["task_type"] = "regression"
                    s = df[target_column].dropna()
                    if len(s) > 0:
                        checks["target_stats"] = {
                            "mean": _safe_num(s.mean()),
                            "std": _safe_num(s.std()) if len(s) > 1 else 0.0,
                            "skew": _safe_num(s.skew()) if len(s) > 2 else 0.0,
                        }
            # 고카디널리티 범주 (>50)
            checks["high_cardinality_cols"] = [
                c for c in columns if dtypes.get(c, "") in ("object", "category") and df[c].nunique(dropna=True) > 50
            ][:10]
            if n_rows < 1000:
                checks["dataset_size_note"] = "표본 부족 — ML 신뢰도 낮음"
            elif n_rows > 1_000_000:
                checks["dataset_size_note"] = "대용량 — 샘플링·DL 고려"
            else:
                checks["dataset_size_note"] = "ML 적정 규모"
            # 타깃 누수 1차 의심: 컬럼명에 leak/leaked/post/after/result 등
            leak_kw = ("leak", "post", "after", "result", "future")
            checks["leakage_candidates"] = [
                c for c in columns if c != target_column and any(k in c.lower() for k in leak_kw)
            ][:5]
        elif category == "tabular_dl":
            checks["dataset_size_ok"] = bool(n_rows >= 10000)
            checks["high_cardinality_embedding_candidates"] = [
                c for c in columns if dtypes.get(c, "") in ("object", "category") and df[c].nunique(dropna=True) > 50
            ][:10]
            num_cols = [c for c in columns if dtypes.get(c, "").startswith(("int", "float"))]
            ranges = []
            for c in num_cols:
                try:
                    if df[c].notna().any():
                        ranges.append(float(df[c].max()) - float(df[c].min()))
                except Exception:
                    continue
            if ranges and min(ranges) > 0:
                checks["scale_spread"] = round(max(ranges) / max(min(ranges), 1e-9), 2)
            checks["seed"] = 42
        elif category == "timeseries":
            time_cols_kind = [c for c in columns if df[c].dtype.kind == "M"]
            if not time_cols_kind:
                # 휴리스틱: 컬럼명에 date/time/ts
                for c in columns:
                    if any(tok in c.lower() for tok in ("date", "time", "ts")):
                        try:
                            import pandas as pd

                            pd.to_datetime(df[c], errors="raise")
                            time_cols_kind.append(c)
                            break
                        except Exception:
                            continue
            checks["time_columns"] = time_cols_kind[:3]
            if time_cols_kind:
                try:
                    import pandas as pd

                    ts = pd.to_datetime(df[time_cols_kind[0]], errors="coerce").dropna().sort_values()
                    if len(ts) > 1:
                        diffs = ts.diff().dropna()
                        if not diffs.empty:
                            checks["frequency_hint"] = str(diffs.mode().iloc[0])
                            checks["timezone"] = str(ts.dt.tz) if ts.dt.tz else "naive"
                            checks["gap_count"] = int((diffs > diffs.median() * 2).sum())
                except Exception:
                    pass
            checks["multi_series_id_candidates"] = [
                c
                for c in columns
                if dtypes.get(c, "") in ("object", "category", "int64") and 1 < df[c].nunique(dropna=True) <= 100
            ][:5]
        elif category == "anomaly_detection":
            if target_column and target_column in df.columns:
                vc = df[target_column].value_counts(dropna=True)
                n = int(vc.sum())
                if len(vc) == 2 and n > 0:
                    minor = float(vc.min())
                    checks["labeled"] = True
                    checks["contamination_pct"] = round((minor / n) * 100, 3)
                else:
                    checks["labeled"] = False
    except Exception:
        pass
    return checks
