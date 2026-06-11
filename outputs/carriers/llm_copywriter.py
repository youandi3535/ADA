"""outputs.carriers.llm_copywriter — 슬라이드 문장 LLM 채움 (Phase 3 — 카피라이팅 레이어).

흐름 (jh 2026-06-11, HJ 구두 협의):
    템플릿 소환 (state.report_plan → SlideSpec 20장)
    → 템플릿 구성 파악 (슬라이드별 제목/so_what/bullet 슬롯 + 글자 예산)
    → 데이터 수집 (ReportContext ①~⑪ — profile/eda meta/model/evaluation)
    → 문장 채움 (덱 전체 1회 LLM batch — 톤 일관 + 비용 최소)

설계 원칙:
    - LLM 호출은 덱당 1회. 슬라이드별 호출 금지 (디자이너 18회와 달리 문장은
      덱 전체 서사 일관성이 필요).
    - 수치 인용 제한 — 입력 데이터에 있는 수치만 사용 지시. 위반 의심 시
      로깅 (완전 차단 가드레일은 Day 8 InsightAgent 와 통합 예정).
    - 실패 시 기존 skeleton 문장 유지 (안전 폴백) + 로그 1줄 (침묵 금지).
    - cover/agenda/section_divider/closing 은 채움 대상 제외.

LLMDesigner 와 동일 패턴. BaseAgent abstract __call__ 구현 필수 (2026-06-11 사고).
"""

from __future__ import annotations

import json
import re
from typing import Any

from agents.base import BaseAgent

# 채움 제외 레이아웃 — 구조 고정 슬라이드
_SKIP_LAYOUTS = ("cover", "agenda", "section_divider", "closing")

# 글자 예산 (한글 기준) — 템플릿 박스 크기에서 도출한 보수적 상한
_BUDGET = {"title_ko": 30, "so_what": 70, "bullet": 80}

_SYSTEM_PROMPT = """\
당신은 데이터 분석 보고서의 시니어 카피라이터입니다. 자동 분석 파이프라인이 만든
슬라이드 초안과 분석 데이터(JSON)를 받아, 각 슬라이드의 문장을 컨설팅 수준으로
다시 씁니다.

원칙:
1. Action Title — 제목은 명사 나열이 아니라 발견을 말한다.
   나쁨: "EDA · 주요 변수 1" / 좋음: "성별이 최대 생존 결정 변수 — 55%p 격차"
2. 주장 → 근거 구조 — so_what 은 한 문장 주장, bullet 은 수치 근거.
3. 수치 인용 제한 — 반드시 입력 data 에 존재하는 수치만 사용. 새 수치 창작 금지.
   데이터에 수치가 없으면 정성 서술로만.
4. 글자 예산 — title_ko ≤ 30자, so_what ≤ 70자, bullet ≤ 80자.
   bullet 개수는 초안과 동일하게 유지.
5. 한국어. 단, 모델명·지표명 (CatBoost, val_accuracy 등) 은 원어 유지.
6. 초안이 이미 구체적이고 수치를 인용하면 미세 수정만.

출력 — STRICT JSON only (설명·서론 금지):
{"slides": {"<slide_id>": {"title_ko": "...", "so_what": "...", "body_outline": ["...", ...]}, ...}}
모든 입력 슬라이드 id 를 포함할 것. 바꿀 게 없으면 초안 그대로 반환.
"""


class LLMCopywriter(BaseAgent):
    """덱 전체 문장 1회 채움."""

    uses_llm = True
    model_name = "claude-sonnet-4-6"  # 문장 품질이 본질 — haiku 대신 sonnet
    use_anthropic_api = True

    async def __call__(self, state: Any) -> Any:  # pragma: no cover — 그래프 노드 아님
        """LLMCopywriter 는 파이프라인 노드가 아님 — ``fill_deck`` 전용. state 그대로 반환."""
        return state

    async def fill_deck(self, slides: list[Any], ctx: Any) -> dict[str, dict]:
        """슬라이드 목록의 문장 채움 결과 반환. 실패 시 빈 dict (폴백).

        Returns:
            {slide_id: {"title_ko": str, "so_what": str, "body_outline": [str]}}
        """
        targets = [sl for sl in slides if getattr(sl, "layout", "") not in _SKIP_LAYOUTS]
        if not targets:
            return {}

        payload = {
            "slides": [
                {
                    "id": sl.id,
                    "role": getattr(sl, "role", "") or "",
                    "layout": getattr(sl, "layout", "") or "",
                    "draft": {
                        "title_ko": sl.title_ko or "",
                        "so_what": getattr(sl, "so_what", "") or "",
                        "body_outline": list(getattr(sl, "body_outline", None) or []),
                    },
                }
                for sl in targets
            ],
            "data": self._collect_data(ctx),
        }

        try:
            raw = await self._call_llm(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=json.dumps(payload, ensure_ascii=False),
                max_tokens=8000,
                temperature=0.4,
            )
        except Exception as e:
            self.logger.warning("copywriter_llm_failed", error=str(e))
            return {}

        parsed = self._parse_json_lenient(raw)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("slides"), dict):
            self.logger.warning("copywriter_unparsable", raw_head=(raw or "")[:200])
            return {}

        fills = self._validate(parsed["slides"], payload, targets)
        self.logger.info("copywriter_done", filled=len(fills), targets=len(targets))
        return fills

    # ------------------------------------------------------------------

    def _collect_data(self, ctx: Any) -> dict[str, Any]:
        """ReportContext → 슬라이드 문장의 인용 가능 수치·사실 패키지."""

        def _safe(fn, default=None):
            try:
                return fn()
            except Exception:
                return default

        pm = _safe(lambda: ctx.evaluation.primary_metric, {}) or {}
        return {
            "meta": {
                "category": _safe(lambda: ctx.meta.category, ""),
                "user_intent": (_safe(lambda: ctx.meta.user_intent, "") or "")[:200],
                "audience": _safe(lambda: ctx.meta.audience, ""),
            },
            "profile": {
                # ReportContext 의 ① 데이터 프로파일 필드명은 dataset (probe 로 실측 확인)
                "shape": _safe(lambda: dict(ctx.dataset.shape), {}),
                "missing_top": _safe(
                    lambda: dict(
                        sorted(ctx.dataset.missing_rate.items(), key=lambda kv: -kv[1])[:5]
                    ),
                    {},
                ),
                "target": _safe(lambda: ctx.dataset.detected_target, None),
            },
            "domain": {
                "industry": _safe(lambda: ctx.domain.inferred_industry, ""),
                "use_case": _safe(lambda: ctx.domain.inferred_use_case, ""),
            },
            "eda_findings": _safe(
                lambda: [
                    {
                        "x": c.x,
                        "title": c.title_ko,
                        "finding": c.finding,
                        "numbers": list(c.numbers or [])[:5],
                    }
                    for c in ctx.eda.charts
                    if c.finding or c.numbers
                ],
                [],
            ),
            "features_created": _safe(
                lambda: [getattr(f, "name", str(f)) for f in (ctx.features.created or [])][:10], []
            ),
            "model": {
                "chosen": _safe(lambda: dict(ctx.model_selection.chosen), {}),
                "candidates": _safe(
                    lambda: [
                        {"name": c.name, "score": getattr(c, "score", None)}
                        for c in ctx.model_selection.candidates
                    ][:5],
                    [],
                ),
            },
            "evaluation": {
                "primary_metric": pm,
                "metrics": _safe(lambda: dict(ctx.evaluation.metrics or {}), {}),
                "verdict": _safe(lambda: ctx.evaluation.verdict, ""),
                "gate_passed": _safe(lambda: ctx.evaluation.gate_passed, None),
            },
        }

    # ------------------------------------------------------------------

    def _validate(
        self, slides_out: dict, payload: dict, targets: list[Any]
    ) -> dict[str, dict]:
        """형식·예산·수치 출처 검증. 통과 필드만 채택."""
        data_blob = json.dumps(payload["data"], ensure_ascii=False)
        valid_ids = {sl.id for sl in targets}
        draft_by_id = {s["id"]: s["draft"] for s in payload["slides"]}
        fills: dict[str, dict] = {}

        for sid, fill in slides_out.items():
            if sid not in valid_ids or not isinstance(fill, dict):
                continue
            draft = draft_by_id.get(sid, {})
            out: dict[str, Any] = {}

            title = str(fill.get("title_ko", "") or "").strip()
            if title and len(title) <= _BUDGET["title_ko"] + 10:
                out["title_ko"] = title
            so_what = str(fill.get("so_what", "") or "").strip()
            if so_what and len(so_what) <= _BUDGET["so_what"] + 20:
                out["so_what"] = so_what

            body = fill.get("body_outline")
            n_draft = len(draft.get("body_outline") or [])
            if isinstance(body, list) and body and (n_draft == 0 or len(body) == n_draft):
                bullets = [str(b).strip() for b in body if str(b).strip()]
                if bullets and all(len(b) <= _BUDGET["bullet"] + 30 for b in bullets):
                    out["body_outline"] = bullets

            # 수치 출처 점검 (소프트) — 출력 수치가 입력 data 에 없으면 경고만.
            # 백분율 변환 인식: 출력 74.2(%) ↔ 입력 0.742 는 동일 값으로 간주.
            joined = " ".join([out.get("title_ko", ""), out.get("so_what", "")] + out.get("body_outline", []))
            draft_blob = json.dumps(draft, ensure_ascii=False)

            def _known(n: str) -> bool:
                if n in data_blob or n in draft_blob:
                    return True
                try:
                    v = float(n) / 100.0
                except ValueError:
                    return False
                return any(
                    f"{v:.{prec}f}".rstrip("0") in data_blob for prec in (2, 3, 4)
                )

            suspicious = [
                n for n in re.findall(r"\d+(?:\.\d+)?", joined) if len(n) >= 2 and not _known(n)
            ]
            if suspicious:
                self.logger.info(
                    "copywriter_number_unverified", slide_id=sid, numbers=suspicious[:5]
                )

            if out:
                fills[sid] = out
        return fills

    # ------------------------------------------------------------------

    def _parse_json_lenient(self, text: str) -> Any:
        """llm_designer._parse_json_lenient 와 동일 — JSON 앞뒤 잡설 방어."""
        parsed = self._parse_json(text)
        if isinstance(parsed, dict):
            return parsed
        if not text:
            return None
        start = text.find("{")
        while start != -1:
            depth = 0
            for i in range(start, len(text)):
                ch = text[i]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start : i + 1])
                        except Exception:
                            break
            start = text.find("{", start + 1)
        return None


__all__ = ["LLMCopywriter"]
