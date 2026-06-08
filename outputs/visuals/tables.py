"""outputs.visuals.tables — 비교 표 5 변형 (Phase 3, Part 9-4).

각 함수는 표 spec dict 반환 — carrier 가 PPT table / PDF Table / HTML table 로 렌더.

5 변형:
    feature_matrix    — 행=후보, 열=기준, 셀=값/체크/점수
    score_card        — 가중치 컬럼 + 가중 합계 행
    before_after      — 좌 Before, 우 After, 가운데 Δ
    risk_register     — 리스크·확률·영향·대응·소유자
    pros_cons         — 좌 장점 / 우 단점 (박스)
"""

from __future__ import annotations

from typing import Any

from outputs.visuals.visual_dna import VisualDNA


def feature_matrix(
    *,
    columns: list[str],
    rows: list[dict[str, Any]],
    title: str = "비교 매트릭스",
    highlight_winner_col: str | None = None,
    dna: VisualDNA | None = None,
) -> dict[str, Any]:
    """행=후보, 열=기준 표.

    Args:
        rows: [{"name": ..., col1: val, col2: val, ...}]
    """
    return {
        "type": "table_feature_matrix",
        "title": title,
        "columns": ["", *columns],  # 첫 컬럼은 이름
        "rows": [[r.get("name", "")] + [str(r.get(c, "-")) for c in columns] for r in rows],
        "header_color": (dna.palette.get("primary") if dna else "#2563eb") or "#2563eb",
        "highlight_winner_col": highlight_winner_col,
    }


def score_card(
    *,
    criteria: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    title: str = "점수표",
    dna: VisualDNA | None = None,
) -> dict[str, Any]:
    """가중치 기반 점수표.

    Args:
        criteria: [{"name", "weight": 0~1}]
        candidates: [{"name", "scores": {criterion_name: score 0~1}}]
    """
    # 가중 합 계산
    rows: list[list[Any]] = []
    for cand in candidates:
        scores = cand.get("scores", {})
        weighted_sum = 0.0
        row = [cand.get("name", "")]
        for c in criteria:
            cname = c.get("name", "")
            cweight = float(c.get("weight", 0))
            s = float(scores.get(cname, 0))
            weighted_sum += s * cweight
            row.append(f"{s:.2f}")
        row.append(f"{weighted_sum:.2f}")
        rows.append(row)
    # 정렬 (가중 합 내림차순)
    rows.sort(key=lambda r: float(r[-1]), reverse=True)
    return {
        "type": "table_score_card",
        "title": title,
        "columns": ["후보"] + [f"{c['name']} ({c['weight'] * 100:.0f}%)" for c in criteria] + ["가중 합"],
        "rows": rows,
        "header_color": (dna.palette.get("primary") if dna else "#2563eb") or "#2563eb",
        "winner_row_index": 0,  # 정렬 후 1위
    }


def before_after(
    *,
    items: list[dict[str, Any]],
    title: str = "Before / After",
    dna: VisualDNA | None = None,
) -> dict[str, Any]:
    """Before/After 비교.

    Args:
        items: [{"metric", "before", "after", "delta"}]
    """
    rows = []
    for it in items:
        b = it.get("before")
        a = it.get("after")
        delta = it.get("delta")
        if delta is None and isinstance(b, (int, float)) and isinstance(a, (int, float)):
            delta = a - b
        rows.append(
            [
                str(it.get("metric", "")),
                str(b) if b is not None else "-",
                str(a) if a is not None else "-",
                (
                    f"+{delta:.2f}"
                    if isinstance(delta, (int, float)) and delta > 0
                    else f"{delta:.2f}"
                    if isinstance(delta, (int, float))
                    else "-"
                ),
            ]
        )
    return {
        "type": "table_before_after",
        "title": title,
        "columns": ["지표", "Before", "After", "Δ"],
        "rows": rows,
        "header_color": (dna.palette.get("primary") if dna else "#2563eb") or "#2563eb",
        "success_color": (dna.semantic.get("success") if dna else "#16A34A") or "#16A34A",
        "danger_color": (dna.semantic.get("danger") if dna else "#DC2626") or "#DC2626",
    }


def risk_register(
    *,
    risks: list[dict[str, Any]],
    title: str = "리스크 등록부",
    dna: VisualDNA | None = None,
) -> dict[str, Any]:
    """리스크·확률·영향·대응·소유자 표.

    Args:
        risks: [{"description","probability","impact","mitigation","owner","due"}]
    """
    rows = []
    for r in risks:
        rows.append(
            [
                str(r.get("description", "")),
                str(r.get("probability", "-")),
                str(r.get("impact", "-")),
                str(r.get("mitigation", "-")),
                str(r.get("owner", "(미지정)")),
                str(r.get("due", "-")),
            ]
        )
    return {
        "type": "table_risk_register",
        "title": title,
        "columns": ["리스크", "확률", "영향", "대응", "소유자", "기한"],
        "rows": rows,
        "header_color": (dna.semantic.get("warning") if dna else "#D97706") or "#D97706",
    }


def pros_cons(
    *,
    pros: list[str],
    cons: list[str],
    title: str = "장단점",
    dna: VisualDNA | None = None,
) -> dict[str, Any]:
    """좌 장점·우 단점 박스."""
    return {
        "type": "table_pros_cons",
        "title": title,
        "pros": list(pros)[:5],
        "cons": list(cons)[:5],
        "pros_color": (dna.semantic.get("success") if dna else "#16A34A") or "#16A34A",
        "cons_color": (dna.semantic.get("danger") if dna else "#DC2626") or "#DC2626",
    }
