"""outputs.pdf — OUT-02 PDF 상세 리포트 (reportlab)."""
from __future__ import annotations

from typing import Any

from outputs.base import OutputGenerator


class PDFReportGenerator(OutputGenerator):
    output_code = "OUT-02"
    extension = "pdf"

    def generate(self, *, insights: str, best_model: dict[str, Any],
                 eda_charts: list[str], category: str, user_intent: str,
                 eval_result: dict[str, Any] | None) -> str:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
        )

        local = self._tmp()
        doc = SimpleDocTemplate(local, pagesize=A4,
                                 leftMargin=2 * cm, rightMargin=2 * cm,
                                 topMargin=2 * cm, bottomMargin=2 * cm)
        styles = getSampleStyleSheet()
        flow: list = []

        flow.append(Paragraph("ADA 자동 분석 보고서", styles["Title"]))
        flow.append(Spacer(1, 1 * cm))
        flow.append(Paragraph(f"<b>카테고리:</b> {category}", styles["Normal"]))
        flow.append(Paragraph(f"<b>사용자 의도:</b> {user_intent or '미지정'}",
                              styles["Normal"]))
        flow.append(Spacer(1, 0.5 * cm))

        flow.append(Paragraph("핵심 인사이트", styles["Heading2"]))
        flow.append(Paragraph((insights or "").replace("\n", "<br/>"), styles["BodyText"]))
        flow.append(PageBreak())

        flow.append(Paragraph("Best Model", styles["Heading2"]))
        bm = best_model or {}
        flow.append(Paragraph(f"모델: <b>{bm.get('model_name')}</b>",
                              styles["BodyText"]))
        for k, v in (bm.get("metrics") or {}).items():
            txt = f"{k}: {v:.4f}" if isinstance(v, float) else f"{k}: {v}"
            flow.append(Paragraph(txt, styles["BodyText"]))

        flow.append(PageBreak())
        flow.append(Paragraph("EDA Charts", styles["Heading2"]))
        for chart in eda_charts[:6]:
            try:
                import tempfile
                from tools.minio_tool import get_minio_client
                mc = get_minio_client()
                key = chart.replace(f"s3://{mc.bucket}/", "") if chart.startswith("s3://") else chart
                body = mc.download_bytes(key)
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png").name
                with open(tmp, "wb") as f:
                    f.write(body)
                flow.append(Image(tmp, width=15 * cm, height=8 * cm))
                flow.append(Spacer(1, 0.5 * cm))
            except Exception:
                continue

        flow.append(PageBreak())
        flow.append(Paragraph("평가", styles["Heading2"]))
        ev = eval_result or {}
        flow.append(Paragraph(f"passed: <b>{ev.get('passed')}</b>", styles["BodyText"]))
        flow.append(Paragraph(ev.get("rationale", ""), styles["BodyText"]))

        doc.build(flow)
        return self._upload(local)
