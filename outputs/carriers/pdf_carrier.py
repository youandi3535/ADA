"""PDF carrier - KO CID font + Visual PNG embed."""

from __future__ import annotations

from pathlib import Path

from outputs.architect.plan import ReportPlan
from outputs.context.schema import ReportContext

_FONT_OK = False
_KS = "HYSMyeongJo-Medium"
_KG = "HYGothic-Medium"


def _reg():
    global _FONT_OK
    if _FONT_OK:
        return
    from reportlab.lib import fonts as F
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    for n in (_KS, _KG):
        if n not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(UnicodeCIDFont(n))
        pdfmetrics.registerFontFamily(n, normal=n, bold=n, italic=n, boldItalic=n)
        # ps2tt 가 lowercase 키로 검색 → 대문자 폰트명 반환 (doc 의 internal 폰트명과 매칭)
        ln = n.lower()
        F._ps2tt_map[ln] = (n, 0, 0)
        for b in (0, 1):
            for i in (0, 1):
                F._tt2ps_map[(n, b, i)] = n
    _FONT_OK = True


def _fv(v):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.4f}" if 0 < abs(v) < 1 else f"{v:,.2f}"
    return str(v)


def generate_pdf(plan: ReportPlan, ctx: ReportContext, output_path) -> str:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle as PS
        from reportlab.lib.units import cm
        from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except Exception:
        return _fallback(plan, output_path)
    _reg()
    from outputs.style.classification import classification_treatment
    from outputs.style.palette import get_palette, hex_to_rgb
    from outputs.visuals.render import render_visual_to_png

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    pal = get_palette(ctx.meta.category)
    primary = colors.Color(*(c / 255 for c in hex_to_rgb(pal["primary"])))
    muted = colors.Color(0.39, 0.45, 0.55)
    ink = colors.HexColor("#0F172A")
    treat = classification_treatment(ctx.meta.classification)

    title = PS("T", fontName=_KG, fontSize=22, leading=28, textColor=primary, spaceAfter=8)
    h1 = PS("H1", fontName=_KG, fontSize=18, leading=24, textColor=primary, spaceBefore=10, spaceAfter=6)
    h2 = PS("H2", fontName=_KG, fontSize=14, leading=20, textColor=primary, spaceBefore=8, spaceAfter=4)
    sw = PS("SW", fontName=_KG, fontSize=12, leading=18, textColor=primary, leftIndent=6)
    body = PS("B", fontName=_KS, fontSize=11, leading=16, textColor=ink)
    bul = PS("BL", fontName=_KS, fontSize=11, leading=16, textColor=ink, leftIndent=14, firstLineIndent=-8)
    cap = PS("CP", fontName=_KS, fontSize=9, leading=12, textColor=muted)

    doc = SimpleDocTemplate(
        str(out), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm
    )
    flow = []
    intent = ctx.meta.user_intent or "분석 보고서"
    chosen = (ctx.model_selection.chosen or {}).get("name", "-")
    pm = ctx.evaluation.primary_metric or {}

    flow.append(Paragraph(intent, title))
    flow.append(Spacer(1, 0.3 * cm))
    flow.append(
        Paragraph(
            f"카테고리 : {ctx.meta.category}     모델 : {chosen}     {pm.get('name', '지표')} : {_fv(pm.get('value'))}",
            body,
        )
    )
    flow.append(Paragraph(f"분류 {ctx.meta.classification} · 생성 {(ctx.meta.generated_at or '')[:10]}", cap))
    flow.append(Spacer(1, 1.5 * cm))

    if plan.narrative_thread.setup:
        flow.append(Paragraph("Executive Summary", h1))
        flow.append(Paragraph(f"현황 — {plan.narrative_thread.setup}", body))
        flow.append(Paragraph(f"문제 — {plan.narrative_thread.conflict}", body))
        flow.append(Paragraph(f"해결 — {plan.narrative_thread.resolution}", body))
        flow.append(Spacer(1, 0.5 * cm))

    if ctx.evaluation.metrics:
        flow.append(Paragraph("핵심 지표", h2))
        data = [["지표", "값"]]
        for k, m in list(ctx.evaluation.metrics.items())[:6]:
            data.append([k, _fv(m.get("value"))])
        t = Table(data, colWidths=[8 * cm, 4 * cm])
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), primary),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), _KG),
                    ("FONTNAME", (0, 1), (-1, -1), _KS),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                    ("ALIGN", (1, 1), (1, -1), "RIGHT"),
                ]
            )
        )
        flow.append(t)
    flow.append(PageBreak())

    for sec in plan.sections:
        if sec.id == "backup" or sec.kind == "cover":
            continue
        flow.append(Paragraph(sec.title, h1))
        for sl in sec.slides:
            if sl.role == "meta" and sl.layout in ("cover", "agenda", "closing"):
                continue
            flow.append(Paragraph(sl.title_ko or sl.id, h2))
            if sl.so_what:
                flow.append(Paragraph(f"핵심 — {sl.so_what}", sw))
            for b in sl.body_outline:
                flow.append(Paragraph(f"• {b}", bul))
            vs = sl.visual_spec
            if vs and vs.type and vs.type != "text_only":
                try:
                    png = render_visual_to_png(vs, ctx, slide=sl)
                    if png:
                        from PIL import Image as PI

                        with PI.open(png) as im:
                            ar = im.width / im.height
                        w_cm = 16.0
                        h_cm = w_cm / ar
                        if h_cm > 10.0:
                            h_cm = 10.0
                            w_cm = h_cm * ar
                        flow.append(Spacer(1, 0.3 * cm))
                        flow.append(Image(png, width=w_cm * cm, height=h_cm * cm))
                        if vs.caption:
                            flow.append(Paragraph(vs.caption, cap))
                except Exception:
                    pass
            flow.append(Spacer(1, 0.4 * cm))
        flow.append(PageBreak())

    def _foot(canvas, dc):
        canvas.saveState()
        canvas.setFont(_KS, 9)
        canvas.setFillColor(muted)
        canvas.drawString(2 * cm, 1 * cm, f"ADA · {intent[:30]}")
        canvas.drawCentredString(A4[0] / 2, 1 * cm, f"{(ctx.meta.generated_at or '')[:10]}  p.{dc.page}")
        canvas.setFillColor(colors.HexColor(treat.get("footer_color", "#334155")))
        canvas.drawRightString(A4[0] - 2 * cm, 1 * cm, treat.get("footer_text", "INTERNAL"))
        canvas.restoreState()

    doc.build(flow, onFirstPage=_foot, onLaterPages=_foot)
    return str(out)


def _fallback(plan, output_path):
    out = Path(str(output_path) + ".txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"[PDF Fallback {plan.skeleton}]", encoding="utf-8")
    return str(out)
