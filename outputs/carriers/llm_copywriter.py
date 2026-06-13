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
_BUDGET = {"title_ko": 30, "so_what": 70, "bullet": 90}

# bullet 허용 범위 — "사실 — 시사점" 페어 3~5개 (초안 개수에 묶지 않음, 2026-06-12 확장)
_BULLET_MIN, _BULLET_MAX = 2, 5

_SYSTEM_PROMPT = """\
당신은 데이터 분석 보고서의 시니어 카피라이터입니다. 자동 분석 파이프라인이 만든
슬라이드 초안과 분석 데이터(JSON)를 받아, 각 슬라이드의 문장을 컨설팅 수준으로
다시 씁니다.

원칙:
1. Action Title — 제목은 명사 나열이 아니라 발견을 말한다.
   나쁨: "EDA · 주요 변수 1" / 좋음: "성별이 최대 생존 결정 변수 — 55%p 격차"
2. KEY INSIGHTS 페어 (필수) — 모든 bullet 은 "사실 (수치 인용) — 그래서 알 수 있는 것"
   2부 구조로 쓴다. 사실만 나열하고 끝내지 말 것.
   나쁨: "여성 생존율 74.2%"
   좋음: "여성 74.2% vs 남성 18.9% (55%p) — 단일 변수로 최대 판별 신호"
3. 수치 인용 제한 — 반드시 입력 data 에 존재하는 수치만 사용. 새 수치 창작 금지.
   재료가 부족하면 bullet 수를 줄여라. 빈 말로 채우지 말 것.
4. bullet 은 3~5개 — 입력 data 의 재료가 허용하는 만큼 확장하라.
   초안보다 많아도 된다 (단, 모든 추가 bullet 은 data 의 수치·사실에 근거).
5. 글자 예산 — title_ko ≤ 30자, so_what ≤ 70자, bullet ≤ 90자.
6. 한국어. 단, 모델명·지표명 (CatBoost, val_accuracy 등) 은 원어 유지.
7. 초안이 이미 구체적이고 수치를 인용하면 미세 수정만.
8. 사정거리 (필수) — role 이 "claim" 또는 "insight" 인 슬라이드는 마지막 bullet 을
   "추론 사정거리" 문장으로 쓴다: 이 결과로 어디까지 말할 수 있고, 무엇이 더 있으면
   다음 단계 추론이 가능한지. limitations·미적립 재료를 인용해 경계를 정직하게 긋는다.
   예: "이 결과는 탑승 시점 변수 기준 — 구조 과정 변수(갑판 위치 등)가 있으면
   인과 해석까지 확장 가능"
9. 완료 시제 (필수) — 이 발표는 *끝난 분석* 의 보고다. "~확인 필요", "~권장",
   "~예정" 같은 진행 중 권고 톤 금지. 수행된 처리와 그 *결과* 를 서술하라.
   나쁨: "불균형 여부 별도 확인 필요" / 좋음: "타겟 38:62 — 불균형 보정 없이 학습 가능 수준"
   예외: 사정거리 bullet (규칙 8) 과 후속 작업·로드맵 슬라이드만 미래형 허용.
   data 에 결과가 없으면 그 항목은 다른 *확정된 사실* 로 대체하라.
12-3. 발견 종합 특칙 (id "insight_synthesis") — 이 장은 모델 내부(SHAP·변수 기여·
   정확도)를 *설명하지 않는다*. 그건 뒤 슬라이드에서 다룬다. 여기서는 "이 데이터를
   분석해서 *현실 세계에서 무엇을 알게 되는가*"를 쓴다. user_intent 와 도메인을 보고
   이 분석이 드러내는 정책·사회·비즈니스·행동 차원의 의미를 해석하라.
   나쁨(기술 요약): "Sex_male SHAP 0.601이 판단의 주축 — 비선형 상호작용 흡수"
   좋음(현실 함의): "성별이 생존을 갈랐다 — 재난 시 '여성·아동 우선' 구조 원칙이
   데이터로 입증됨", "선실 등급이 생존율을 좌우 — 사회경제적 지위가 생사를 가른
   불평등의 증거". 발견 수치는 근거로만 인용하고, 문장의 주어는 *현실 현상*이어야 한다.
12-1. EDA·해석 슬라이드 풍부화 — EDA/CM/세그먼트/사례 장은 페어 4개를 채우고,
   각 시사점은 발견에서 멈추지 말고 *전처리·피처·운영 전략의 함의*까지 잇는다
   (60~90자). 예: "Cabin 77% 결측 — 결측 자체가 등급 대리 신호, 유무 파생 피처가
   정보 손실을 회수". 사례(S14) 장은 CM 집계(S15)와 겹치지 않게 *개별 승객의
   이야기* 로 서술 — "이 승객은 왜 틀렸나"의 답이 되어야 한다.
12-2. 인사이트 종합 (id "insight_synthesis") — 제목은 예시 문구가 아니라 이 분석의
   *실제 종합 결론* 한 문장 (예: "성별·요금·등급이 생존을 구조적으로 결정 — 0.79
   정확도로 정량 입증"). body 는 인사이트·접목 중심으로 쓴다.
12. 인사이트 우선 (전 슬라이드 필수) — 이 덱의 주인공은 수치가 아니라 *해석*이다.
   모든 수치는 반드시 맥락 비교(평균 대비·임계 대비·타 변수 대비)와 "그래서 무엇을
   의미하는가"를 동반하라. 시사점이 사실의 재서술이면 실패다.
   나쁨: "Fare SHAP 0.983 — Fare 가 가장 높음" (재서술)
   좋음: "Fare SHAP 0.983 — 2위(0.45)의 2배, 티켓 가격이 등급·구조 접근성을 통합 대리"
   결과값만 나열된 초안은 적극적으로 해석을 추가해 다시 써라.
10-2. 브리지 부제 — 입력 slides 는 발표 순서다. 섹션이 전환되는 슬라이드
   (데이터→방법, 방법→EDA, EDA→모델 성능, 해석→운영 정책)의 so_what 은
   직전 내용을 받아 다음으로 넘기는 전환 구문으로 시작하라.
   예: "데이터 품질을 확인했으니, 이제 어떤 방법으로 분석할지 — CatBoost + 검증 설계"
   전환 슬라이드가 아니면 적용하지 말 것. 뒤 슬라이드 내용을 앞당겨 쓰지 말 것.
10-1. 분석 가설 특칙 (id "hypothesis") — 각 bullet 은 정확히
   "가설문 — 증거 (수치 인용) — 인사이트" 3분할로 쓴다. H1·01 같은 라벨 접두 금지.
   나쁨: "H1 · 핵심 변수 영향 · Sex가 신호를 제공한다고 가설 — 입증됨"
   좋음: "Sex 가 결정적 신호다 — 여성 74.2% vs 남성 18.9% (55%p) — 구조 우선순위가 데이터에 재현됨"
10. Executive Summary 특칙 (id "exec_summary") — 이 장은 덱 *전체* 의 요약이다.
   title_ko 는 "Executive Summary" 그대로 유지 (Action Title 규칙 1 적용 금지).
   so_what 은 덱 전체를 한 문장으로: 무엇을(과제) + 어떻게(모델) + 결과(핵심 수치)
   + 결정(verdict 에 따른 도입/보완/보류 권고)을 모두 담는다.
   나쁨: "성별 55%p 격차가 핵심 신호 — CatBoost 가 포착" (개별 발견 요약에 불과)
   좋음: "CatBoost 로 타이타닉 생존 79% 정확도 달성 — 임계 통과, 운영 도입 권장"

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
                # 2026-06-12 — 인용 재료 확장 (세그먼트·CM): 페어 bullet 의 근거 공급
                "per_segment": _safe(lambda: list(ctx.evaluation.per_segment or [])[:6], []),
                "confusion_matrix": _safe(lambda: ctx.evaluation.confusion_matrix, None),
            },
            "baselines": _safe(lambda: dict(ctx.model_selection.baselines.__dict__), {}),
            # dataclass → dict (json.dumps 안전 — 객체 그대로면 TypeError 로 전체 폴백됨)
            "shap_top": _safe(
                lambda: [
                    {"feature": g.feature, "importance": g.importance}
                    for g in (ctx.interpretation.global_importance or [])[:5]
                ],
                [],
            ),
            # jh 2026-06-12 — S14 개별 사례 재료
            "local_examples": _safe(
                lambda: list(ctx.interpretation.local_examples or [])[:3], []
            ),
            # jh 2026-06-12 — '어디까지 볼 수 있나' (사정거리) 재료: 한계·데이터 공백
            "limitations": {
                "model_caveats": _safe(lambda: list(ctx.limitations.model_caveats or [])[:5], []),
                "data_gaps": _safe(lambda: list(ctx.limitations.data_gaps or [])[:5], []),
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

            # jh 2026-06-12 — 초과 제목은 기각 대신 절단 수용.
            # (기각 시 구식 초안 제목이 남아 새 so_what 과 불일치 — 운영 S10 실측)
            title = str(fill.get("title_ko", "") or "").strip()
            if title:
                limit = _BUDGET["title_ko"] + 10
                if len(title) > limit:
                    cut = title[:limit]
                    for sep in (" — ", " · ", ", ", " "):
                        idx = cut.rfind(sep)
                        if idx >= int(limit * 0.5):
                            cut = cut[:idx]
                            break
                    title = cut.rstrip(" .,·—")
                out["title_ko"] = title
            so_what = str(fill.get("so_what", "") or "").strip()
            if so_what and len(so_what) <= _BUDGET["so_what"] + 20:
                out["so_what"] = so_what

            body = fill.get("body_outline")
            # 2026-06-12 — 초안 개수 고정 해제: 재료가 있으면 3~5개로 확장 허용.
            # (어제 견본 수준의 KEY INSIGHTS 분량. 상한 초과는 잘라내지 않고 기각 — 안전)
            if isinstance(body, list) and body:
                bullets = [str(b).strip() for b in body if str(b).strip()]
                if (
                    bullets
                    and _BULLET_MIN <= len(bullets) <= _BULLET_MAX
                    and all(len(b) <= _BUDGET["bullet"] + 30 for b in bullets)
                ):
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
