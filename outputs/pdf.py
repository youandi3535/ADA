"""outputs.pdf — OUT-02 PDF 상세 리포트 (reportlab). ADR-008 L2 reattach 통합."""

from __future__ import annotations

from typing import Any

from outputs.base import OutputGenerator, get_theme, reattach_pii


def _colored_para_style(styles: Any, name: str, base: str, rgb: tuple[int, int, int]) -> Any:
    from reportlab.lib.colors import Color
    from reportlab.lib.styles import ParagraphStyle

    r, g, b = rgb
    return ParagraphStyle(
        name=name,
        parent=styles[base],
        textColor=Color(r / 255.0, g / 255.0, b / 255.0),
    )


class PDFReportGenerator(OutputGenerator):
    output_code = "OUT-02"
    extension = "pdf"

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

        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            Image,
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )

        theme = get_theme(category)
        primary = theme["primary_rgb"]
        label_ko = theme["label_ko"]
        primary_color = colors.Color(primary[0] / 255.0, primary[1] / 255.0, primary[2] / 255.0)

        local = self._tmp()
        doc = SimpleDocTemplate(
            local, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm
        )
        styles = getSampleStyleSheet()
        title_style = _colored_para_style(styles, "TitleColored", "Title", primary)
        h2_style = _colored_para_style(styles, "H2Colored", "Heading2", primary)
        flow: list = []

        flow.append(Paragraph(f"ADA Report - {label_ko}", title_style))
        flow.append(Spacer(1, 1 * cm))
        flow.append(Paragraph(f"<b>Category:</b> {label_ko} ({category})", styles["Normal"]))
        flow.append(Paragraph(f"<b>Intent:</b> {user_intent or '-'}", styles["Normal"]))
        flow.append(Spacer(1, 0.5 * cm))

        flow.append(Paragraph("Insights", h2_style))
        flow.append(Paragraph((insights or "").replace("\n", "<br/>"), styles["BodyText"]))
        flow.append(PageBreak())

        flow.append(Paragraph("Best Model", h2_style))
        bm = best_model or {}
        flow.append(Paragraph(f"Model: <b>{bm.get('model_name')}</b>", styles["BodyText"]))
        for k, v in (bm.get("metrics") or {}).items():
            txt = f"{k}: {v:.4f}" if isinstance(v, float) else f"{k}: {v}"
            flow.append(Paragraph(txt, styles["BodyText"]))

        flow.append(PageBreak())
        flow.append(Paragraph("EDA Charts", h2_style))
        for chart in eda_charts[:6]:
            tmp = self._download_chart(chart)
            if tmp:
                try:
                    flow.append(Image(tmp, width=15 * cm, height=8 * cm))
                    flow.append(Spacer(1, 0.5 * cm))
                except Exception:
                    continue

        extras = self._call_extras(state, ctx={"output_code": self.output_code, "category": category})
        if any(extras.get(k) for k in ("charts", "tables", "text_blocks")):
            flow.append(PageBreak())
            flow.append(Paragraph(f"[{label_ko}] Category Analysis", h2_style))

            for chart in extras.get("charts", [])[:4]:
                tmp = self._download_chart(chart)
                if tmp:
                    try:
                        flow.append(Image(tmp, width=15 * cm, height=8 * cm))
                        flow.append(Spacer(1, 0.4 * cm))
                    except Exception:
                        continue

            for tbl in extras.get("tables", [])[:3]:
                title = str(tbl.get("title", "Table"))
                flow.append(Paragraph(f"<b>{title}</b>", styles["BodyText"]))
                try:
                    rows = list(tbl.get("rows", []))
                    cols = list(tbl.get("columns") or (list(rows[0].keys()) if rows else []))
                    if cols and rows:
                        data: list[list[Any]] = [list(cols)]
                        for row in rows[:15]:
                            data.append([str(row.get(c, "")) for c in cols])
                        t = Table(data, hAlign="LEFT")
                        t.setStyle(
                            TableStyle(
                                [
                                    ("BACKGROUND", (0, 0), (-1, 0), primary_color),
                                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                                ]
                            )
                        )
                        flow.append(t)
                        flow.append(Spacer(1, 0.4 * cm))
                except Exception:
                    continue

            for text_block in extras.get("text_blocks", [])[:3]:
                safe_block = reattach_pii(state, str(text_block))
                flow.append(Paragraph(safe_block.replace("\n", "<br/>"), styles["BodyText"]))
                flow.append(Spacer(1, 0.3 * cm))

        flow.append(PageBreak())
        flow.append(Paragraph("Evaluation", h2_style))
        ev = eval_result or {}
        flow.append(Paragraph(f"passed: <b>{ev.get('passed')}</b>", styles["BodyText"]))
        flow.append(Paragraph(ev.get("rationale", ""), styles["BodyText"]))

        doc.build(flow)
        return self._upload(local)
