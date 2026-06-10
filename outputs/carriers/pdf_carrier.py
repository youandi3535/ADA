"""PDF carrier - KO font(TTF 우선, CID 폴백) + Visual PNG embed."""

from __future__ import annotations

import os as _os
import re as _re
from pathlib import Path

from outputs.architect.plan import ReportPlan
from outputs.context.schema import ReportContext

_FONT_OK = False
# 등록 후 실제 사용할 폰트명 — TTF 성공 시 ADA-KO 로 갱신, 실패 시 CID 기본값 유지.
_KS = "HYSMyeongJo-Medium"  # 본문 (CID 폴백)
_KG = "HYGothic-Medium"  # 제목/굵게 (CID 폴백)

# 번들/시스템에서 찾을 한글 TTF 후보 (OFL/시스템). reportlab 은 OTF(CFF) 못 읽으므로 .ttf 만.
_KO_TTF_REGULAR = (
    "NanumGothic.ttf",
    "NanumGothic-Regular.ttf",
    "Pretendard-Regular.ttf",
    "NotoSansKR-Regular.ttf",
    "malgun.ttf",
)
_KO_TTF_BOLD = (
    "NanumGothicBold.ttf",
    "NanumGothic-Bold.ttf",
    "Pretendard-Bold.ttf",
    "NotoSansKR-Bold.ttf",
    "malgunbd.ttf",
)


def _font_search_dirs():
    """한글 TTF 탐색 경로 — 레포 번들 > koreanize_matplotlib > 시스템."""
    dirs = []
    try:
        dirs.append(Path(__file__).resolve().parents[1] / "assets" / "fonts")
    except Exception:
        pass
    try:
        import koreanize_matplotlib as _km  # 파이프라인이 차트용으로 설치 → NanumGothic 번들

        dirs.append(Path(_km.__file__).resolve().parent)
    except Exception:
        pass
    for p in ("/usr/share/fonts", "/usr/local/share/fonts", _os.path.expanduser("~/.fonts"), "C:/Windows/Fonts"):
        dirs.append(Path(p))
    return [d for d in dirs if d and d.exists()]


def _locate_ttf(names):
    for d in _font_search_dirs():
        for nm in names:  # 1차: 평면
            cand = d / nm
            if cand.exists():
                return cand
        try:  # 2차: 재귀 (시스템 폰트 하위 디렉터리)
            for nm in names:
                hit = next(d.rglob(nm), None)
                if hit:
                    return hit
        except Exception:
            continue
    return None


# matplotlib font_manager 에 인덱싱된 한글 family (render.py 가 차트에 쓰는 후보와 정렬)
_KO_FAMILIES = (
    "Pretendard",
    "NanumGothic",
    "Noto Sans CJK KR",
    "Noto Sans KR",
    "Malgun Gothic",
    "AppleGothic",
    "Apple SD Gothic Neo",
    "Baekmuk Gulim",
    "UnDotum",
)


def _ttf_via_matplotlib():
    """matplotlib 폰트 인덱스에서 한글 TTF 를 family 명으로 탐색.

    파일명에 의존하지 않으므로(번들·시스템 무관) 차트(render.py)가 실제로 쓰는 그 폰트를
    PDF 본문에도 동일 적용 → 환경 불문 일관. reportlab 은 OTF(CFF) 못 읽으므로 .ttf 만.
    """
    try:
        import matplotlib.font_manager as fm
    except Exception:
        return None, None
    regular = bold = None
    try:
        for fam in _KO_FAMILIES:  # 선호 순서대로
            for fe in fm.fontManager.ttflist:
                fname = (getattr(fe, "fname", "") or "")
                if not fname.lower().endswith(".ttf") or (getattr(fe, "name", "") or "") != fam:
                    continue
                is_bold = (getattr(fe, "weight", "normal") in (700, "bold")) or ("bold" in fname.lower())
                if is_bold and bold is None:
                    bold = fname
                elif not is_bold and regular is None:
                    regular = fname
            if regular is not None:
                break  # 한 family 안에서 regular 확보되면 종료 (bold 는 같은 family 우선)
    except Exception:
        return None, None
    return (Path(regular) if regular else None), (Path(bold) if bold else None)


def _reg():
    """한글 폰트 등록 — TTF(자간·glyph 정상) 우선, 실패 시 CID 폴백.

    CID(HYSMyeongJo/HYGothic) 는 자간이 벌어지고 '·' 등이 '�' 로 깨지므로,
    NanumGothic/Pretendard 등 실 TTF 가 있으면 TTFont 로 등록해 사용한다.
    """
    global _FONT_OK, _KS, _KG
    if _FONT_OK:
        return
    from reportlab.pdfbase import pdfmetrics

    # ── TTF 우선 (자간·glyph 정상). 탐색: 번들/km/시스템(파일명) → matplotlib(family)
    try:
        reg = _locate_ttf(_KO_TTF_REGULAR)
        bold = _locate_ttf(_KO_TTF_BOLD)
        if reg is None:  # 파일명 매칭 실패 → matplotlib family 인덱스로 폭넓게 재시도
            mreg, mbold = _ttf_via_matplotlib()
            reg, bold = (reg or mreg), (bold or mbold)
        if reg is not None and reg.suffix.lower() == ".ttf":
            from reportlab.pdfbase.pdfmetrics import registerFontFamily
            from reportlab.pdfbase.ttfonts import TTFont

            if bold is None or bold.suffix.lower() != ".ttf":
                bold = reg
            pdfmetrics.registerFont(TTFont("ADA-KO", str(reg)))
            pdfmetrics.registerFont(TTFont("ADA-KO-B", str(bold)))
            registerFontFamily("ADA-KO", normal="ADA-KO", bold="ADA-KO-B", italic="ADA-KO", boldItalic="ADA-KO-B")
            _KS, _KG = "ADA-KO", "ADA-KO-B"
            _FONT_OK = True
            return
    except Exception:
        pass  # TTF 실패 → CID 폴백

    # ── CID 폴백 (기존 동작 보존)
    from reportlab.lib import fonts as F
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    _KS, _KG = "HYSMyeongJo-Medium", "HYGothic-Medium"
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


def _clean_title(raw, fallback="데이터 분석 종합 보고서", cap=48):
    """비대·중복된 user_intent 를 표지용 짧은 제목으로 정리.

    누적된 게이트 선택('(분석 방향:…)(방법론:…)' 반복)을 순서보존 dedupe 후
    첫 의미 조각만 취해 길이 cap. 비면 고정 제목 fallback.
    """
    s = (raw or "").strip()
    if not s:
        return fallback
    parts = _re.split(r"[()\[\]]|\s{2,}|·", s)
    seen, frags = set(), []
    for p in parts:
        p = p.strip(" \t·-—,:|")
        if not p or p in seen:
            continue
        seen.add(p)
        frags.append(p)
    title = frags[0] if frags else s
    if len(title) > cap:
        title = title[:cap].rstrip() + "…"
    return title or fallback


def _fetch_png(path):
    """image_embed 경로 → 로컬 PNG 경로. 로컬 우선, MinIO 키면 다운로드. 실패 None."""
    if not path:
        return None
    try:
        if Path(path).exists():
            return str(path)
    except Exception:
        pass
    try:
        from tools.minio_tool import get_minio_client

        mc = get_minio_client()
        key = path.replace(f"s3://{mc.bucket}/", "") if str(path).startswith("s3://") else path
        data = mc.download_bytes(key)
        if not data:
            return None
        import tempfile

        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.write(data)
        tmp.close()
        return tmp.name
    except Exception:
        return None


def _fv(v):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.4f}" if 0 < abs(v) < 1 else f"{v:,.2f}"
    return str(v)


def generate_pdf(plan: ReportPlan, ctx: ReportContext, output_path) -> str:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_RIGHT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle as PS
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            Image,
            KeepTogether,
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except Exception:
        return _fallback(plan, output_path)
    _reg()
    from outputs.style.palette import get_palette, hex_to_rgb
    from outputs.visuals.render import render_visual_to_png

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    pal = get_palette(ctx.meta.category)
    primary = colors.Color(*(c / 255 for c in hex_to_rgb(pal["primary"])))  # 표 헤더 배경 전용

    # 글씨는 모두 검은색 — 표 헤더(파란 배경+흰 글씨)만 예외로 유지.
    black = colors.black
    title = PS("T", fontName=_KG, fontSize=22, leading=28, textColor=black, spaceAfter=8)
    h1 = PS("H1", fontName=_KG, fontSize=18, leading=24, textColor=black, spaceBefore=10, spaceAfter=6)
    # h1_toc: h1 과 모양 동일하되 목차 페이지 추적 대상(afterFlowable 가 style.name 으로 식별)
    h1_toc = PS("H1TOC", fontName=_KG, fontSize=18, leading=24, textColor=black, spaceBefore=10, spaceAfter=6)
    h2 = PS("H2", fontName=_KG, fontSize=14, leading=20, textColor=black, spaceBefore=8, spaceAfter=4)
    sw = PS("SW", fontName=_KG, fontSize=12, leading=18, textColor=black, leftIndent=6)
    body = PS("B", fontName=_KS, fontSize=11, leading=16, textColor=black)
    bul = PS("BL", fontName=_KS, fontSize=11, leading=16, textColor=black, leftIndent=14, firstLineIndent=-8)
    cap = PS("CP", fontName=_KS, fontSize=9, leading=12, textColor=black)
    toc_e = PS("TOCE", fontName=_KS, fontSize=12, leading=18, textColor=black)  # 목차 항목명
    toc_p = PS("TOCP", fontName=_KS, fontSize=12, leading=18, textColor=black, alignment=TA_RIGHT)  # 목차 페이지

    title_text = _clean_title(ctx.meta.user_intent)  # 비대/중복 intent 컷
    chosen = (ctx.model_selection.chosen or {}).get("name", "-")
    pm = ctx.evaluation.primary_metric or {}

    # 목차 항목 — 본문에 실제로 렌더되는 파트만 (Executive Summary + 번호 섹션)
    toc_entries = []
    if plan.narrative_thread.setup:
        toc_entries.append("Executive Summary")
    for _sec in plan.sections:
        if _sec.id == "backup" or _sec.kind == "cover":
            continue
        if _sec.title:
            toc_entries.append(_sec.title)

    def _build_story(toc_render):
        """flowable 리스트 생성. toc_render=None 이면 1차(페이지 측정)용 placeholder 목차.

        목차 헤딩(Executive Summary·각 섹션)은 style 'H1TOC' 로 찍어 afterFlowable 가
        시작 페이지를 순서대로 수집 → 2차에서 페이지 범위를 채운다.
        """
        flow = []
        # ── 표지
        flow.append(Paragraph(title_text, title))
        flow.append(Paragraph("데이터 분석 종합 보고서", cap))  # 고정 부제
        flow.append(Spacer(1, 0.3 * cm))
        flow.append(
            Paragraph(
                f"카테고리 : {ctx.meta.category}     모델 : {chosen}     {pm.get('name', '지표')} : {_fv(pm.get('value'))}",
                body,
            )
        )
        flow.append(Paragraph(f"분류 {ctx.meta.classification} · 생성 {(ctx.meta.generated_at or '')[:10]}", cap))
        flow.append(Spacer(1, 1.5 * cm))

        # ── 목차 (표지 다음 페이지) — 항목명 | 페이지범위 2열, 점선 대신 옅은 구분선
        if toc_entries:
            flow.append(PageBreak())
            flow.append(Paragraph("목차", h1))
            flow.append(Spacer(1, 0.4 * cm))
            rows = []
            for _idx, _label in enumerate(toc_entries):
                _pr = toc_render[_idx][1] if toc_render else ""
                rows.append([Paragraph(_label, toc_e), Paragraph(_pr, toc_p)])
            tt = Table(rows, colWidths=[14 * cm, 3 * cm])
            tt.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#E2E8F0")),
                    ]
                )
            )
            flow.append(tt)
            flow.append(PageBreak())

        # ── Executive Summary (목차 추적 대상: H1TOC)
        nt = plan.narrative_thread
        if getattr(nt, "headline", "") or nt.resolution or nt.conflict:
            flow.append(Paragraph("Executive Summary", h1_toc))
            if getattr(nt, "headline", ""):
                flow.append(Paragraph(f"<b>{nt.headline}</b>", body))  # 결론(정수) — 굵게
            # 라벨 없이 흐르는 단정 문장 (시니어 스타일): 원인→근거→대응→단서
            _rest = " ".join(s for s in [nt.conflict, nt.resolution, nt.recommendation] if s)
            if _rest:
                flow.append(Paragraph(_rest, body))
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

        # ── 본문 섹션 (목차 추적 대상: H1TOC)
        for sec in plan.sections:
            if sec.id == "backup" or sec.kind == "cover":
                continue
            flow.append(Paragraph(sec.title, h1_toc))
            flow.append(Spacer(1, 0.35 * cm))  # 규칙: 큰 제목 밑 한 줄 띄움
            _img_in_sec = 0  # 페이지당 차트 최대 2개 강제용
            _just_broke = False
            for sl in sec.slides:
                if sl.role == "meta" and sl.layout in ("cover", "agenda", "closing"):
                    continue
                sl_flow: list = [Paragraph(sl.title_ko or sl.id, h2)]
                if sl.so_what:  # 규칙: '핵심 —' 위아래 한 줄 띄움
                    sl_flow.append(Spacer(1, 0.2 * cm))
                    sl_flow.append(Paragraph(f"핵심 — {sl.so_what}", sw))
                    sl_flow.append(Spacer(1, 0.2 * cm))
                # 산문형 본문(라벨 + 단락) — 규칙: 소제목 사이 한 줄 더 띄움
                for _blk in (getattr(sl, "prose_blocks", None) or []):
                    if isinstance(_blk, (list, tuple)) and len(_blk) >= 2 and _blk[1]:
                        sl_flow.append(Spacer(1, 0.42 * cm))
                        if _blk[0]:  # 라벨 있으면 굵게, 없으면 단락만 (라벨 없는 흐름)
                            sl_flow.append(Paragraph(f"<b>{_blk[0]}</b>", sw))
                        sl_flow.append(Paragraph(str(_blk[1]), body))
                for b in sl.body_outline:
                    sl_flow.append(Paragraph(f"• {b}", bul))
                has_img = False
                vs = sl.visual_spec
                if vs and (vs.type or "").startswith("table_"):
                    # 표는 이미지 대신 native reportlab Table — 선명·full-width·페이지 분할(헤더 반복)
                    _cols = list((vs.spec or {}).get("columns") or [])
                    _rows = list((vs.spec or {}).get("rows") or [])
                    if _cols and _rows:
                        _nc = len(_cols)
                        _data = [list(_cols)] + [[str(c) for c in r] for r in _rows]
                        _t = Table(_data, colWidths=[(17.0 / _nc) * cm] * _nc, hAlign="LEFT", repeatRows=1)
                        _t.setStyle(
                            TableStyle(
                                [
                                    ("BACKGROUND", (0, 0), (-1, 0), primary),
                                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                    ("FONTNAME", (0, 0), (-1, 0), _KG),
                                    ("FONTNAME", (0, 1), (-1, -1), _KS),
                                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
                                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                                ]
                            )
                        )
                        _grp: list = [Spacer(1, 0.2 * cm)]
                        if vs.title:
                            _grp.append(Paragraph(f"<b>{vs.title}</b>", sw))
                        _grp.append(_t)
                        if vs.caption:
                            _grp.append(Paragraph(vs.caption, cap))
                        sl_flow.append(KeepTogether(_grp))  # 규칙: 표는 절대 페이지 분할 금지
                elif vs and vs.type and vs.type != "text_only":
                    try:
                        if (vs.type or "") == "image_embed":
                            # 실 파이프라인 차트 PNG 직접 임베드 (재렌더 불가 → 원본)
                            png = _fetch_png((vs.spec or {}).get("path"))
                        else:
                            png = render_visual_to_png(vs, ctx, slide=sl)
                        if png:
                            from PIL import Image as PI

                            with PI.open(png) as im:
                                ar = im.width / im.height
                            w_cm = 16.0  # 1.5배 확대 (10.7 → 16)
                            h_cm = w_cm / ar
                            if h_cm > 10.0:
                                h_cm = 10.0
                                w_cm = h_cm * ar
                            sl_flow.append(Spacer(1, 0.3 * cm))
                            sl_flow.append(Image(png, width=w_cm * cm, height=h_cm * cm))
                            if vs.caption:
                                sl_flow.append(Paragraph(vs.caption, cap))
                            has_img = True
                    except Exception:
                        pass
                sl_flow.append(Spacer(1, 0.4 * cm))
                # 제목+그래프가 페이지에서 쪼개지지 않게 — 차트 있는 슬라이드는 KeepTogether 로 한 덩어리
                if has_img:
                    flow.append(KeepTogether(sl_flow))
                    _img_in_sec += 1
                    _just_broke = False
                    if _img_in_sec % 2 == 0:  # 차트 2개마다 페이지 분할 → 페이지당 최대 2개
                        flow.append(PageBreak())
                        _just_broke = True
                else:
                    flow.extend(sl_flow)
                    _just_broke = False
            if not _just_broke:  # 직전에 분할했으면 빈 페이지 방지
                flow.append(PageBreak())
        return flow

    def _foot(canvas, dc):
        canvas.saveState()
        canvas.setFont(_KS, 9)
        canvas.setFillColor(colors.black)
        canvas.drawString(2 * cm, 1 * cm, title_text[:40])  # 주제만 (왼쪽)
        canvas.drawRightString(A4[0] - 2 * cm, 1 * cm, f"p.{dc.page}")  # 페이지번호 (오른쪽 가장자리)
        canvas.restoreState()

    class _TrackDoc(SimpleDocTemplate):
        """afterFlowable 로 'H1TOC' 헤딩의 시작 페이지를 순서대로 수집."""

        def afterFlowable(self, fl):  # noqa: N802 (reportlab API 시그니처)
            if isinstance(fl, Paragraph) and getattr(fl.style, "name", "") == "H1TOC":
                self.toc_pages.append(self.page)

    def _mk(path):
        d = _TrackDoc(
            str(path), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm
        )
        d.toc_pages = []
        return d

    # ── 1차: placeholder 목차로 빌드 → 각 헤딩 시작 페이지·총 페이지 수 측정
    import tempfile as _tf

    _tmp = _tf.NamedTemporaryFile(suffix=".pdf", delete=False).name
    try:
        d1 = _mk(_tmp)
        d1.build(_build_story(None), onFirstPage=_foot, onLaterPages=_foot)
        pages, total = list(d1.toc_pages), d1.page
    except Exception:
        pages, total = [], 0
    try:
        _os.unlink(_tmp)
    except Exception:
        pass

    # ── 페이지 범위 계산 (다음 항목 시작-1, 마지막은 총 페이지). 측정 실패 시 페이지 생략.
    if pages and len(pages) == len(toc_entries):
        toc_render = []
        for _i, _label in enumerate(toc_entries):
            _s = pages[_i]
            _e = (pages[_i + 1] - 1) if _i + 1 < len(pages) else total
            if _e < _s:
                _e = _s
            toc_render.append((_label, f"p.{_s}" if _s == _e else f"p.{_s}–{_e}"))
    else:
        toc_render = [(_label, "") for _label in toc_entries]

    # ── 2차: 실제 페이지 범위 채워 최종 렌더
    doc = _mk(out)
    doc.build(_build_story(toc_render), onFirstPage=_foot, onLaterPages=_foot)
    return str(out)


def _fallback(plan, output_path):
    out = Path(str(output_path) + ".txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"[PDF Fallback {plan.skeleton}]", encoding="utf-8")
    return str(out)
