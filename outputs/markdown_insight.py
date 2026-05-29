"""outputs.markdown_insight — OUT-07 인사이트 정리 (.md). ADR-008 L2 reattach 통합."""

from __future__ import annotations

from typing import Any

from outputs.base import OutputGenerator, reattach_pii


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
        extras = self._call_extras(state, ctx={"output_code": self.output_code, "category": category})
        extra_chart_lines = "\n".join(f"- {c}" for c in (extras.get("charts") or [])) or "_(분석 차트 없음)_"

        def _md_table(tbl: dict[str, Any]) -> str:
            cols = tbl.get("columns") or []
            rows = tbl.get("rows") or []
            if not cols:
                return ""
            head = "| " + " | ".join(str(c) for c in cols) + " |"
            sep = "| " + " | ".join("---" for _ in cols) + " |"
            body = []
            for r in rows[:15]:
                cells = r if isinstance(r, (list, tuple)) else [r.get(c, "") for c in cols]
                body.append("| " + " | ".join(reattach_pii(state, str(x)) for x in cells) + " |")
            title = reattach_pii(state, str(tbl.get("title", "")))
            return f"**{title}**\n\n" + "\n".join([head, sep, *body])

        extra_tables_md = "\n\n".join(t for t in (_md_table(x) for x in (extras.get("tables") or [])) if t)
        extra_text_md = "\n\n".join(reattach_pii(state, str(t)) for t in (extras.get("text_blocks") or []))
        metric_lines = "\n".join(
            f"- **{k}**: {v if isinstance(v, str) else (f'{v:.4f}' if isinstance(v, float) else v)}"
            for k, v in metrics.items()
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

## EDA Charts (MinIO 경로)
{chr(10).join(f"- {c}" for c in eda_charts) if eda_charts else "_(차트 없음)_"}

## 모델 분석 차트
{extra_chart_lines}

{extra_tables_md}

{extra_text_md}
"""
        local = self._tmp()
        with open(local, "w", encoding="utf-8") as f:
            f.write(md)
        return self._upload(local)
