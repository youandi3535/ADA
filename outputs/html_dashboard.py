"""outputs.html_dashboard — OUT-04 정적 단일 파일 대시보드. ADR-008 L2 reattach 통합."""

from __future__ import annotations

import base64
import json
from typing import Any

from outputs.base import OutputGenerator, reattach_pii


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

        chart_imgs = []
        try:
            from tools.minio_tool import get_minio_client

            mc = get_minio_client()
            for c in eda_charts[:4]:
                key = c.replace(f"s3://{mc.bucket}/", "") if c.startswith("s3://") else c
                try:
                    body = mc.download_bytes(key)
                    chart_imgs.append(base64.b64encode(body).decode("ascii"))
                except Exception:
                    continue
        except Exception:
            pass

        # Day 9 H1 — 카테고리 핸들러 extras (분석 차트/테이블/텍스트)
        extras = self._call_extras(state, ctx={"output_code": self.output_code, "category": category})
        extra_b64: list[str] = []
        try:
            from tools.minio_tool import get_minio_client

            mc2 = get_minio_client()
            for c in (extras.get("charts") or [])[:8]:
                key = c.replace(f"s3://{mc2.bucket}/", "") if isinstance(c, str) and c.startswith("s3://") else c
                try:
                    body = mc2.download_bytes(key)
                    extra_b64.append(base64.b64encode(body).decode("ascii"))
                except Exception:
                    continue
        except Exception:
            pass
        extra_charts_html = "".join(
            f"<div class='chart'><img src='data:image/png;base64,{b64}' /></div>" for b64 in extra_b64
        )

        def _render_table(tbl: dict[str, Any]) -> str:
            cols = tbl.get("columns") or []
            rows = tbl.get("rows") or []
            head = "".join(f"<th>{c}</th>" for c in cols)
            body_rows = []
            for r in rows[:15]:
                cells = r if isinstance(r, (list, tuple)) else [r.get(c, "") for c in cols]
                body_rows.append("<tr>" + "".join(f"<td>{reattach_pii(state, str(x))}</td>" for x in cells) + "</tr>")
            title = reattach_pii(state, str(tbl.get("title", "")))
            return f"<h3>{title}</h3><table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"

        extra_tables_html = "".join(_render_table(t) for t in (extras.get("tables") or [])[:5])
        extra_text_html = "".join(
            f"<p>{reattach_pii(state, str(t))}</p>" for t in (extras.get("text_blocks") or [])[:5]
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
  <h2>모델 분석 차트</h2>
  {extra_charts_html or "<p><em>표시할 분석 차트가 없습니다.</em></p>"}
  {extra_tables_html}
  {extra_text_html}
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
