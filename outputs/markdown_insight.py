"""outputs.markdown_insight — OUT-07 인사이트 정리 (.md). ADR-008 L2 reattach 통합.

HJ-4 (2026-06-05) — `_call_extras` 통합. 카테고리 핸들러의 text_blocks (신뢰도 배지·권장 액션 등)
와 tables (예측표·성능표·fold 진단표) 를 markdown 으로 임베드.
"""

from __future__ import annotations

from typing import Any

from outputs.base import OutputGenerator, reattach_pii


def _render_extras_md_table(tbl: dict) -> str:
    """카테고리 extras table → GitHub-flavored Markdown."""
    title = str(tbl.get("title", ""))
    cols = list(tbl.get("columns") or [])
    rows = tbl.get("rows") or []
    if not cols or not rows:
        return ""
    head = "| " + " | ".join(str(c) for c in cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body_lines = []
    for r in rows[:10]:
        if isinstance(r, dict):
            cells = [str(r.get(c, "")) for c in cols]
        else:
            cells = [str(v) for v in r]
        body_lines.append("| " + " | ".join(cells) + " |")
    return f"\n### {title}\n\n{head}\n{sep}\n" + "\n".join(body_lines) + "\n"


class InsightSummaryGenerator(OutputGenerator):
    output_code = "OUT-07"
    extension = "md"

    def generate(
        self,
        *,
        insights: str,
        best_model: dict[str, Any],
        eda_charts: list[str],
        category: str,
        user_intent: str,
        eval_result: dict[str, Any] | None,
        state: Any = None,
    ) -> str:
        # ADR-008 L2 — 사용자 노출 직전 PII 마스킹
        insights = reattach_pii(state, insights)
        user_intent = reattach_pii(state, user_intent)
        if eval_result:
            eval_result = {**eval_result, "rationale": reattach_pii(state, eval_result.get("rationale"))}

        bm = best_model or {}
        metrics = bm.get("metrics") or {}
        metric_lines = "\n".join(
            f"- **{k}**: {v if isinstance(v, str) else (f'{v:.4f}' if isinstance(v, float) else v)}"
            for k, v in metrics.items()
        )

        # HJ-4 — 카테고리 extras
        extras = self._call_extras(state, ctx={"output_code": self.output_code, "category": category})
        extras_text_md = (
            "\n\n".join(reattach_pii(state, str(b)) for b in extras.get("text_blocks", [])[:3])
            or "_(카테고리 추가 분석 없음)_"
        )
        extras_tables_md = "".join(_render_extras_md_table(t) for t in extras.get("tables", [])[:3])
        extras_charts_md = (
            "\n".join(f"- {c}" for c in extras.get("charts", [])[:4])
            if extras.get("charts")
            else "_(카테고리 차트 없음)_"
        )

        md = f"""# ADA 분석 인사이트 — {self.job_id}

> 카테고리: **{category}** · 사용자 의도: {user_intent or "미지정"}

## 핵심 인사이트
{insights or "_(생성된 인사이트가 없습니다.)_"}

## Best Model
- **모델명**: `{bm.get("model_name", "-")}`
- **프레임워크**: {bm.get("framework", "-")}

### 지표
{metric_lines}

## 평가
- passed: **{(eval_result or {}).get("passed", "-")}**
- 근거: {(eval_result or {}).get("rationale", "-")}

## 카테고리 분석 ({category})

{extras_text_md}
{extras_tables_md}

### 카테고리 차트 (MinIO 경로)
{extras_charts_md}

## EDA Charts (MinIO 경로)
{chr(10).join(f"- {c}" for c in eda_charts) if eda_charts else "_(차트 없음)_"}
"""
        local = self._tmp()
        with open(local, "w", encoding="utf-8") as f:
            f.write(md)
        return self._upload(local)
