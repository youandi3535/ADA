"""outputs.carriers.script_carrier — OUT-03 발표 대본 (Phase 6).

ReportPlan + ReportContext → 한국어 발표 대본 (.txt).
이전 outputs/script.py 대체.
"""

from __future__ import annotations

from pathlib import Path

from outputs.architect.plan import ReportPlan
from outputs.context.schema import ReportContext


def generate_script(plan: ReportPlan, ctx: ReportContext, output_path: str | Path) -> str:
    """발표 대본 .txt 생성. 출력 파일 경로 반환."""
    lines: list[str] = []
    intent = ctx.meta.user_intent or "자동 분석"
    chosen = ctx.model_selection.chosen.get("name", "-")
    pm = ctx.evaluation.primary_metric or {}

    lines.append(f"[ADA 발표 대본 — {plan.skeleton}]\n")
    lines.append(f"안녕하세요. 오늘은 '{intent}' 주제로 {ctx.meta.category} 분석 결과를 공유드리겠습니다.\n")
    lines.append(f"먼저 결론입니다. 최적 모델로 {chosen} 를 선정했고, 주요 지표는 다음과 같습니다.")
    lines.append(f"  - {pm.get('name', '-')}: {pm.get('value', '-')}")
    for k, m in list(ctx.evaluation.metrics.items())[:3]:
        if k != pm.get("name"):
            lines.append(f"  - {k}: {m.get('value')}")
    lines.append("")

    # 섹션별 흐름
    for sec in plan.sections:
        if sec.kind in ("cover", "closing"):
            continue
        lines.append(f"\n【{sec.title}】")
        for sl in sec.slides:
            if sl.role == "meta":
                continue
            if sl.so_what:
                lines.append(f"  • {sl.so_what}")

    # 인사이트 본문 인용
    if ctx.meta.user_intent:
        lines.append("")
        lines.append("핵심 인사이트는 다음과 같습니다.")

    # 마무리
    lines.append("")
    lines.append("이상으로 발표를 마치겠습니다. 질문 받겠습니다. 감사합니다.")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return str(out)
