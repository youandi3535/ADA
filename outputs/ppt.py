"""outputs.ppt — OUT-01 PowerPoint 발표자료 (python-pptx)."""

from __future__ import annotations

from typing import Any

from outputs.base import OutputGenerator


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
    ) -> str:
        from pptx import Presentation
        from pptx.util import Inches, Pt

        prs = Presentation()
        # 1) 표지
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        slide.shapes.title.text = "ADA 자동 분석 보고서"
        slide.placeholders[1].text = f"카테고리: {category}\n의도: {user_intent or '미지정'}"

        # 2) 핵심 인사이트
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = "핵심 인사이트"
        tf = slide.placeholders[1].text_frame
        tf.text = (insights or "")[:1500]
        for p in tf.paragraphs:
            for r in p.runs:
                r.font.size = Pt(18)

        # 3) 모델 비교
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = "Best Model"
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
            try:
                # MinIO에서 임시 다운로드
                from tools.minio_tool import get_minio_client

                mc = get_minio_client()
                if chart_path.startswith("s3://"):
                    key = chart_path.replace(f"s3://{mc.bucket}/", "")
                else:
                    key = chart_path
                body = mc.download_bytes(key)
                tmp = self._tmp().replace(".pptx", ".png")
                with open(tmp, "wb") as f:
                    f.write(body)
                slide.shapes.add_picture(tmp, Inches(0.5), Inches(1.5), width=Inches(8))
            except Exception:
                pass

        # 5) 평가 결과
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = "평가 / 향후 행동"
        body = slide.placeholders[1].text_frame
        ev = eval_result or {}
        body.text = f"passed: {ev.get('passed')}\n근거: {ev.get('rationale', '')[:300]}"

        local = self._tmp()
        prs.save(local)
        return self._upload(local)
