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

    def _try_report_v2(self, *, state: Any) -> str | None:
        """신형 보고서 경로 — report_context 가 실내용이면 report_skeleton→pdf_carrier 로 렌더.

        OUT-01(PPT) V2 와 동일 철학: state 에 분석 컨텍스트가 쌓여 있으면 신형 엔진으로
        '데이터 분석 종합 보고서' 를 생성하고, 없거나 실패하면 None 을 반환해 호출부가
        구형(legacy) reportlab 렌더로 폴백한다 (silent-safe).
        """
        if state is None:
            return None
        try:
            from outputs.context.builder import build_report_context

            ctx = build_report_context(state)
            # [임시 디버그] 실제 ReportContext 덤프 — 검증용, 확인 후 제거.
            # outputs/ 디렉터리에 기록한다(=compose 의 ../outputs:/app/outputs 마운트 → 호스트에서 바로 보임).
            # 과거엔 repo 루트(/app)에 썼는데 /app 은 마운트 안 돼 호스트에서 안 보였음.
            try:
                import json as _json
                import os as _os

                _dump = _os.path.join(_os.path.dirname(__file__), "report_context_dump.json")
                with open(_dump, "w", encoding="utf-8") as _f:
                    _json.dump(ctx.to_dict(), _f, ensure_ascii=False, indent=1)
            except Exception:  # noqa: BLE001
                pass
            # 실질 내용이 있을 때만 신형 가동 — 얇은 state(테스트 등)는 구형 폴백 유지.
            has_content = bool(ctx.dataset.dtypes) or bool(ctx.evaluation.metrics) or bool(ctx.eda.charts)
            if not has_content:
                return None
            from outputs.architect.skeletons import report_skeleton
            from outputs.carriers.pdf_carrier import generate_pdf

            plan = report_skeleton.build(ctx)
            local = self._tmp()
            generate_pdf(plan, ctx, local)
            return self._upload(local)
        except Exception as e:  # noqa: BLE001
            try:
                from ada.core.logger import get_logger

                get_logger("PDFReportGenerator").warning("pdf_v2_report_failed", error=str(e))
            except Exception:  # noqa: BLE001
                pass
            return None

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

        # ── 신형 보고서 경로 (OUT-02 V2) — report_context 있으면 종합보고서, 없으면 구형 폴백
        _v2 = self._try_report_v2(state=state)
        if _v2 is not None:
            return _v2

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

        # HJ — Method B: eda_charts + extras['charts'] 를 한 번에 병렬 다운로드.
        # reportlab flow append 는 순차 (Story 빌더가 stateful).
        eda_paths = list(eda_charts[:6])
        extras = self._call_extras(state, ctx={"output_code": self.output_code, "category": category})
        extras_paths = list(extras.get("charts", [])[:4])
        local_paths = self._download_charts_parallel(eda_paths + extras_paths)
        eda_local = local_paths[: len(eda_paths)]
        extras_local = local_paths[len(eda_paths) :]

        flow.append(PageBreak())
        flow.append(Paragraph("EDA Charts", h2_style))
        for tmp in eda_local:
            if tmp:
                try:
                    flow.append(Image(tmp, width=15 * cm, height=8 * cm))
                    flow.append(Spacer(1, 0.5 * cm))
                except Exception:
                    continue

        if any(extras.get(k) for k in ("charts", "tables", "text_blocks")):
            flow.append(PageBreak())
            flow.append(Paragraph(f"[{label_ko}] Category Analysis", h2_style))

            for tmp in extras_local:
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
