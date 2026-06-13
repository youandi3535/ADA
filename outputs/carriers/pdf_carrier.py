"""PDF carrier - KO font(TTF 우선, CID 폴백) + Visual PNG embed."""

from __future__ import annotations

import os as _os
import re as _re
from pathlib import Path

from outputs.architect.plan import ReportPlan
from outputs.architect.skeletons.report_skeleton import chairman_exec as _chairman_exec, ko_metric as _ko_metric
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


def _nodash(s):
    """[B18 평이한언어룰] 본문 렌더 직전 긴 줄표(—)를 쉼표로 정리 — 절 잇는 어색한 대시 금지(전역)."""
    if not isinstance(s, str):
        return s
    return _re.sub(r"\s*—\s*", ", ", s).replace(" ,", ",")


def _draw_brand_A(c, x, y, h, color, lw):
    """브랜드 'A' 심볼 — 얇은 획 피크(로고 마크). (x,y)=바운딩 좌하단, h=높이."""
    w = h * 0.86
    c.setStrokeColor(color)
    c.setLineWidth(lw)
    c.setLineCap(1)
    c.setLineJoin(1)
    c.line(x, y, x + w / 2, y + h)
    c.line(x + w, y, x + w / 2, y + h)
    t = 0.42  # 가로획 높이 비율
    c.line(x + t * (w / 2), y + t * h, x + w - t * (w / 2), y + t * h)


def _round_card(c, x, y, w, h, r, fill, stroke=None):
    """둥근 모서리 카드 — fill(+옵션 stroke 테두리)."""
    c.setFillColor(fill)
    if stroke is not None:
        c.setStrokeColor(stroke)
        c.setLineWidth(1.2)
        c.roundRect(x, y, w, h, r, stroke=1, fill=1)
    else:
        c.roundRect(x, y, w, h, r, stroke=0, fill=1)


def _wrap_title(c, text, font, max_w):
    """표지 제목 자동 맞춤 — 1줄(31→20pt)에 들어가면 1줄, 아니면 2줄(공백 중앙 분할, 28→14pt).

    긴 제목이 우측 여백을 넘어 잘리는 것 방지(어떤 데이터든 일반화). 반환: (lines, size).
    """
    for sz in range(31, 19, -1):
        if c.stringWidth(text, font, sz) <= max_w:
            return [text], sz
    sp = [i for i, ch in enumerate(text) if ch == " "]
    if sp:
        mid = len(text) / 2
        cut = min(sp, key=lambda i: abs(i - mid))
        l1, l2 = text[:cut].strip(), text[cut:].strip()
    else:
        cut = len(text) // 2
        l1, l2 = text[:cut], text[cut:]
    longer = l1 if c.stringWidth(l1, font, 50) >= c.stringWidth(l2, font, 50) else l2
    for sz in range(28, 13, -1):
        if c.stringWidth(longer, font, sz) <= max_w:
            return [l1, l2], sz
    return [l1, l2], 14


def _brandize_png(png):
    """[PDF 전용] 차트 강조색 #185FA5 → 브랜드 블루 #3A6FE0 재색칠.

    render.py(공유·PPT 담당 팀원 영역)는 불변. carrier 가 받은 차트 PNG 만 PDF용으로 후처리한다.
    흰 배경 블렌딩 알파를 보존해 가장자리(AA) 매끄럽게 재색칠. numpy/PIL 없거나 강조색 없으면
    원본 그대로 반환(안전 — 실패해도 PDF 는 깨지지 않음).
    """
    if not png:
        return png
    try:
        import tempfile

        import numpy as np
        from PIL import Image as _PIL

        src = np.array((24, 95, 165))  # #185FA5 (render.py 강조 통일색)
        dst = np.array((58, 111, 224), float)  # #3A6FE0 (사이트 브랜드 블루)
        im = _PIL.open(png).convert("RGB")
        a = np.asarray(im).astype(np.int16)
        m = np.sqrt(((a - src) ** 2).sum(2)) < 70
        if not m.any():
            return png
        al = ((255 - a).sum(2) / (255 * 3 - src.sum())).clip(0, 1)[..., None]  # 흰 배경 블렌딩 α 추정
        rec = dst * al + 255 * (1 - al)
        out = a.astype(float)
        out[m] = rec[m]
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
        _PIL.fromarray(out.clip(0, 255).astype("uint8")).save(tmp)
        return tmp
    except Exception:
        return png


def generate_pdf(plan: ReportPlan, ctx: ReportContext, output_path) -> str:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_RIGHT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle as PS
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            Flowable,
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
    from outputs.visuals.render import render_visual_to_png

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    primary = colors.HexColor("#243B5C")  # 표 헤더 배경 — 브랜드 네이비(통일, palette 비의존)

    # 글씨는 모두 검은색 — 표 헤더(파란 배경+흰 글씨)만 예외로 유지.
    black = colors.black
    h1 = PS("H1", fontName=_KG, fontSize=22, leading=30, textColor=colors.HexColor("#243B5C"), spaceBefore=14, spaceAfter=8)  # [B28] h1 22pt · 브랜드 네이비
    # h1_toc: h1 과 모양 동일하되 목차 페이지 추적 대상(afterFlowable 가 style.name 으로 식별)
    h1_toc = PS("H1TOC", fontName=_KG, fontSize=22, leading=30, textColor=colors.HexColor("#243B5C"), spaceBefore=14, spaceAfter=8)
    h2 = PS("H2", fontName=_KG, fontSize=18, leading=26, textColor=colors.HexColor("#243B5C"), spaceBefore=10, spaceAfter=6)  # [B28] h2 18pt · 브랜드 네이비
    sw = PS("SW", fontName=_KG, fontSize=16, leading=23, textColor=colors.HexColor("#243B5C"), leftIndent=0)  # [B28][B29] sw 16pt 네이비
    body = PS("B", fontName=_KS, fontSize=14, leading=20, textColor=black, leftIndent=8)  # [B28][B30] body 14pt+들여쓰기 8
    bul = PS("BL", fontName=_KS, fontSize=14, leading=20, textColor=black, leftIndent=14, firstLineIndent=-10)  # [B28] bul 14pt
    cap = PS("CP", fontName=_KS, fontSize=12, leading=16, textColor=black)  # [B28] cap 12pt
    PS("TOCE", fontName=_KS, fontSize=14, leading=20, textColor=black)  # [B28] toc_e 14pt  # 목차 항목명
    PS("TOCP", fontName=_KS, fontSize=12, leading=18, textColor=colors.HexColor("#475569"), alignment=TA_RIGHT)  # 목차 페이지(옅은 회색)
    # [목차룰] Executive Summary 강조 + TABLE OF CONTENTS 트래킹 라벨
    PS("TOCEE", fontName=_KG, fontSize=13, leading=20, textColor=colors.HexColor("#243B5C"))  # Exec Summary 강조
    PS("TOCPE", fontName=_KS, fontSize=13, leading=20, textColor=colors.HexColor("#243B5C"), alignment=TA_RIGHT)
    PS("TOCSE", fontName=_KS, fontSize=11, leading=16, textColor=colors.HexColor("#64748B"), leftIndent=16)  # 부록 하위
    PS("TOCSP", fontName=_KS, fontSize=11, leading=16, textColor=colors.HexColor("#64748B"), alignment=TA_RIGHT)
    toc_label = PS("TOCLbl", fontName="Helvetica", fontSize=9, leading=12, textColor=colors.HexColor("#94A3B8"))  # TABLE OF CONTENTS

    # 카테고리 한글 매핑 (표지·사이트 톤 통일) — _draw_cover 에서 사용
    _CAT_KO = {
        "tabular_ml": "정형 ML",
        "tabular_dl": "정형 DL",
        "timeseries": "시계열",
        "anomaly_detection": "이상 탐지",
        "anomaly": "이상 탐지",
    }
    # NOTE(2026-06-12): 옛 플로어블 표지 스타일/상수(_NAVY·cover_* 13종) 제거 —
    #   표지는 _draw_cover() 캔버스 단일 경로로 일원화(B5 표지룰). 색은 _BR_* 토큰만 사용.

    title_text = _clean_title(ctx.meta.user_intent)  # 비대/중복 intent 컷
    chosen = (ctx.model_selection.chosen or {}).get("name", "-")
    pm = ctx.evaluation.primary_metric or {}

    # [브랜드 표지] 사이트(ada-aiagent.com) 브랜드 — 캔버스 표지 색·데이터 (전부 ctx 출처, 하드코딩 없음)
    _BR_BG = colors.HexColor("#F4F6FB")
    _BR_NAVY = colors.HexColor("#243B5C")
    _BR_BLUE = colors.HexColor("#3A6FE0")
    _BR_LAV = colors.HexColor("#8478C8")
    _BR_PILL = colors.HexColor("#E7EEFB")
    _BR_BLUEBG = colors.HexColor("#EAF1FD")
    _BR_LAVBG = colors.HexColor("#ECEAFA")
    _BR_BORDER = colors.HexColor("#E3E8F2")
    _BR_DIV = colors.HexColor("#DCE3EF")
    _BR_MUTE = colors.HexColor("#8A96A8")
    _BR_SUB = colors.HexColor("#6B7891")
    _BR_LINE = colors.HexColor("#EEF1F7")
    try:
        from outputs.architect.skeletons.report_skeleton import _human_dataset_name as _hdn

        _cv_ds = _hdn(ctx)
    except Exception:
        _cv_ds = (ctx.dataset.dataset_name or "").strip() or "데이터셋"
    _cv_shape = ctx.dataset.shape or {}
    _cv_nrows = _cv_shape.get("rows", 0)
    _cv_ncols = _cv_shape.get("cols")
    _cv_subtitle = f"{_cv_ds} · {_cv_nrows:,}건" if (_cv_ds and _cv_nrows) else _cv_ds
    _cv_cat = _CAT_KO.get(ctx.meta.category or "", ctx.meta.category or "-")
    _cv_date = (ctx.meta.generated_at or "")[:10] or "-"
    _cv_cls = (ctx.meta.classification or "INTERNAL").upper()
    _cv_m1v = _fv(pm.get("value"))
    _cv_m1l = _ko_metric(pm.get("name")) if pm.get("name") else "주지표"
    _cv_m2v = f"{_cv_ncols:,}" if isinstance(_cv_ncols, int) and _cv_ncols else None
    _cv_m2l = "데이터 변수"

    # 목차 항목 — 본문에 실제로 렌더되는 파트만 (Executive Summary + 번호 섹션)
    toc_entries = []
    if plan.narrative_thread.setup:
        toc_entries.append("Executive Summary")
    for _sec in plan.sections:
        if _sec.id == "backup" or _sec.kind == "cover":
            continue
        if _sec.title:
            toc_entries.append(_sec.title)

    class _TocFlow(Flowable):
        """[B24 목차룰] 번호 뱃지 + Exec 하이라이트 + 점선 리더 + 선별 질문설명. entries=(번호,제목,설명,페이지,종류).

        설명(desc)은 1~7 분석 섹션에만 — '그 섹션이 답하는 관통질문'. Exec·결론·부록은 자명해 비움(설명 0).
        """

        def __init__(self, entries, width):
            Flowable.__init__(self)
            self.entries = entries
            self.width = width
            self.H = sum(
                34 if k == "exec" else (47 if (k == "main" and d) else 36 if k == "main" else 25)
                for _n, _t, d, _p, k in entries
            )

        def wrap(self, aw, ah):
            return (self.width, self.H)

        def _leader(self, c, x1, x2, y):
            c.saveState()
            c.setStrokeColor(colors.HexColor("#CBD5E1"))
            c.setLineWidth(1)
            c.setDash([1, 3])
            c.line(x1, y, x2, y)
            c.restoreState()

        def draw(self):
            _NV = colors.HexColor("#243B5C")
            _BL = colors.HexColor("#3A6FE0")
            _GR = colors.HexColor("#64748B")
            _EX = colors.HexColor("#EAF1FD")
            _SB = colors.HexColor("#7C8AA0")
            _DS = colors.HexColor("#6B7891")
            c = self.canv
            W = self.width
            y = self.H - 15
            for num, title, desc, pg, kind in self.entries:
                if kind == "exec":
                    c.setFillColor(_EX)
                    c.roundRect(0, y - 8, W, 30, 6, fill=1, stroke=0)
                    c.setFont(_KG, 15)
                    c.setFillColor(_NV)
                    c.drawString(14, y, title)
                    c.setFont(_KG, 13)
                    c.setFillColor(_BL)
                    c.drawRightString(W - 10, y, pg)
                    y -= 34
                elif kind == "main":
                    _two = bool(desc)
                    _by = y + 3 if _two else y
                    c.setFillColor(_NV)
                    c.roundRect(0, _by - 6, 25, 25, 6, fill=1, stroke=0)
                    c.setFont(_KG, 12.5)
                    c.setFillColor(colors.white)
                    c.drawCentredString(12.5, _by + 1, num)
                    c.setFont(_KG, 14.5)
                    c.setFillColor(_NV)
                    c.drawString(38, _by, title)
                    _tw = c.stringWidth(title, _KG, 14.5)
                    c.setFont(_KS, 12)
                    _pw = c.stringWidth(pg, _KS, 12)
                    self._leader(c, 38 + _tw + 12, W - _pw - 10, _by + 5)
                    c.setFillColor(_GR)
                    c.drawRightString(W, _by, pg)
                    if _two:
                        c.setFont(_KS, 10.5)
                        c.setFillColor(_DS)
                        c.drawString(38, y - 13, desc)
                        y -= 47
                    else:
                        y -= 36
                else:
                    _lbl = (num + "  " + title) if num else title
                    c.setFont(_KS, 11)
                    c.setFillColor(_SB)
                    c.drawString(44, y, _lbl)
                    _tw = c.stringWidth(_lbl, _KS, 11)
                    _pw = c.stringWidth(pg, _KS, 11)
                    self._leader(c, 44 + _tw + 10, W - _pw - 10, y + 4)
                    c.drawRightString(W, y, pg)
                    y -= 25

    def _exhibit(num, takeaway, kpis, unit, source, width):
        """[B-Exhibit] McKinsey식 5요소 exhibit 박스(flowable): 번호·결론제목·KPI비주얼·단위기간·출처주석.

        kpis=[(값, 라벨, 색hex)]. 결론제목(takeaway)이 핵심 — 제목만 읽어도 논리가 흐르게. 전부 ctx 출처.
        """
        _exn = PS("ExN", fontName=_KG, fontSize=9.5, textColor=colors.HexColor("#3A6FE0"), leading=13)
        _ext = PS("ExT", fontName=_KG, fontSize=14.5, textColor=colors.HexColor("#243B5C"), leading=20, spaceBefore=4, spaceAfter=2)
        _exs = PS("ExS", fontName=_KS, fontSize=9, textColor=colors.HexColor("#64748B"), leading=13)
        from reportlab.lib.enums import TA_CENTER
        from reportlab.pdfbase.pdfmetrics import stringWidth
        # [B-Exhibit] KPI 밴드 = 2행(숫자행/라벨행). 숫자=같은 베이스라인(BOTTOM)+가운데, 라벨=같은 줄 시작(TOP)+가운데.
        _num_ps = PS("ExKNum", fontName=_KG, fontSize=22, leading=24, alignment=TA_CENTER)
        _lbl_ps = PS("ExKLbl", fontName=_KS, fontSize=10, textColor=colors.HexColor("#6B7891"),
                     leading=13, alignment=TA_CENTER)
        _n = len(kpis) or 1
        _lbl_max = (width - 32) / _n - 18  # 라벨 한 줄 가용 폭(좌우 패딩 제외)

        def _lblbreak(s):
            # 한 줄에 들어가면 그대로. 길면 '연결구'를 자르지 않고 좋은 지점에서 한 번만 내림.
            if stringWidth(s, _KS, 10) <= _lbl_max:
                return s
            _mm = list(_re.finditer(r"\)\s+", s))  # 1순위: 괄호 묶음 뒤 → 뒤 연결구 통째로 다음 줄
            if _mm:
                _i = _mm[0].end()
                return s[:_i].rstrip() + "<br/>" + s[_i:].strip()
            _sp = [i for i, ch in enumerate(s) if ch == " "]  # 2순위: 중앙에 가장 가까운 공백
            if _sp:
                _md = len(s) / 2
                _i = min(_sp, key=lambda x: abs(x - _md))
                return s[:_i] + "<br/>" + s[_i + 1:]
            return s

        _nums, _lbls = [], []
        for _v, _l, _col in kpis:
            _nums.append(Paragraph(f'<font color="{_col}"><b>{_v}</b></font>', _num_ps))
            _lbls.append(Paragraph(_lblbreak(_l), _lbl_ps))
        _kt = Table([_nums, _lbls], colWidths=[(width - 32) / _n] * _n)
        _kt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F4F7FC")),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, 0), "BOTTOM"),   # 숫자행: 같은 베이스라인
            ("VALIGN", (0, 1), (-1, 1), "TOP"),      # 라벨행: 같은 줄에서 시작
            ("TOPPADDING", (0, 0), (-1, 0), 14), ("BOTTOMPADDING", (0, 0), (-1, 0), 3),
            ("TOPPADDING", (0, 1), (-1, 1), 3), ("BOTTOMPADDING", (0, 1), (-1, 1), 14),
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("LINEAFTER", (0, 0), (-2, -1), 0.5, colors.HexColor("#E3E8F2")),
        ]))
        _inner = [
            Paragraph(f"E X H I B I T &nbsp;&nbsp; {num}", _exn),
            Paragraph(takeaway, _ext), Spacer(1, 0.25 * cm), _kt, Spacer(1, 0.2 * cm),
            Paragraph(f"{unit}<br/>{source}", _exs),
        ]
        _box = Table([[_inner]], colWidths=[width])
        _box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FBFCFE")),
            ("BOX", (0, 0), (-1, -1), 1.2, colors.HexColor("#E3E8F2")),
            ("ROUNDEDCORNERS", [8, 8, 8, 8]),
            ("LEFTPADDING", (0, 0), (-1, -1), 20), ("RIGHTPADDING", (0, 0), (-1, -1), 20),
            ("TOPPADDING", (0, 0), (-1, -1), 16), ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
        ]))
        return KeepTogether([_box])

    def _build_story(toc_render):
        """flowable 리스트 생성. toc_render=None 이면 1차(페이지 측정)용 placeholder 목차.

        목차 헤딩(Executive Summary·각 섹션)은 style 'H1TOC' 로 찍어 afterFlowable 가
        시작 페이지를 순서대로 수집 → 2차에서 페이지 범위를 채운다.
        """
        flow = []
        # ── 표지: onFirstPage=_draw_cover 가 1페이지에 브랜드 캔버스 표지를 직접 드로잉.
        #     여기선 페이지 1 예약용 PageBreak 만 — 목차/본문은 2페이지부터.
        flow.append(PageBreak())

        # ── 목차 [B24 목차룰 보강 2026-06-11] 기준 매치
        # - 항목 ~ 페이지번호 사이 점선 (....) 채움 (3열 Table: 항목 | 점선 | 페이지)
        # - 9.x 부록 하위는 들여쓰기 + 옅은 회색 (toc_sub_e/toc_sub_p)
        # - 8번/9번 사이 본문↔부록 구분선 강화 (네이비 진한 LINEBELOW)
        if toc_entries:
            flow.append(Paragraph("목차", h1))
            flow.append(Paragraph("T A B L E &nbsp;&nbsp; O F &nbsp;&nbsp; C O N T E N T S", toc_label))
            flow.append(Spacer(1, 0.5 * cm))
            # [B24 목차룰] 항목 파싱 → (번호, 제목, 설명, 페이지, 종류). _TocFlow 가 뱃지·Exec하이라이트·점선·선별설명 렌더.
            # 설명 = 구조적·일반화(어떤 데이터든 동일) — 1~7 분석 섹션이 '답하는 관통질문'. Exec·결론·부록은 자명해 비움.
            _TOC_DESC = {
                "1": "무엇을, 왜 분석하는가",
                "2": "이 데이터로 답할 수 있는가",
                "3": "무엇이 결과를 가르는가",
                "4": "믿을 수 있는 절차인가",
                "5": "단순 기준보다 나은가",
                "6": "어디에 집중해야 하는가",
                "7": "무엇을, 어떻게 실행하는가",
            }
            _toc_rows = []
            for _idx, _label in enumerate(toc_entries):
                _pr = toc_render[_idx][1] if toc_render else ""
                _l = _label.strip()
                if _l.lower().startswith("executive"):
                    _toc_rows.append(("", _l, "", _pr, "exec"))
                elif _l.startswith(("9.1", "9.2", "9.3", "9.4")) or (_l.startswith(("부록", "Appendix")) and "·" in _l):
                    _ps = _l.split(None, 1)
                    _toc_rows.append((_ps[0], _ps[1] if len(_ps) > 1 else "", "", _pr, "sub"))
                else:
                    _mm = _re.match(r"^(\d+)\.?\s*(.*)$", _l)
                    if _mm:
                        _toc_rows.append((_mm.group(1), _mm.group(2), _TOC_DESC.get(_mm.group(1), ""), _pr, "main"))
                    else:
                        _toc_rows.append(("", _l, "", _pr, "main"))
            flow.append(_TocFlow(_toc_rows, 17 * cm))
            flow.append(PageBreak())

        # ── Executive Summary [회장님 Exec룰] BLUF · 관통질문/답 · 3기둥(왜) · hero exhibit · 권고 · 단서
        nt = plan.narrative_thread

        def _exec_hero(kpis=None, take="", unit="", src=""):  # hero — 비즈니스 KPI 우선, 없으면 모델지표 폴백
            if kpis:
                flow.append(_exhibit("1 · 핵심 비즈니스 KPI", take or "핵심 임팩트", kpis, unit or "단위: 추정치", src or "출처: ADA 분석", 17 * cm))
                return
            if not ctx.evaluation.metrics:
                return
            _pm = ctx.evaluation.primary_metric or {}
            _kc = ["#3A6FE0", "#243B5C", "#8478C8"]
            _kp = [(_fv(_m.get("value")), _ko_metric(_k), _kc[_j % 3])
                   for _j, (_k, _m) in enumerate(list(ctx.evaluation.metrics.items())[:3])]
            _pmk = _ko_metric(_pm.get("name")) if _pm.get("name") else "주지표"
            _tk = (f"{_pmk} {_fv(_pm.get('value'))}, 단순 추측을 결정적으로 상회해 도입 기준을 충족한다."
                   if _pm.get("value") is not None else "핵심 지표가 도입 판단의 기준이 된다.")
            _n = (ctx.dataset.shape or {}).get("rows", 0)
            _sr = f"출처: ADA 분석 · n = {_n:,} · 주: 검증셋 기준" if _n else "출처: ADA 분석 · 주: 검증셋 기준"
            flow.append(_exhibit("1 · 모델 성능 지표", _tk, _kp, "단위: 지표값(0~1 또는 %) · 기간: 전체 표본", _sr, 17 * cm))

        _pkg = _chairman_exec(ctx, plan)  # 회장 패키지(내용=skeleton). None 이면 기존 Exec 폴백.
        if _pkg and (getattr(nt, "headline", "") or nt.resolution or nt.conflict):
            flow.append(Paragraph("Executive Summary", h1_toc))
            flow.append(Paragraph(f"<b>{_nodash(_pkg['bluf'])}</b>", body))  # BLUF(결정 한 줄)
            flow.append(Spacer(1, 0.2 * cm))
            flow.append(Paragraph(  # 관통 질문 + 답
                f"<font color='#64748B'>관통 질문: {_nodash(_pkg['question'])}</font>  "
                f"<b><font color='#3A6FE0'>답: {_pkg['verdict']}</font></b>", cap))
            flow.append(Spacer(1, 0.32 * cm))
            for _i, (_pt, _pd) in enumerate(_pkg["pillars"], 1):  # 3기둥(왜)
                flow.append(Paragraph(f"<b><font color='#3A6FE0'>{_i}.</font> {_pt}</b>  {_nodash(_pd)}", body))
                flow.append(Spacer(1, 0.12 * cm))
            flow.append(Spacer(1, 0.6 * cm))  # 3기둥과 exhibit 사이 한 줄 호흡(붙지 않게)
            _exec_hero(_pkg.get("kpis"), _pkg.get("hero_take"), _pkg.get("hero_unit"), _pkg.get("hero_src"))  # hero = 비즈니스 KPI
            flow.append(Spacer(1, 0.3 * cm))
            _ask_t = Table([[Paragraph(f"<b>권고: {_nodash(_pkg['ask'])}</b>", sw)]], colWidths=[17 * cm])
            _ask_t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EAF1FD")),
                ("LEFTPADDING", (0, 0), (-1, -1), 14), ("RIGHTPADDING", (0, 0), (-1, -1), 14),
                ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ]))
            flow.append(_ask_t)  # 권고(now-what)
            flow.append(Spacer(1, 0.15 * cm))
            flow.append(Paragraph(f"<font color='#94A3B8'>{_nodash(_pkg['caveat'])}</font>", cap))  # 단서
        else:
            if getattr(nt, "headline", "") or nt.resolution or nt.conflict:
                flow.append(Paragraph("Executive Summary", h1_toc))
                if getattr(nt, "headline", ""):
                    flow.append(Paragraph(f"<b>{_nodash(nt.headline)}</b>", body))
                    flow.append(Spacer(1, 0.25 * cm))
                _rest = " ".join(s for s in [nt.conflict, nt.resolution, nt.recommendation] if s)
                if _rest:
                    flow.append(Paragraph(_nodash(_rest), body))
                flow.append(Spacer(1, 0.5 * cm))
            _exec_hero()
        flow.append(PageBreak())

        # ── 본문 섹션 (목차 추적 대상: H1TOC)
        for sec in plan.sections:
            if sec.id == "backup" or sec.kind == "cover":
                continue
            # [고아 헤딩 방지] 섹션 제목을 첫 렌더 슬라이드와 한 덩어리로 묶어, 제목만 남고 내용이 다음 장으로 밀리는 현상 차단
            _sec_head = [Paragraph(sec.title, h1_toc), Spacer(1, 0.35 * cm)]  # 규칙: 큰 제목 밑 한 줄 띄움
            _img_in_sec = 0  # 페이지당 차트 최대 2개 강제용
            _just_broke = False
            for sl in sec.slides:
                if sl.role == "meta" and sl.layout in ("cover", "agenda", "closing"):
                    continue
                sl_flow: list = [Paragraph(sl.title_ko or sl.id, h2)]
                if sl.so_what:  # 규칙: '핵심 —' 위아래 한 줄 띄움
                    sl_flow.append(Spacer(1, 0.2 * cm))
                    sl_flow.append(Paragraph(_nodash(f"핵심 — {sl.so_what}"), sw))
                    sl_flow.append(Spacer(1, 0.2 * cm))
                # 산문형 본문(라벨 + 단락) — 규칙: 소제목 사이 한 줄 더 띄움
                for _blk in (getattr(sl, "prose_blocks", None) or []):
                    if isinstance(_blk, (list, tuple)) and len(_blk) >= 2 and _blk[1]:
                        sl_flow.append(Spacer(1, 0.42 * cm))
                        if _blk[0]:  # 라벨 있으면 굵게, 없으면 단락만 (라벨 없는 흐름)
                            sl_flow.append(Paragraph(f"<b>{_blk[0]}</b>", sw))
                        sl_flow.append(Paragraph(_nodash(str(_blk[1])), body))
                for b in sl.body_outline:
                    sl_flow.append(Paragraph(f"• {_nodash(b)}", bul))
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
                            _grp.append(Paragraph(_nodash(vs.caption), cap))
                        sl_flow.append(KeepTogether(_grp))  # 규칙: 표는 절대 페이지 분할 금지
                elif vs and vs.type and vs.type != "text_only":
                    try:
                        if (vs.type or "") == "image_embed":
                            # 실 파이프라인 차트 PNG 직접 임베드 (재렌더 불가 → 원본)
                            png = _fetch_png((vs.spec or {}).get("path"))
                        else:
                            png = render_visual_to_png(vs, ctx, slide=sl)
                            png = _brandize_png(png)  # [PDF 전용] 차트 강조색 #185FA5→브랜드 블루 #3A6FE0
                        if png:
                            from PIL import Image as PI

                            with PI.open(png) as im:
                                ar = im.width / im.height
                            # [B6 EDA페이지룰] 페이지당 2개 강제 — width 13cm / height 상한 4.8cm
                            # (섹션 헤딩 + 차트 2개가 첫 페이지에도 확실히 같이 들어가도록 높이 축소)
                            w_cm = 13.0
                            h_cm = w_cm / ar
                            if h_cm > 4.8:
                                h_cm = 4.8
                                w_cm = h_cm * ar
                            sl_flow.append(Spacer(1, 0.2 * cm))
                            sl_flow.append(Image(png, width=w_cm * cm, height=h_cm * cm))
                            if vs.caption:
                                sl_flow.append(Paragraph(_nodash(vs.caption), cap))
                            has_img = True
                    except Exception:
                        pass
                sl_flow.append(Spacer(1, 0.25 * cm))
                if _sec_head is not None:  # [고아 헤딩 방지] 첫 렌더 슬라이드 앞에 섹션 제목 결합 → 절대 분리 안 됨
                    sl_flow = _sec_head + sl_flow
                    _sec_head = None
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
            if _sec_head is not None:  # 슬라이드가 하나도 안 그려진 섹션 → 제목만이라도 출력(누락 방지)
                flow.extend(_sec_head)
            # [부록압축 2026-06-12] 부록 섹션끼리 PageBreak 생략 → 9.1~9.4 밀집
            if not _just_broke and sec.kind != "appendix":
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
        # [공통 로고] 본문 우상단 — 연한 'ada studio' 워드마크 러닝 마크(우측 정렬, 표지=락업/본문=연한 워드마크)
        _lg_sz = 10.0
        _lg_y = A4[1] - 1.5 * cm
        _lg_ada_w = canvas.stringWidth("ada ", _KG, _lg_sz)
        _lg_studio_w = canvas.stringWidth("studio", _KG, _lg_sz)
        _lg_gap = _lg_sz * 1.05  # A 심볼 폭 + 여백
        _lg_x = A4[0] - 2 * cm - (_lg_gap + _lg_ada_w + _lg_studio_w)  # 우측 정렬
        _draw_brand_A(canvas, _lg_x, _lg_y - _lg_sz * 0.05, _lg_sz * 0.95, colors.HexColor("#9AA7BD"), 1.0)
        canvas.setFont(_KG, _lg_sz)
        canvas.setFillColor(colors.HexColor("#8794AC"))  # ada — 연한 네이비
        canvas.drawString(_lg_x + _lg_gap, _lg_y, "ada ")
        canvas.setFillColor(colors.HexColor("#9FB8EC"))  # studio — 연한 블루
        canvas.drawString(_lg_x + _lg_gap + _lg_ada_w, _lg_y, "studio")
        canvas.restoreState()

    def _draw_cover(cnv, _doc):
        """[B5 표지룰] ADA Studio 브랜드 표지 — onFirstPage 로 1페이지에 직접 드로잉(사이트 톤)."""
        W, H = A4
        M = 56.0
        cnv.setFillColor(_BR_BG)
        cnv.rect(0, 0, W, H, stroke=0, fill=1)
        cnv.setStrokeColor(_BR_BORDER)
        cnv.setLineWidth(1)
        cnv.rect(0.5, 0.5, W - 1, H - 1, stroke=1, fill=0)
        # (1) 로고 락업 — A 심볼 + "ada studio"(ada 네이비 / studio 블루)
        _draw_brand_A(cnv, M, H - 78, 24, _BR_NAVY, 2.4)
        cnv.setFont(_KG, 19)
        cnv.setFillColor(_BR_NAVY)
        _tx, _ty = M + 30, H - 74
        cnv.drawString(_tx, _ty, "ada ")
        _wa = cnv.stringWidth("ada ", _KG, 19)
        cnv.setFillColor(_BR_BLUE)
        cnv.drawString(_tx + _wa, _ty, "studio")
        # 태그라인 pill
        _px = _tx + _wa + cnv.stringWidth("studio", _KG, 19) + 14
        _pw = 128
        _round_card(cnv, _px, H - 78, _pw, 20, 10, _BR_PILL)
        cnv.setFont(_KS, 9.5)
        cnv.setFillColor(_BR_BLUE)
        cnv.drawCentredString(_px + _pw / 2, H - 71, "AI 데이터 분석 에이전트")
        # 분류 (우상단)
        cnv.setFont(_KG, 9.5)
        cnv.setFillColor(_BR_NAVY)
        cnv.drawRightString(W - M, H - 72, _cv_cls)
        # 구분선
        cnv.setStrokeColor(_BR_DIV)
        cnv.setLineWidth(1.1)
        cnv.line(M, H - 96, W - M, H - 96)
        # (2)(3) 보고서 종류 라벨 + 제목 + 데이터셋 부제
        cnv.setFont(_KS, 11)
        cnv.setFillColor(_BR_MUTE)
        cnv.drawString(M, H - 250, "데 이 터   분 석   종 합   보 고 서")
        # 제목 — 길면 자동 축소/2줄(우측 여백 넘침 방지)
        _tlines, _tsz = _wrap_title(cnv, title_text, _KG, W - 2 * M)
        cnv.setFont(_KG, _tsz)
        cnv.setFillColor(_BR_NAVY)
        _ty0 = H - 296
        _lh = _tsz * 1.16
        for _i, _ln in enumerate(_tlines):
            cnv.drawString(M, _ty0 - _i * _lh, _ln)
        cnv.setFont(_KS, 14)
        cnv.setFillColor(_BR_SUB)
        cnv.drawString(M, _ty0 - len(_tlines) * _lh - 4, _cv_subtitle)
        # (4) 흰색 메타 카드 — 카테고리/주 모델/표본/생성
        _mc_y, _mc_h = H - 472, 130
        _round_card(cnv, M, _mc_y, W - 2 * M, _mc_h, 14, colors.white, _BR_BORDER)
        _rows = [
            ("분석 카테고리", str(_cv_cat)),
            ("주 모델", str(chosen)),
            ("표본 수", f"{_cv_nrows:,}건" if _cv_nrows else "-"),
            ("생성", _cv_date),
        ]
        _ry = _mc_y + _mc_h - 30
        for _k, _v in _rows:
            cnv.setFont(_KS, 12.5)
            cnv.setFillColor(_BR_MUTE)
            cnv.drawString(M + 22, _ry, _k)
            cnv.setFont(_KG, 12.5)
            cnv.setFillColor(_BR_NAVY)
            cnv.drawRightString(W - M - 22, _ry, _v)
            if _k != "생성":
                cnv.setStrokeColor(_BR_LINE)
                cnv.setLineWidth(0.8)
                cnv.line(M + 22, _ry - 12, W - M - 22, _ry - 12)
            _ry -= 29
        # (5) KEY 지표 카드 — 좌(블루) 주지표 / 우(라벤더) 변수 수. 변수 없으면 주지표 full-width.
        _ky, _kh, _gap = H - 572, 84, 14
        if _cv_m2v:
            _kw = (W - 2 * M - _gap) / 2
            _round_card(cnv, M, _ky, _kw, _kh, 14, _BR_BLUEBG)
            cnv.setFont(_KG, 33)
            cnv.setFillColor(_BR_BLUE)
            cnv.drawString(M + 22, _ky + 34, _cv_m1v)
            cnv.setFont(_KS, 12.5)
            cnv.setFillColor(_BR_SUB)
            cnv.drawString(M + 22, _ky + 15, _cv_m1l)
            _round_card(cnv, M + _kw + _gap, _ky, _kw, _kh, 14, _BR_LAVBG)
            cnv.setFont(_KG, 33)
            cnv.setFillColor(_BR_LAV)
            cnv.drawString(M + _kw + _gap + 22, _ky + 34, _cv_m2v)
            cnv.setFont(_KS, 12.5)
            cnv.setFillColor(_BR_SUB)
            cnv.drawString(M + _kw + _gap + 22, _ky + 15, _cv_m2l)
        else:
            _round_card(cnv, M, _ky, W - 2 * M, _kh, 14, _BR_BLUEBG)
            cnv.setFont(_KG, 33)
            cnv.setFillColor(_BR_BLUE)
            cnv.drawString(M + 22, _ky + 34, _cv_m1v)
            cnv.setFont(_KS, 12.5)
            cnv.setFillColor(_BR_SUB)
            cnv.drawString(M + 22, _ky + 15, _cv_m1l)
        # (6) 푸터 — 도메인 + 라벨
        cnv.setStrokeColor(_BR_DIV)
        cnv.setLineWidth(1.1)
        cnv.line(M, 108, W - M, 108)
        cnv.setFont(_KG, 11.5)
        cnv.setFillColor(_BR_BLUE)
        cnv.drawString(M, 88, "ada-aiagent.com")
        cnv.setFont(_KS, 10.5)
        cnv.setFillColor(_BR_MUTE)
        cnv.drawRightString(W - M, 88, "DATA-DRIVEN INSIGHT REPORT")

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
        d1.build(_build_story(None), onFirstPage=_draw_cover, onLaterPages=_foot)
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
    doc.build(_build_story(toc_render), onFirstPage=_draw_cover, onLaterPages=_foot)
    return str(out)


def _fallback(plan, output_path):
    out = Path(str(output_path) + ".txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"[PDF Fallback {plan.skeleton}]", encoding="utf-8")
    return str(out)
