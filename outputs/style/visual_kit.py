"""outputs.style.visual_kit - PPT shape/gradient helpers for consulting-grade design."""

from __future__ import annotations


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def add_rect(slide, x_cm, y_cm, w_cm, h_cm, hex_color, *, line=False):
    """Solid filled rectangle. Returns shape."""
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Cm

    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Cm(x_cm), Cm(y_cm), Cm(w_cm), Cm(h_cm))
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor(*hex_to_rgb(hex_color))
    if not line:
        shape.line.fill.background()
    return shape


def add_rounded_rect(slide, x_cm, y_cm, w_cm, h_cm, hex_color, *, line_hex=None):
    """Rounded rectangle - good for KPI cards / pills."""
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Cm

    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Cm(x_cm), Cm(y_cm), Cm(w_cm), Cm(h_cm))
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor(*hex_to_rgb(hex_color))
    if line_hex:
        shape.line.color.rgb = RGBColor(*hex_to_rgb(line_hex))
        shape.line.width = Cm(0.02)
    else:
        shape.line.fill.background()
    return shape


def add_oval(slide, x_cm, y_cm, w_cm, h_cm, hex_color):
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Cm

    shape = slide.shapes.add_shape(MSO_SHAPE.OVAL, Cm(x_cm), Cm(y_cm), Cm(w_cm), Cm(h_cm))
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor(*hex_to_rgb(hex_color))
    shape.line.fill.background()
    return shape


def add_chevron(slide, x_cm, y_cm, w_cm, h_cm, hex_color):
    """Right-pointing arrow chevron - for process flow."""
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Cm

    shape = slide.shapes.add_shape(MSO_SHAPE.CHEVRON, Cm(x_cm), Cm(y_cm), Cm(w_cm), Cm(h_cm))
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor(*hex_to_rgb(hex_color))
    shape.line.fill.background()
    return shape


def set_text(
    shape, text: str, *, font="Malgun Gothic", size_pt=14, bold=False, color_hex="#0F172A", align="left", vcenter=True
):
    """Set text inside a shape with KO font."""
    from pptx.dml.color import RGBColor
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Pt

    tf = shape.text_frame
    tf.word_wrap = True
    if vcenter:
        try:
            tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        except Exception:
            pass
    tf.text = text
    for p in tf.paragraphs:
        if align == "center":
            p.alignment = PP_ALIGN.CENTER
        elif align == "right":
            p.alignment = PP_ALIGN.RIGHT
        else:
            p.alignment = PP_ALIGN.LEFT
        for r in p.runs:
            r.font.size = Pt(size_pt)
            r.font.bold = bold
            r.font.color.rgb = RGBColor(*hex_to_rgb(color_hex))
            r.font.name = font
            _ea_font(r, font)


def _ea_font(run, family: str) -> None:
    """Set east-asian (Korean) typeface explicitly."""
    try:
        from lxml import etree
        from pptx.oxml.ns import qn

        rPr = run._r.get_or_add_rPr()
        for ea in rPr.findall(qn("a:ea")):
            rPr.remove(ea)
        ea = etree.SubElement(rPr, qn("a:ea"))
        ea.set("typeface", family)
    except Exception:
        pass


def add_text_box(slide, x_cm, y_cm, w_cm, h_cm, text: str, **style):
    """Convenience: textbox + set_text."""
    from pptx.util import Cm

    tx = slide.shapes.add_textbox(Cm(x_cm), Cm(y_cm), Cm(w_cm), Cm(h_cm))
    set_text(tx, text, **style)
    return tx


def add_horizontal_rule(slide, x_cm, y_cm, w_cm, hex_color, *, h_cm=0.05):
    """Thin horizontal divider line."""
    return add_rect(slide, x_cm, y_cm, w_cm, h_cm, hex_color)


def add_vertical_accent(slide, x_cm, y_cm, h_cm, hex_color, *, w_cm=0.18):
    """Vertical color bar - for slide title left-side accent."""
    return add_rect(slide, x_cm, y_cm, w_cm, h_cm, hex_color)


def add_gradient_rect(slide, x_cm, y_cm, w_cm, h_cm, hex_start, hex_end, *, angle=0):
    """Linear gradient rectangle via OXML."""
    from lxml import etree
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.oxml.ns import qn
    from pptx.util import Cm

    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Cm(x_cm), Cm(y_cm), Cm(w_cm), Cm(h_cm))
    shape.line.fill.background()
    sp = shape.fill._xPr
    for tag in ("a:noFill", "a:solidFill", "a:gradFill"):
        for el in sp.findall(qn(tag)):
            sp.remove(el)
    grad = etree.SubElement(sp, qn("a:gradFill"))
    grad.set("flip", "none")
    grad.set("rotWithShape", "1")
    gsLst = etree.SubElement(grad, qn("a:gsLst"))
    for pos, hx in ((0, hex_start), (100000, hex_end)):
        gs = etree.SubElement(gsLst, qn("a:gs"))
        gs.set("pos", str(pos))
        clr = etree.SubElement(gs, qn("a:srgbClr"))
        clr.set("val", hx.lstrip("#"))
    lin = etree.SubElement(grad, qn("a:lin"))
    lin.set("ang", str(int(angle * 60000)))
    lin.set("scaled", "1")
    etree.SubElement(grad, qn("a:tileRect"))
    return shape


def add_glyph(slide, x_cm, y_cm, w_cm, h_cm, glyph, color_hex="#FFFFFF", size_pt=20, bg_color=None):
    """Unicode glyph icon with optional circular background."""
    if bg_color:
        add_oval(slide, x_cm, y_cm, w_cm, h_cm, bg_color)
    add_text_box(
        slide,
        x_cm,
        y_cm,
        w_cm,
        h_cm,
        glyph,
        size_pt=size_pt,
        color_hex=color_hex,
        align="center",
        vcenter=True,
        bold=True,
    )


def add_triangle(slide, x_cm, y_cm, w_cm, h_cm, hex_color, *, direction="up"):
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Cm

    shape_map = {
        "up": MSO_SHAPE.ISOSCELES_TRIANGLE,
        "right": MSO_SHAPE.RIGHT_TRIANGLE,
        "diamond": MSO_SHAPE.DIAMOND,
        "hex": MSO_SHAPE.HEXAGON,
    }
    sh = shape_map.get(direction, MSO_SHAPE.ISOSCELES_TRIANGLE)
    shape = slide.shapes.add_shape(sh, Cm(x_cm), Cm(y_cm), Cm(w_cm), Cm(h_cm))
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor(*hex_to_rgb(hex_color))
    shape.line.fill.background()
    return shape


GLYPHS = {
    "data": "▦",
    "chart": "▲",
    "report": "▤",
    "model": "◆",
    "warn": "⚠",
    "ok": "✓",
    "no": "✗",
    "info": "ⓘ",
    "arrow_r": "▶",
    "arrow_d": "▼",
    "arrow_u": "▲",
    "star": "★",
    "hex": "⬢",
    "circle": "●",
    "diamond": "◆",
    "bulb": "✦",
    "target": "◎",
    "settings": "⚙",
    "shield": "▼",
}
