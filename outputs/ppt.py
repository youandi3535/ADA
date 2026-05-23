"""outputs.ppt — OUT-01 PowerPoint 발표자료 (python-pptx) + Day 9 카테고리 테마/훅."""

from __future__ import annotations

from typing import Any

from outputs.base import OutputGenerator, get_theme


def _set_title_color(slide: Any, rgb: tuple[int, int, int]) -> None:
    """슬라이드 제목에 RGB 색상 적용 (실패 시 silent skip)."""
    try:
        from pptx.dml.color import RGBColor

        for para in slide.shapes.title.text_frame.paragraphs:
            for run in para.runs:
                run.font.color.rgb = RGBColor(*rgb)
    except Exception:
        pass


def _set_background(slide: Any, rgb: tuple[int, int, int]) -> None:
    """슬라이드 배경 fill (subtle accent). 실패 시 skip."""
    try:
        from pptx.dml.color import RGBColor

        fill = slide.background.fill
        fill.solid()
        fill.fore_color.rgb = RGBColor(*rgb)
    except Exception:
        pass


class PresentationGenerator(OutputGenerator):
    output_code = "OUT-01"
    extension = "pptx"

    def generate(
        self,
        *,
        insights: str,
        best_model: dict[str, Any],
        eda_charts: list[str],
        category: str,
        user_intent: str,
        eval_result: dict[str, Any] | None,
        state: Any = None,  # Day 9 — 카테고리 핸들러 호출에 사용 (선택)
    ) -> str:
        from pptx import Presentation
        from pptx.util import Inches, Pt

        theme = get_theme(category)
        primary = theme["primary_rgb"]
        accent = theme["accent_rgb"]
        label_ko = theme["label_ko"]

        prs = Presentation()

        # 1) 표지 — 카테고리 라벨 + accent 배경 띠
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        slide.shapes.title.text = "ADA 자동 분석 보고서"
        slide.placeholders[1].text = f"카테고리: {label_ko} ({category})\n의도: {user_intent or '미지정'}"
        _set_title_color(slide, primary)

        # 2) 핵심 인사이트 — 제목 색상만 primary 적용 (본문은 가독성 유지)
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = "핵심 인사이트"
        _set_title_color(slide, primary)
        tf = slide.placeholders[1].text_frame
        tf.text = (insights or "")[:1500]
        for p in tf.paragraphs:
            for r in p.runs:
                r.font.size = Pt(18)

        # 3) Best Model
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = "Best Model"
        _set_title_color(slide, primary)
        body = slide.placeholders[1].text_frame
        bm = best_model or {}
        body.text = f"모델: {bm.get('model_name', '-')}"
        for k, v in (bm.get("metrics") or {}).items():
            p = body.add_paragraph()
            p.text = f"{k}: {v:.4f}" if isinstance(v, float) else f"{k}: {v}"

        # 4) EDA 차트
        for i, chart_path in enumerate(eda_charts[:4]):
            slide = prs.slides.add_slide(prs.slide_layouts[5])
            slide.shapes.title.text = f"EDA Chart #{i + 1}"
            _set_title_color(slide, primary)
            tmp = self._download_chart(chart_path)
            if tmp:
                try:
                    slide.shapes.add_picture(tmp, Inches(0.5), Inches(1.5), width=Inches(8))
                except Exception:
                    pass

        # 5) Day 9 — 카테고리 핸들러의 extras 임베드 (charts + tables + text_blocks)
        extras = self._call_extras(state, ctx={"output_code": self.output_code, "category": category})
        for j, chart_path in enumerate(extras.get("charts", [])[:4]):
            slide = prs.slides.add_slide(prs.slide_layouts[5])
            slide.shapes.title.text = f"[{label_ko}] 카테고리 분석 #{j + 1}"
            _set_title_color(slide, primary)
            tmp = self._download_chart(chart_path)
            if tmp:
                try:
                    slide.shapes.add_picture(tmp, Inches(0.5), Inches(1.5), width=Inches(8))
                except Exception:
                    pass

        for tbl in extras.get("tables", [])[:3]:
            slide = prs.slides.add_slide(prs.slide_layouts[5])
            slide.shapes.title.text = str(tbl.get("title", f"[{label_ko}] 표"))
            _set_title_color(slide, primary)
            try:
                rows = list(tbl.get("rows", []))
                cols = list(tbl.get("columns") or (list(rows[0].keys()) if rows else []))
                if cols and rows:
                    n_rows = min(len(rows), 10) + 1
                    n_cols = len(cols)
                    table_shape = slide.shapes.add_table(
                        n_rows, n_cols, Inches(0.5), Inches(1.5), Inches(9), Inches(0.5 * n_rows)
                    )
                    tbl_obj = table_shape.table
                    for c_idx, c in enumerate(cols):
                        tbl_obj.cell(0, c_idx).text = str(c)
                    for r_idx, row in enumerate(rows[:10]):
                        for c_idx, c in enumerate(cols):
                            tbl_obj.cell(r_idx + 1, c_idx).text = str(row.get(c, ""))
            except Exception:
                pass

        for text_block in extras.get("text_blocks", [])[:3]:
            slide = prs.slides.add_slide(prs.slide_layouts[1])
            slide.shapes.title.text = f"[{label_ko}] 해설"
            _set_title_color(slide, primary)
            tf = slide.placeholders[1].text_frame
            tf.text = str(text_block)[:1500]

        # 6) 평가 결과 (accent 배경 살짝)
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = "평가 / 향후 행동"
        _set_title_color(slide, primary)
        _set_background(slide, accent)
        body = slide.placeholders[1].text_frame
        ev = eval_result or {}
        body.text = f"passed: {ev.get('passed')}\n근거: {ev.get('rationale', '')[:300]}"

        local = self._tmp()
        prs.save(local)
        return self._upload(local)
