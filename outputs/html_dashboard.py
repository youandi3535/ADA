"""outputs.html_dashboard — OUT-04 정적 단일 파일 대시보드. ADR-008 L2 reattach 통합.

HJ-4 (2026-06-05) — `_call_extras` 통합. 카테고리 핸들러의 build/assets 결과
(charts·tables·text_blocks) 를 base64 inline 이미지·HTML 표·텍스트 블록으로 임베드.
"""

from __future__ import annotations

import base64
import html as html_lib
import json
from typing import Any

from outputs.base import OutputGenerator, reattach_pii


def _esc(s: Any) -> str:
    """HTML 본문 escape (스크립트/태그 주입 방어)."""
    return html_lib.escape("" if s is None else str(s))


class DashboardArtifactGenerator(OutputGenerator):
    output_code = "OUT-04"
    extension = "html"

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
        # ADR-008 L2 — PII 마스킹
        insights = reattach_pii(state, insights)
        user_intent = reattach_pii(state, user_intent)
        if eval_result:
            eval_result = {**eval_result, "rationale": reattach_pii(state, eval_result.get("rationale"))}

        from outputs import CATEGORY_COLORS

        # HJ — Method B: eda_charts + extras['charts'] 를 한 번에 raw bytes 로 병렬 다운로드.
        # HTML 임베드는 base64 inline 이라 파일 시스템 우회.
        # HJ-4 — 카테고리 핸들러 extras (charts/tables/text_blocks)
        extras = self._call_extras(state, ctx={"output_code": self.output_code, "category": category})
        eda_paths = [c for c in eda_charts[:4] if isinstance(c, str)]
        extras_paths = [c for c in extras.get("charts", [])[:4] if isinstance(c, str)]
        all_bytes = self._download_chart_bytes_parallel(eda_paths + extras_paths)
        eda_bytes = all_bytes[: len(eda_paths)]
        extras_bytes = all_bytes[len(eda_paths) :]

        chart_imgs = [base64.b64encode(b).decode("ascii") for b in eda_bytes if b]
        extras_chart_imgs = [base64.b64encode(b).decode("ascii") for b in extras_bytes if b]

        extras_charts_html = "".join(
            f"<div class='chart'><img src='data:image/png;base64,{b64}' /></div>" for b64 in extras_chart_imgs
        )

        def _render_extras_table(tbl: dict) -> str:
            title = _esc(tbl.get("title", ""))
            cols = tbl.get("columns") or []
            rows = tbl.get("rows") or []
            head = "".join(f"<th>{_esc(c)}</th>" for c in cols)
            body_rows = []
            for r in rows[:10]:
                if isinstance(r, dict):
                    cells = "".join(f"<td>{_esc(r.get(c, ''))}</td>" for c in cols)
                else:
                    cells = "".join(f"<td>{_esc(v)}</td>" for v in r)
                body_rows.append(f"<tr>{cells}</tr>")
            return (
                f"<div class='extras-table'><h3>{title}</h3>"
                f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table></div>"
            )

        extras_tables_html = "".join(_render_extras_table(t) for t in extras.get("tables", [])[:3])
        extras_text_html = "".join(
            f"<p class='extras-text'>{_esc(reattach_pii(state, str(b))).replace(chr(10), '<br>')}</p>"
            for b in extras.get("text_blocks", [])[:3]
        )

        bm = best_model or {}
        ev = eval_result or {}
        metrics = bm.get("metrics") or {}
        accent = CATEGORY_COLORS.get(category, "#2563eb")

        metric_rows = "".join(
            f"<tr><td>{k}</td><td>{v if isinstance(v, str) else round(v, 4) if v is not None else ''}</td></tr>"
            for k, v in metrics.items()
        )
        charts_html = "".join(
            f"<div class='chart'><img src='data:image/png;base64,{b64}' /></div>" for b64 in chart_imgs
        )

        chart_labels = [k for k, v in metrics.items() if isinstance(v, (int, float))]
        chart_values = [round(float(metrics[k]), 4) for k in chart_labels]

        html = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>ADA 대시보드 — {self.job_id}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0"></script>
<style>
  body {{ font-family: -apple-system,sans-serif; max-width: 1100px; margin: 24px auto; color:#111; }}
  header {{ border-left: 6px solid {accent}; padding-left: 12px; }}
  h1 {{ margin: 0; }}
  table {{ border-collapse: collapse; }}
  td, th {{ padding: 6px 12px; border-bottom: 1px solid #eee; }}
  .chart img {{ max-width: 100%; margin: 10px 0; border: 1px solid #eee; }}
  section {{ margin: 24px 0; }}
  .pill {{ display:inline-block; padding:4px 10px; border-radius:999px; background:{accent};
           color:#fff; font-size:12px; }}
  .extras-text {{ padding: 10px 14px; margin: 8px 0; background: #f9fafb;
                  border-left: 4px solid {accent}; white-space: pre-wrap; }}
  .extras-table h3 {{ margin: 12px 0 6px; font-size: 14px; color: #374151; }}
</style>
</head><body>
<header>
  <h1>ADA 자동 분석 결과</h1>
  <p><span class="pill">{category}</span> &nbsp; 의도: {user_intent or "미지정"}</p>
</header>

<section>
  <h2>핵심 인사이트</h2>
  <p>{(insights or "").replace(chr(10), "<br>")}</p>
</section>

<section>
  <h2>Best Model: {bm.get("model_name", "-")}</h2>
  <table><tbody>{metric_rows}</tbody></table>
  <canvas id="metricsChart" height="120"></canvas>
</section>

<section>
  <h2>EDA Charts</h2>
  {charts_html}
</section>

<section>
  <h2>카테고리 분석 ({_esc(category)})</h2>
  {extras_text_html}
  {extras_charts_html}
  {extras_tables_html}
</section>

<section>
  <h2>평가</h2>
  <p>passed: <b>{ev.get("passed")}</b><br>{ev.get("rationale", "")}</p>
</section>

<script>
new Chart(document.getElementById('metricsChart'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps(chart_labels)},
    datasets: [{{ label: 'metrics', data: {json.dumps(chart_values)},
                  backgroundColor: '{accent}' }}]
  }},
  options: {{ scales: {{ y: {{ beginAtZero: true }} }} }}
}});
</script>
</body></html>
"""
        local = self._tmp()
        with open(local, "w", encoding="utf-8") as f:
            f.write(html)
        return self._upload(local)
