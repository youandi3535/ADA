"""outputs.content.terminology — 보고서 단위 용어 사전 (Phase 3, Part 11-2).

ReportPlan + ReportContext 에서 등장하는 핵심 개념을 표준 용어로 고정.
이후 모든 슬라이드 콘텐츠 생성에서 *같은 개념 = 같은 단어* 보장.

도메인 용어 (ctx.domain.glossary) + 분석 표준 용어를 합쳐 사전 구축.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from outputs.context.schema import ReportContext

# ==============================================================
# 표준 동의어 → canonical 매핑
# ==============================================================

_SYNONYMS: dict[str, str] = {
    # 분석 일반
    "유저": "사용자",
    "어카운트": "계정",
    "이반": "이탈",
    "해지": "이탈",
    "탈퇴": "이탈",
    "churn": "이탈",
    "고객 이반": "고객 이탈",
    # 메트릭
    "정확도": "Accuracy",
    "재현율": "Recall",
    "정밀도": "Precision",
    "에프원": "F1",
    "에이유씨": "AUC",
    # 모델
    "엑스지": "XGBoost",
    "라이트지비엠": "LightGBM",
    "캣부스트": "CatBoost",
    "프로펫": "Prophet",
    "아리마": "ARIMA",
    # 도메인
    "월간 활성 사용자": "MAU",
    "데일리 활성": "DAU",
}


# ==============================================================
# Terminology dataclass
# ==============================================================


@dataclass
class Terminology:
    canonical: dict[str, str] = field(default_factory=dict)  # concept → canonical_term
    aliases: dict[str, str] = field(default_factory=dict)  # synonym → canonical

    def normalize(self, text: str) -> str:
        """텍스트의 동의어를 canonical 로 치환."""
        if not text:
            return text
        out = text
        # 길이 긴 alias 부터 치환 (포함 관계 충돌 방지)
        for alias in sorted(self.aliases.keys(), key=len, reverse=True):
            canon = self.aliases[alias]
            if alias != canon and alias in out:
                out = out.replace(alias, canon)
        return out

    def to_dict(self) -> dict:
        return {"canonical": dict(self.canonical), "aliases": dict(self.aliases)}


# ==============================================================
# 빌더
# ==============================================================


def build_terminology(ctx: ReportContext) -> Terminology:
    """ReportContext 로부터 용어 사전 구축."""
    term = Terminology(aliases=dict(_SYNONYMS))

    # 도메인 용어집 — canonical 으로 등재
    for word, definition in (ctx.domain.glossary or {}).items():
        if word and isinstance(word, str):
            term.canonical[word] = word

    # 메트릭 이름 — canonical
    for mname in ctx.evaluation.metrics:
        term.canonical[mname] = mname

    # 모델 이름 — canonical
    if ctx.model_selection.chosen.get("name"):
        term.canonical[ctx.model_selection.chosen["name"]] = ctx.model_selection.chosen["name"]
    for c in ctx.model_selection.candidates:
        if c.name:
            term.canonical[c.name] = c.name

    return term


def audit_consistency(plan, term: Terminology) -> dict:
    """ReportPlan 의 슬라이드 콘텐츠에서 alias 가 그대로 등장하는지 감사.

    Returns:
        {slide_id → [violations: alias used instead of canonical]}
    """
    findings: dict[str, list[str]] = {}
    for sl in plan.all_slides():
        body = " ".join(sl.body_outline) + " " + (sl.so_what or "") + " " + (sl.title_ko or "")
        slide_findings: list[str] = []
        for alias, canon in term.aliases.items():
            if alias != canon and alias in body:
                slide_findings.append(f"{alias} → {canon}")
        if slide_findings:
            findings[sl.id] = slide_findings
    return findings


def apply_to_plan(plan, term: Terminology) -> None:
    """ReportPlan 의 모든 슬라이드에 사전 정규화 in-place 적용."""
    for sl in plan.all_slides():
        sl.so_what = term.normalize(sl.so_what)
        sl.title_ko = term.normalize(sl.title_ko)
        sl.body_outline = [term.normalize(b) for b in sl.body_outline]
        sl.speaker_notes_hint = term.normalize(sl.speaker_notes_hint)
