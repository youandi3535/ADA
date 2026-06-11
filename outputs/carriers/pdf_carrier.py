"""PDF carrier - KO font(TTF 우선, CID 폴백) + Visual PNG embed."""

from __future__ import annotations

import os as _os
import re as _re
from pathlib import Path

from outputs.architect.plan import ReportPlan
from outputs.architect.skeletons.report_skeleton import ko_metric as _ko_metric
from outputs.context.schema import ReportContext

# [PYLANCE_TEST_2026] persist-check — 이 줄이 남아있으면 복원 안 됨
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
    h1 = PS("H1", fontName=_KG, fontSize=22, leading=30, textColor=black, spaceBefore=14, spaceAfter=8)  # [B28] h1 22pt
    # h1_toc: h1 과 모양 동일하되 목차 페이지 추적 대상(afterFlowable 가 style.name 으로 식별)
    h1_toc = PS("H1TOC", fontName=_KG, fontSize=22, leading=30, textColor=black, spaceBefore=14, spaceAfter=8)
    h2 = PS("H2", fontName=_KG, fontSize=18, leading=26, textColor=black, spaceBefore=10, spaceAfter=6)  # [B28] h2 18pt
    sw = PS("SW", fontName=_KG, fontSize=16, leading=23, textColor=colors.HexColor("#1E3A5F"), leftIndent=0)  # [B28][B29] sw 16pt 네이비
    body = PS("B", fontName=_KS, fontSize=14, leading=20, textColor=black, leftIndent=8)  # [B28][B30] body 14pt+들여쓰기 8
    bul = PS("BL", fontName=_KS, fontSize=14, leading=20, textColor=black, leftIndent=14, firstLineIndent=-10)  # [B28] bul 14pt
    cap = PS("CP", fontName=_KS, fontSize=12, leading=16, textColor=black)  # [B28] cap 12pt
    toc_e = PS("TOCE", fontName=_KS, fontSize=14, leading=20, textColor=black)  # [B28] toc_e 14pt  # 목차 항목명
    toc_p = PS("TOCP", fontName=_KS, fontSize=12, leading=18, textColor=colors.HexColor("#475569"), alignment=TA_RIGHT)  # 목차 페이지(옅은 회색)
    # [목차룰] Executive Summary 강조 + TABLE OF CONTENTS 트래킹 라벨
    toc_e_exec = PS("TOCEE", fontName=_KG, fontSize=13, leading=20, textColor=colors.HexColor("#1E3A5F"))  # Exec Summary 강조
    toc_p_exec = PS("TOCPE", fontName=_KS, fontSize=13, leading=20, textColor=colors.HexColor("#1E3A5F"), alignment=TA_RIGHT)
    toc_sub_e = PS("TOCSE", fontName=_KS, fontSize=11, leading=16, textColor=colors.HexColor("#64748B"), leftIndent=16)  # 부록 하위
    toc_sub_p = PS("TOCSP", fontName=_KS, fontSize=11, leading=16, textColor=colors.HexColor("#64748B"), alignment=TA_RIGHT)
    toc_label = PS("TOCLbl", fontName="Helvetica", fontSize=9, leading=12, textColor=colors.HexColor("#94A3B8"))  # TABLE OF CONTENTS

    # [B5 표지룰] ADA Studio 브랜드 표지 전용 스타일
    # 카테고리 한글 매핑 (사이트 톤 통일)
    _CAT_KO = {
        "tabular_ml": "정형 ML",
        "tabular_dl": "정형 DL",
        "timeseries": "시계열",
        "anomaly_detection": "이상 탐지",
        "anomaly": "이상 탐지",
    }
    _NAVY = colors.HexColor("#1E3A5F")
    _GRAY = colors.HexColor("#475569")
    _GRAY_LT = colors.HexColor("#94A3B8")
    _BLUE_PALE = colors.HexColor("#9CB4D0")
    cover_brand = PS("CoverBrand", fontName="Helvetica-Bold", fontSize=28, leading=32, textColor=colors.white)
    cover_brand_sub = PS("CoverBrandSub", fontName="Helvetica", fontSize=9, leading=12, textColor=_BLUE_PALE)
    cover_class = PS("CoverCls", fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=colors.white, alignment=TA_RIGHT)
    cover_label = PS("CoverLbl", fontName="Helvetica-Bold", fontSize=10, leading=14, textColor=_GRAY)
    cover_title = PS("CoverTitle", fontName=_KG, fontSize=28, leading=36, textColor=_NAVY, spaceBefore=8, spaceAfter=6)
    cover_subtitle = PS("CoverSub", fontName=_KS, fontSize=14, leading=20, textColor=_GRAY)
    cover_meta_key = PS("CoverK", fontName=_KG, fontSize=10, leading=14, textColor=_GRAY)
    cover_meta_val = PS("CoverV", fontName=_KS, fontSize=11, leading=15, textColor=black)
    cover_slogan = PS("CoverSlogan", fontName=_KS, fontSize=10, leading=14, textColor=_NAVY)
    cover_big_num = PS("CoverBigNum", fontName="Helvetica-Bold", fontSize=36, leading=42, textColor=_NAVY, alignment=TA_RIGHT)
    cover_big_lbl = PS("CoverBigLbl", fontName=_KG, fontSize=9, leading=12, textColor=_GRAY, alignment=TA_RIGHT)
    cover_footer = PS("CoverFt", fontName="Helvetica", fontSize=8, leading=11, textColor=_GRAY_LT)
    cover_domain = PS("CoverDom", fontName="Helvetica", fontSize=8, leading=11, textColor=_GRAY_LT, alignment=TA_RIGHT)

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
        # ── 표지 [B5 표지룰] ADA Studio 브랜드 표지 — 사이트(ada-aiagent.com) 톤 일치
        # 구성: (1) 네이비 헤더  (2) 보고서 종류 라벨  (3) 제목+데이터셋부제
        #       (4) 회색 메타 박스 [카테고리/주 모델/표본/생성 | 큰 지표]
        #       (5) 사이트 슬로건  (6) 푸터 (© + 도메인)
        import datetime as _dt

        # (1) 네이비 헤더 박스
        _classification = (ctx.meta.classification or "PUBLIC").upper()
        _header_left = [
            Paragraph("ADA Studio", cover_brand),
            Spacer(1, 0.1 * cm),
            Paragraph("A D A P T I V E &nbsp;&nbsp; D A T A &nbsp;&nbsp; A N A L Y S T", cover_brand_sub),
        ]
        _header_right = Paragraph(_classification, cover_class)
        _header = Table([[_header_left, _header_right]], colWidths=[12 * cm, 5 * cm], rowHeights=[2.8 * cm])
        _header.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _NAVY),
            ("VALIGN", (0, 0), (0, 0), "MIDDLE"),
            ("VALIGN", (1, 0), (1, 0), "TOP"),
            ("LEFTPADDING", (0, 0), (0, 0), 18),
            ("RIGHTPADDING", (1, 0), (1, 0), 18),
            ("TOPPADDING", (1, 0), (1, 0), 14),
            ("BOX", (0, 0), (-1, -1), 0, _NAVY),
            # 95점 push: 헤더 아래 미세한 진한 네이비 액센트 라인
            ("LINEBELOW", (0, 0), (-1, -1), 1.5, colors.HexColor("#0F1E33")),
        ]))
        flow.append(_header)
        flow.append(Spacer(1, 0.8 * cm))

        # (2) 보고서 종류 라벨
        flow.append(Paragraph("D A T A - D R I V E N &nbsp;&nbsp; I N S I G H T &nbsp;&nbsp; R E P O R T", cover_label))
        flow.append(Spacer(1, 0.25 * cm))

        # (3) 큰 제목 + 데이터셋 부제 (이름 · 표본 수)
        flow.append(Paragraph(title_text, cover_title))
        _ds_name = ""
        try:
            from outputs.architect.skeletons.report_skeleton import _human_dataset_name as _hdn
            _ds_name = _hdn(ctx)
        except Exception:
            _ds_name = (ctx.dataset.dataset_name or "").strip() or "데이터셋"
        # [표지룰 보강 2026-06-11] 기준 매치 — 부제 간결화 ("데이터셋명 · N건")
        _shape = ctx.dataset.shape or {}
        _n_rows = _shape.get("rows", 0)
        _subtitle = f"{_ds_name} · {_n_rows:,}건" if (_ds_name and _n_rows) else _ds_name
        flow.append(Paragraph(_subtitle, cover_subtitle))
        flow.append(Spacer(1, 1.2 * cm))

        # (4) 회색 메타 박스 — 좌: 카테고리/주 모델/표본/생성, 우: 큰 지표
        _gen_date = (ctx.meta.generated_at or "")[:10]
        _cat_ko = _CAT_KO.get(ctx.meta.category or "", ctx.meta.category or "-")
        _meta_rows = [
            [Paragraph("분석 카테고리", cover_meta_key), Paragraph(_cat_ko, cover_meta_val)],
            [Paragraph("주 모델", cover_meta_key), Paragraph(str(chosen), cover_meta_val)],
            [Paragraph("표본 수", cover_meta_key), Paragraph(f"{_n_rows:,}건" if _n_rows else "-", cover_meta_val)],
            [Paragraph("생성", cover_meta_key), Paragraph(_gen_date or "-", cover_meta_val)],
        ]
        _meta_left = Table(_meta_rows, colWidths=[3.0 * cm, 6.5 * cm])
        _meta_left.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        _metric_name = _ko_metric(pm.get("name")) if pm.get("name") else "지표"
        _metric_val = _fv(pm.get("value"))
        # 우측: 작은 네이비 사각 아이콘 (▣) + 큰 숫자 + 라벨
        # [표지룰 보강 2026-06-11] 기준 매치 — 작은 파란 정사각 아이콘
        _meta_right = [
            Paragraph('<para alignment="right"><font color="#185FA5" size="14">■</font></para>', cover_big_lbl),
            Spacer(1, 0.05 * cm),
            Paragraph(_metric_val, cover_big_num),
            Paragraph(_metric_name, cover_big_lbl),
        ]
        _meta = Table([[_meta_left, _meta_right]], colWidths=[10 * cm, 7 * cm])
        _meta.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
            ("LINEBEFORE", (0, 0), (0, -1), 3, _NAVY),  # 좌측 네이비 액센트 (브랜드 시각 신호)
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 20),
            ("RIGHTPADDING", (0, 0), (-1, -1), 20),
            ("TOPPADDING", (0, 0), (-1, -1), 20),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 20),
        ]))
        flow.append(_meta)
        flow.append(Spacer(1, 1.2 * cm))

        # (5) 슬로건 — 사이트 메인 카피, 평문 (좌측 액센트 라인 없음 — 사용자 확정)
        flow.append(Paragraph("다섯 번의 선택으로, 데이터를 전문가 수준 인사이트로", cover_slogan))

        # (6) 푸터 (페이지 하단 푸시) — 위에 옅은 구분선
        flow.append(Spacer(1, 3.0 * cm))
        _year = _dt.datetime.now().year
        _footer = Table([[
            Paragraph(f"© {_year} ADA Studio · Adaptive Data Analyst", cover_footer),
            Paragraph("ada-aiagent.com", cover_domain),
        ]], colWidths=[10 * cm, 7 * cm])
        _footer.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("LINEABOVE", (0, 0), (-1, 0), 0.4, colors.HexColor("#CBD5E1")),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
        ]))
        flow.append(_footer)

        # ── 목차 [B24 목차룰 보강 2026-06-11] 기준 매치
        # - 항목 ~ 페이지번호 사이 점선 (....) 채움 (3열 Table: 항목 | 점선 | 페이지)
        # - 9.x 부록 하위는 들여쓰기 + 옅은 회색 (toc_sub_e/toc_sub_p)
        # - 8번/9번 사이 본문↔부록 구분선 강화 (네이비 진한 LINEBELOW)
        if toc_entries:
            flow.append(PageBreak())
            flow.append(Paragraph("목차", h1))
            flow.append(Paragraph("T A B L E &nbsp;&nbsp; O F &nbsp;&nbsp; C O N T E N T S", toc_label))
            flow.append(Spacer(1, 0.5 * cm))
            # 점선 스타일 (가운데 채움)
            _dot_style = PS("TOCDot", fontName="Helvetica", fontSize=9, leading=14,
                            textColor=colors.HexColor("#94A3B8"), alignment=1)
            _dots = ". " * 30  # 점선 패턴
            rows = []
            _split_idx = -1  # 본문↔부록 경계 인덱스
            for _idx, _label in enumerate(toc_entries):
                _pr = toc_render[_idx][1] if toc_render else ""
                _l = _label.strip()
                # 9.x 부록 하위 (들여쓰기) — "9.1", "9.2", ... 또는 부록 sub
                _is_sub = _l.startswith(("9.1", "9.2", "9.3", "9.4")) or (
                    _l.startswith(("부록", "Appendix")) and "·" in _l
                )
                # 본문/부록 경계 — "9. 부록" 라인 식별
                if _l.startswith("9.") and not _is_sub:
                    _split_idx = len(rows)
                # 행 스타일 분기
                if _l.lower().startswith("executive"):
                    rows.append([Paragraph(_label, toc_e_exec), Paragraph(_dots, _dot_style), Paragraph(_pr, toc_p_exec)])
                elif _is_sub:
                    rows.append([Paragraph(_label, toc_sub_e), Paragraph(_dots, _dot_style), Paragraph(_pr, toc_sub_p)])
                else:
                    rows.append([Paragraph(_label, toc_e), Paragraph(_dots, _dot_style), Paragraph(_pr, toc_p)])
            tt = Table(rows, colWidths=[8 * cm, 6 * cm, 3 * cm])
            _ts = [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#E2E8F0")),
            ]
            # 본문/부록 경계에 진한 네이비 LINEABOVE (시각 분리)
            if _split_idx > 0:
                _ts.append(("LINEABOVE", (0, _split_idx), (-1, _split_idx), 1.0, colors.HexColor("#1E3A5F")))
            tt.setStyle(TableStyle(_ts))
            flow.append(tt)
            flow.append(PageBreak())

        # ── Executive Summary (목차 추적 대상: H1TOC)
        # [B25 키메시지줄띄움룰] 헤드라인(굵은 결론) 다음 한 줄 띄움 — 시각 호흡 + 본문 분리
        nt = plan.narrative_thread
        if getattr(nt, "headline", "") or nt.resolution or nt.conflict:
            flow.append(Paragraph("Executive Summary", h1_toc))
            if getattr(nt, "headline", ""):
                flow.append(Paragraph(f"<b>{nt.headline}</b>", body))  # 결론(정수) — 굵게
                flow.append(Spacer(1, 0.25 * cm))  # [B25] 키메시지 다음 줄 띄움
            # 라벨 없이 흐르는 단정 문장 (시니어 스타일): 원인·근거·대응·단서
            _rest = " ".join(s for s in [nt.conflict, nt.resolution, nt.recommendation] if s)
            if _rest:
                flow.append(Paragraph(_rest, body))
            flow.append(Spacer(1, 0.5 * cm))

        if ctx.evaluation.metrics:
            flow.append(Paragraph("핵심 지표", h2))
            data = [["지표", "값"]]
            _metric_items = list(ctx.evaluation.metrics.items())[:6]
            for k, m in _metric_items:
                # raw metric key('val_roc_auc' 등)를 한국어로 ('검증 AUC') — 모르는 키는 원본 유지
                data.append([_ko_metric(k), _fv(m.get("value"))])
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
            # [C10 SoWhat룰] + [B26 표·차트SoWhat강제룰] 표 아래 인사이트 한 줄(굵게) + 해석 한 줄
            flow.append(Spacer(1, 0.3 * cm))
            _pm = ctx.evaluation.primary_metric or {}
            _pm_ko = _ko_metric(_pm.get("name")) if _pm.get("name") else "주지표"
            _pm_v = _fv(_pm.get("value"))
            flow.append(Paragraph(
                f"<b>주지표 {_pm_ko} = {_pm_v}이 본 분석의 판단 기준이다.</b>",
                body,
            ))
            # 지표 간 격차 자동 계산
            try:
                _vals = [m.get("value") for _, m in _metric_items if isinstance(m.get("value"), (int, float))]
                if len(_vals) >= 2:
                    _spread = (max(_vals) - min(_vals)) * 100
                    _stab = "균형적이다 — 특정 임계값에 과적합되지 않은 안정 영역으로 해석된다" if _spread <= 15 else "편차가 크다 — 임계값 의존성 확인 필요"
                    flow.append(Paragraph(
                        f"지표 간 격차가 {_spread:.0f}%p 이내로 {_stab}.",
                        body,
                    ))
            except Exception:
                pass
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
                            # [B6 EDA페이지룰] 페이지당 2개 강제 — width 14cm / height 상한 6.0cm
                            w_cm = 14.0
                            h_cm = w_cm / ar
                            if h_cm > 6.0:
                                h_cm = 6.0
                                w_cm = h_cm * ar
                            sl_flow.append(Spacer(1, 0.3 * cm))
                            sl_flow.append(Image(png, width=w_cm * cm, height=h_cm * cm))
                            if vs.caption:
                                sl_flow.append(Paragraph(vs.caption, cap))
                            has_img = True
                    except Exception:
                        pass
                sl_flow.append(Spacer(1, 0.4 * cm))
                # [B6 EDA페이지룰] 차트 슬라이드 페이지당 2개 강제
                # 홀수 번째(1·3·5번): 페이지 상단에서 시작하도록 보장. 짝수 번째(2·4번): 같은 페이지에 이어 붙이고 끝낸 후 PageBreak.
                if has_img:
                    _img_in_sec += 1
                    if _img_in_sec % 2 == 1 and _img_in_sec > 1:
                        # 새 홀수 차트는 무조건 새 페이지에서 시작 (이전 짝수 차트의 PageBreak 가 처리)
                        pass
                    flow.append(KeepTogether(sl_flow))
                    _just_broke = False
                    if _img_in_sec % 2 == 0:
                        flow.append(PageBreak())
                        _just_broke = True
                else:
                    flow.extend(sl_flow)
                    _just_broke = False
            if not _just_broke:  # 직전에 분할했으면 빈 페이지 방지
                flow.append(PageBreak())
        return flow

    def _foot(canvas, dc):
        # [푸터룰] 좌: 보고서 제목 (옅은 회색, 9pt) / 우: 페이지번호 (옅은 회색, 12pt)
        canvas.saveState()
        # 좌측 제목 — 9pt 옅은 회색
        canvas.setFont(_KS, 9)
        canvas.setFillColor(colors.HexColor("#94A3B8"))
        canvas.drawString(2 * cm, 1 * cm, title_text[:40])
        # 우측 페이지 번호 — 12pt 더 옅은 회색
        canvas.setFont("Helvetica", 12)
        canvas.setFillColor(colors.HexColor("#94A3B8"))
        canvas.drawRightString(A4[0] - 2 * cm, 1 * cm, f"p.{dc.page}")
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
