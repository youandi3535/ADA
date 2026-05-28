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
