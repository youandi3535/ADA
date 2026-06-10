"""agents.schema_validator — SchemaValidatorAgent (Day05 §2)."""

from __future__ import annotations

import json as _json
from typing import Any

from ada.core.state import PipelineState
from agents.base import BaseAgent


def _save_g2_screen_ready(state: PipelineState) -> None:
    """HJ 2026-06-09 G1 단축 Z' — G2 화면 사전 진입용 부분 gate_data 를 Redis 에 저장.

    저장 키: ``ada:gate_data:{job_id}`` — 기존 _save_gate_data 와 동일 키 사용.
    gate_direction 이 끝나면 _save_gate_data 가 proposals 채워 덮어씀 — race-safe.

    저장 필드:
      - gate: "G2"
      - proposals: [] (빈 배열 = "분석 방향 생성 중" spinner 표시 트리거)
      - g2_pending: True (frontend 가 spinner 인식)
      - category, target_column, data_profile, domain_partial 등 화면 표시용

    누수 방지: Redis 실패해도 본 G1 흐름 영향 없음 (best-effort).
    """
    try:
        import redis as _redis  # noqa: WPS433

        from ada.core.config import settings as _s  # noqa: WPS433

        r = _redis.Redis.from_url(_s.redis_url)
        dp = state.data_profile or {}
        payload = {
            "gate": "G2",
            "proposals": [],  # 빈 = spinner 트리거
            "g2_pending": True,  # gate_direction 진행 중 신호
            "category": state.category,
            "target_column": state.target_column,
            "data_profile": {
                # 필수 필드만 — 전체 보내면 페이로드 큼
                "rows": dp.get("rows"),
                "cols": dp.get("cols"),
                "columns": dp.get("columns"),
                "target_dtype": dp.get("target_dtype"),
                "class_distribution": dp.get("class_distribution"),
                "domain_analysis": dp.get("domain_analysis"),
                "date_col": dp.get("date_col"),
            },
            "requested_outputs": [],
            "output_paths": {},
        }
        r.set(
            f"ada:gate_data:{state.job_id}",
            _json.dumps(payload, ensure_ascii=False, default=str),
            ex=86400,
        )
    except Exception:  # noqa: BLE001
        # G1 critical path 안전 — Redis 실패해도 정상 진행
        pass

    # CS 2026-06-10 — 백그라운드 prefetch 제거. race condition 원인.
    # propose_topics 는 AnalysisProposerAgent.__call__ 에서 메인 흐름으로 호출됨.
    # (gate_direction 노드의 실제 작업으로 → 마일스톤 sync 정합 + 스키마 검증 완료 후 팝업)


async def _prefetch_topic_proposals(state: PipelineState) -> None:
    """G2 Sub-1 주제 5개 백그라운드 생성. 30초 timeout + 실패 시 fallback patch.

    CS 2026-06-10 — 무한 대기 방지:
      - LLM 호출 30초 안에 응답 없으면 TimeoutError 발생 → fallback 으로 patch
      - 어떤 예외가 나도 _TOPIC_FALLBACK_DEFAULTS 정적 5개를 Redis 에 patch
      - 결과 : 사용자가 30초 이상 영원히 "주제 후보 준비 중…" 보지 않음
    """
    import asyncio as _asyncio

    try:
        from agents.gates.analysis_proposer import AnalysisProposerAgent  # noqa: WPS433

        agent = AnalysisProposerAgent()
        topics = await _asyncio.wait_for(agent.propose_topics(state), timeout=30.0)
        _patch_gate_data(state.job_id, {"topic_proposals": topics})
    except Exception:  # noqa: BLE001
        # 실패·timeout → fallback 즉시 patch (무한 대기 방지)
        try:
            from agents.gates.analysis_proposer import _TOPIC_FALLBACK_DEFAULTS  # noqa: WPS433

            _patch_gate_data(
                state.job_id,
                {"topic_proposals": [dict(t) for t in _TOPIC_FALLBACK_DEFAULTS]},
            )
        except Exception:  # noqa: BLE001
            pass


def _patch_gate_data(job_id: str, patch: dict[str, Any]) -> None:
    """기존 ada:gate_data:{job_id} 의 키 보존 + patch 만 덮어쓰기."""
    try:
        import redis as _redis  # noqa: WPS433

        from ada.core.config import settings as _s  # noqa: WPS433

        r = _redis.Redis.from_url(_s.redis_url)
        raw = r.get(f"ada:gate_data:{job_id}")
        gd = _json.loads(raw) if raw else {}
        gd.update(patch)
        r.set(
            f"ada:gate_data:{job_id}",
            _json.dumps(gd, ensure_ascii=False, default=str),
            ex=86400,
        )
    except Exception:  # noqa: BLE001
        pass


# v2 4 카테고리만
CATEGORY_RULES: dict[str, dict[str, Any]] = {
    "tabular_ml": {
        "min_rows": 100,
        "max_cols": 1000,
        "requires_target": True,
        "min_target_classes": 2,
    },
    "tabular_dl": {
        "min_rows": 1000,
        "max_cols": 1000,
        "requires_target": True,
    },
    "timeseries": {
        "min_rows": 50,
        "requires_target": True,
        "requires_date_col": True,
    },
    "anomaly_detection": {
        "min_rows": 500,
        "requires_target": False,
    },
}


class SchemaValidatorAgent(BaseAgent):
    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            rules = CATEGORY_RULES.get(state.category)
            if rules is None:
                v = {"is_valid": False, "errors": [f"Unsupported category: {state.category}"], "warnings": []}
                return state.with_update(validation=v, next_agent="error_recovery", error=v["errors"][0])
            v = self._validate(state.data_profile or {}, rules)
            if v["is_valid"]:
                # HJ 2026-06-09 G1 단축 Z' — 검증 성공 시 G2 화면 사전 진입 신호.
                # gate_direction LLM (~55s) 가 진행되는 동안 사용자는 G2 의 "주제 선정" 영역
                # (도메인·column_meanings) 을 먼저 보면서 결정 고민. 사용자 고민 시간이
                # gate_direction LLM 시간에 흡수 → 체감 -30~50s.
                _save_g2_screen_ready(state)
                return state.with_update(validation=v, next_agent="gate_direction", error=None)

            # 데이터 검증 실패 = 사용자가 잘못된 카테고리를 선택한 경우.
            # AutoErrorHandler(코드 패치)로 보내지 않고 tabular_ml 로 자동 보정 후
            # gate_direction(G2)에서 재진행 — 사용자 입장에서는 자동 복구로 보임.
            #
            # Z' 적용 시 카테고리 보정이 발생하면 stale 도메인 분석을 사전 표시하지 않음
            # (도메인 분석은 보정 전 카테고리 기반이라 불일치 위험). 기존 흐름만 유지.
            fallback = "tabular_ml"
            fallback_rules = CATEGORY_RULES[fallback]
            v2 = self._validate(state.data_profile or {}, fallback_rules)
            warn_msg = (
                f"선택한 카테고리({state.category})가 데이터와 맞지 않습니다 "
                f"({'; '.join(v['errors'])}). "
                f"'{fallback}'으로 자동 변경합니다."
            )
            self.logger.warning(
                "category_auto_corrected",
                original=state.category,
                fallback=fallback,
                errors=v["errors"],
            )
            return state.with_update(
                category=fallback,
                validation={**v2, "warnings": [warn_msg] + (v2.get("warnings") or [])},
                next_agent="gate_direction",
                error=None,
            )

    @staticmethod
    def _validate(profile: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []

        rows = int(profile.get("rows", 0))
        cols = int(profile.get("cols", 0))

        if "min_rows" in rules and rows < rules["min_rows"]:
            errors.append(f"행 수 부족: {rows} < {rules['min_rows']}")
        if "max_cols" in rules and cols > rules["max_cols"]:
            errors.append(f"컬럼 수 초과: {cols} > {rules['max_cols']}")

        if rules.get("requires_target") and not profile.get("has_target"):
            errors.append("target_column 지정 필수")

        if rules.get("min_target_classes"):
            cd = profile.get("class_distribution") or {}
            if cd and len(cd) < rules["min_target_classes"]:
                errors.append(f"target 클래스 수 부족: {len(cd)} < {rules['min_target_classes']}")

        if rules.get("requires_date_col") and not profile.get("date_col"):
            errors.append("시계열 카테고리: 날짜 컬럼 필수")

        for col, missing_rate in (profile.get("missing") or {}).items():
            if missing_rate > 0.5:
                warnings.append(f"컬럼 '{col}' 결측률 {missing_rate:.1%} — 제거 권장")

        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }
