"""outputs.visuals.render — VisualSpec → PNG 파일 실 렌더링.

matplotlib 로 차트·다이어그램·KPI 카드·표를 PNG 로 그려서 carrier 가 임베드.
한국어 폰트 부재 환경 대응 — 차트 라벨은 영문/숫자 우선, 한국어는 fallback.
"""

from __future__ import annotations

import tempfile
from typing import Any, Optional

from outputs.architect.plan import SlideSpec, VisualSpec
from outputs.context.schema import ReportContext
from outputs.style.palette import get_palette

# ==============================================================
# matplotlib 설정 — 한국어 폰트 폴백
# ==============================================================

_MPL_READY = False

# 막대/카테고리용 distinct 색 팔레트 (구분 잘 되게)
_PALETTE = ["#185FA5", "#1D9E75", "#D85A30", "#7F77DD", "#BA7517", "#D4537E", "#0F6E56", "#993C1D"]


def _ensure_matplotlib() -> Optional[Any]:
    """matplotlib import + 한국어 폰트 폴백 설정. 실패 시 None."""
    global _MPL_READY
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        if not _MPL_READY:
            # 한국어 폰트 — koreanize_matplotlib 가 있으면 import 만으로 자동 등록
            try:
                import koreanize_matplotlib  # noqa: F401
            except Exception:
                pass
            # 한국어 폰트 후보 — 시스템에 있는 것 검색 (koreanize_matplotlib 가 NanumGothic 등록)
            import matplotlib.font_manager as fm

            ko_candidates = (
                "Pretendard",  # HJ 2026-06-08: worker 도 Dockerfile fc-cache 등록 후 1순위
                "NanumGothic",
                "Noto Sans CJK KR",
                "Noto Sans KR",
                "Malgun Gothic",
                "AppleGothic",
                "Apple SD Gothic Neo",
                "Baekmuk Gulim",
                "UnDotum",
            )
            installed = {f.name for f in fm.fontManager.ttflist}
            chosen = next((k for k in ko_candidates if k in installed), None)
            if chosen:
                plt.rcParams["font.family"] = chosen
                plt.rcParams["axes.unicode_minus"] = False
            # 일반 스타일
            plt.rcParams["figure.facecolor"] = "white"
            plt.rcParams["axes.facecolor"] = "white"
            plt.rcParams["axes.edgecolor"] = "#CBD5E1"
            plt.rcParams["axes.labelcolor"] = "#334155"
            plt.rcParams["xtick.color"] = "#64748B"
            plt.rcParams["ytick.color"] = "#64748B"
            plt.rcParams["axes.grid"] = True
            plt.rcParams["grid.color"] = "#E2E8F0"
            plt.rcParams["grid.linestyle"] = "--"
            plt.rcParams["grid.alpha"] = 0.6
            _MPL_READY = True
        return plt
    except Exception:
        return None


# ==============================================================
# 공개 API
# ==============================================================


def render_visual_to_png(vs: VisualSpec, ctx: ReportContext, *, slide: SlideSpec | None = None) -> Optional[str]:
    """VisualSpec → PNG 파일 경로. 실패 시 None."""
    plt = _ensure_matplotlib()
    if plt is None:
        return None

    palette = get_palette(ctx.meta.category)
    primary = palette["primary"]
    accent = palette["accent"]
    secondary = palette["secondary"]

    # jh 2026-06-12 — 실제 분석 차트 PNG (MinIO) 최우선.
    # 운영 결함: EDA 슬라이드 spec 의 chart_path 가 무시되고 _render_bar 가
    # evaluation.metrics 로 폴백 → 결측 슬라이드에 메트릭 차트가 그려졌음.
    # (v2) fetch 가 예외를 던지면 함수 전체가 죽어 히트맵 분기에 못 가던 결함 — try 보호.
    _chart_path = str((vs.spec or {}).get("chart_path") or "")
    if _chart_path:
        try:
            _local = _fetch_chart_png(_chart_path)
            if _local:
                return _local
        except Exception as _fe:  # noqa: BLE001
            import logging

            logging.getLogger("visuals.render").warning(
                "chart_fetch_failed: %s err=%s", _chart_path[:80], _fe
            )

    try:
        vtype = vs.type or ""
        if vtype == "chart_line":
            return _render_line(vs, ctx, primary, accent, plt)
        if vtype == "chart_hbar":
            return _render_hbar(vs, ctx, primary, accent, plt)
        if vtype.startswith("chart_") or vtype == "bar":
            return _render_bar(vs, ctx, primary, accent, plt)
        if vtype == "diagram_process_linear":
            return _render_process_linear(vs, ctx, primary, accent, secondary, plt, slide)
        if vtype == "diagram_timeline_gantt":
            return _render_gantt(vs, ctx, primary, plt)
        if vtype == "diagram_tree":
            return _render_tree(vs, ctx, primary, plt)
        if vtype in (
            "table_feature_matrix",
            "table_score_card",
            "table_before_after",
            "table_risk_register",
            "table_pros_cons",
            "table_2x2_matrix",
        ):
            return _render_table(vs, ctx, primary, accent, plt, slide)
        if vtype == "kpi_cards":
            return _render_kpi_cards(vs, ctx, primary, plt, slide)
        if vtype == "kpi_single":
            return _render_kpi_single(vs, ctx, primary, plt, slide)
        if vtype == "risk_matrix":
            return _render_risk_matrix(vs, ctx, primary, plt)
        # jh 2026-06-12 — CM 수치 기반 히트맵 (MinIO 차트 부재 시에도 S15 시각화 보장)
        # belt: 타입이 달라도 spec 에 confusion_matrix 수치가 있으면 무조건 그림
        _cm_ctx = {}
        try:
            _cm_ctx = ctx.evaluation.confusion_matrix or {}
        except Exception:
            _cm_ctx = {}
        if vtype == "diagram_confusion_matrix" or (vs.spec or {}).get("confusion_matrix") or _cm_ctx:
            _p = _render_cm_heatmap(vs, primary, plt, ctx)
            if _p:
                return _p
        # jh 2026-06-12 — 세그먼트 성능 가로 막대 (skeleton 시점에 per_segment 가
        # 비어 segment_perf_table 로 굳어도 carrier 시점 ctx 로 차트 보장)
        if vtype == "segment_perf_table":
            _segs = (vs.spec or {}).get("segments") or []
            if not _segs:
                _segs = list(ctx.evaluation.per_segment or [])
            _items = [
                (str(s.get("segment") or s.get("name") or "?"), float(s["value"]))
                for s in _segs
                if isinstance(s, dict) and s.get("value") is not None
            ][:8]
            if _items:
                vs.spec = {**(vs.spec or {}), "items": _items}
                return _render_hbar(vs, ctx, primary, accent, plt)
        # 기타 — KPI 카드들 또는 일반 다이어그램
        return _render_generic_box(vs, ctx, primary, plt, slide)
    except Exception as exc:  # noqa: BLE001
        # jh 2026-06-12 — 무로그 실패 금지: S15·S16 차트가 조용히 사라지던 원인 추적용
        import logging

        logging.getLogger("visuals.render").warning(
            "render_visual_failed: type=%s slide=%s err=%s: %s",
            vs.type, getattr(slide, "id", "?"), type(exc).__name__, exc,
        )
        return None


# ==============================================================
# 각 타입별 렌더러
# ==============================================================


def _tmp_png() -> str:
    return tempfile.NamedTemporaryFile(suffix=".png", delete=False).name


def _render_cm_heatmap(vs, primary: str, plt, ctx=None) -> Optional[str]:
    """Confusion Matrix 2x2 히트맵 — spec.confusion_matrix 의 tn/fp/fn/tp 수치로 직접 그림.

    jh 2026-06-12 — MinIO 차트 경로가 없을 때도 S15 가 시각자료 없이
    KEY INSIGHTS 만 남던 결함의 안전망. 수치만 있으면 항상 그려진다.
    (v2) skeleton 빌드 시점엔 spec.confusion_matrix 가 빈 값으로 굳음 → carrier
    시점 ctx.evaluation.confusion_matrix 폴백 (S15 무차트의 진짜 원인).
    """
    cm = (vs.spec or {}).get("confusion_matrix") or {}
    if not cm and ctx is not None:
        try:
            cm = ctx.evaluation.confusion_matrix or {}
        except Exception:
            cm = {}
    try:
        tn = int(cm.get("tn") or cm.get("true_negative") or 0)
        fp = int(cm.get("fp") or cm.get("false_positive") or 0)
        fn = int(cm.get("fn") or cm.get("false_negative") or 0)
        tp = int(cm.get("tp") or cm.get("true_positive") or 0)
    except Exception:
        return None
    if (tn + fp + fn + tp) <= 0:
        return None

    import numpy as np

    mat = np.array([[tn, fp], [fn, tp]], dtype=float)
    fig, ax = plt.subplots(figsize=(7.2, 5.4), dpi=120)
    fig.patch.set_facecolor("white")
    ax.imshow(mat, cmap="Blues", vmin=0, vmax=mat.max() * 1.15)
    labels = [["TN", "FP"], ["FN", "TP"]]
    thresh = mat.max() * 0.55
    for r in range(2):
        for c in range(2):
            color = "#FFFFFF" if mat[r, c] > thresh else "#0F172A"
            ax.text(c, r - 0.12, labels[r][c], ha="center", va="center",
                    fontsize=15, color=color, fontweight="bold")
            ax.text(c, r + 0.16, f"{int(mat[r, c])}", ha="center", va="center",
                    fontsize=26, color=color, fontweight="bold")
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["Pred 0", "Pred 1"], fontsize=12, color="#475569")
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["True 0", "True 1"], fontsize=12, color="#475569")
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    if vs.title:
        ax.set_title(_ensure_ascii(vs.title), fontsize=15, color="#0F172A", pad=12,
                     loc="left", fontweight="bold")
    out = _tmp_png()
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def _fetch_chart_png(path: str) -> Optional[str]:
    """chart_path → 로컬 PNG. 로컬 파일이면 그대로, s3:// 면 MinIO 다운로드.

    실패 시 None — 호출측이 타입별 렌더러로 폴백 (jh 2026-06-12).
    """
    try:
        from pathlib import Path

        if path and not path.startswith("s3://") and Path(path).exists():
            return str(path)
    except Exception:
        pass
    try:
        from tools.minio_tool import get_minio_client

        mc = get_minio_client()
        key = path.replace(f"s3://{mc.bucket}/", "") if path.startswith("s3://") else path
        data = mc.download_bytes(key)
        if not data:
            return None
        tmp = _tmp_png()
        with open(tmp, "wb") as f:
            f.write(data)
        return tmp
    except Exception:
        return None


def _ensure_ascii(text: str) -> str:
    """한국어 폰트 없을 때 라벨 안 깨지게 영문 변환 — 핵심 한국어→영문 매핑.

    matplotlib 가 한국어 폰트를 가졌으면 그대로 두지만, 없으면 fallback.
    """
    if not text:
        return ""
    # 시스템 폰트 ok 면 그대로
    import matplotlib.pyplot as plt

    if plt.rcParams.get("font.family") not in ("DejaVu Sans", "sans-serif"):
        return text
    # ko→en 핵심 매핑
    mapping = {
        "이탈": "Churn",
        "정상": "Normal",
        "이상": "Anomaly",
        "성공": "Success",
        "실패": "Fail",
        "통과": "Pass",
        "현황": "Status",
        "문제": "Issue",
        "결과": "Result",
        "권고": "Action",
        "한계": "Limit",
        "기준": "Baseline",
    }
    out = text
    for ko, en in mapping.items():
        out = out.replace(ko, en)
    # 그래도 한국어 남으면 ASCII 만 유지
    return out


def _render_bar(vs: VisualSpec, ctx: ReportContext, primary: str, accent: str, plt) -> str:
    """막대 차트 — chart spec 의 items 또는 ctx.evaluation.metrics 활용."""
    spec = vs.spec or {}
    items = spec.get("items") or []
    # jh 2026-06-12 — items 가 dict 목록({feature/name, importance/value})이면 튜플로
    # 정규화. (S13 SHAP items 가 dict 라 i[0] 에서 죽고 메트릭 폴백 차트가
    # "SHAP Top 5" 제목 아래 그려지던 차트-본문 불일치 결함)
    if items and isinstance(items[0], dict):
        items = [
            (
                str(d.get("feature") or d.get("name") or d.get("label") or ""),
                float(d.get("importance") or d.get("value") or 0),
            )
            for d in items
            if isinstance(d, dict)
        ]
        items = [(k, v) for k, v in items if k]
    # SHAP 류 차트인데 items 가 비면 carrier 시점 ctx 에서 직접 보충
    # (skeleton 빌드 시점에 interpretation 이 비어 있던 경우의 안전망)
    if not items and vs.type == "chart_annotated_bar":
        try:
            items = [
                (str(g.feature), float(g.importance))
                for g in (ctx.interpretation.global_importance or [])[:5]
            ]
        except Exception:
            items = []
    # 슬라이드 고유 numbers (EDA meta) 가 metrics 폴백보다 우선.
    # (결측 슬라이드에 val_accuracy 막대가 그려지던 주제 불일치 방지)
    if not items:
        items = [
            (str(n.get("name", "")), float(n.get("value", 0)))
            for n in (spec.get("numbers") or [])[:6]
            if isinstance(n, dict) and isinstance(n.get("value"), (int, float))
        ]
    if not items and ctx.evaluation.metrics:
        items = [
            (k, float(m.get("value", 0)))
            for k, m in list(ctx.evaluation.metrics.items())[:6]
            if isinstance(m.get("value"), (int, float))
        ]
    if not items:
        items = [("primary", 0.5), ("baseline", 0.3)]
    labels = [_ensure_ascii(str(i[0]))[:20] for i in items]
    values = [float(i[1]) for i in items]

    max_v = max(values) if values else 1.0
    min_v = min(values) if values else 0.0
    spread = max_v - min_v
    # 값이 몰려 있으면(차이가 작으면) y축을 줌인해 차이를 보이게 — 진짜 비슷하면 그대로 0 기준
    zoomed = bool(min_v > 0 and spread > 0 and spread < 0.15 * max_v)
    if zoomed:
        if max_v <= 1.0:  # 비율(AUC 등) — 0.05 단위로 타이트하게 프레이밍 (8점대→9 가깝게)
            import math as _m

            y_lo = max(0.0, _m.floor(min_v * 20) / 20)
            y_hi = _m.ceil(max_v * 20) / 20 + 0.02
        else:
            y_lo, y_hi = max(0.0, min_v - spread * 0.55), max_v + spread * 0.6
    else:
        y_lo, y_hi = 0.0, max_v * 1.28
    y_off = (y_hi - y_lo) * 0.045

    # [좋은패턴][디자이너 라운드 2026-06-11] 시니어 차트 디자인 — max 막대만 강조, 나머지 묻힘
    # 메시지가 어느 값에 있는지 한눈에 보이게 (BCG/McKinsey 정석)
    _max_idx = values.index(max(values)) if values else -1
    # jh 2026-06-12 — 강조 막대색을 팔레트 primary 로 (하드코딩 #185FA5 가 색상
    # 교체에 안 따라가던 결함, 사용자 지적). 묻힘색은 중립 슬레이트 유지.
    _ACCENT = primary or "#185FA5"
    _MUTED = "#94A3B8"
    colors_list = [_ACCENT if i == _max_idx else _MUTED for i in range(len(values))]

    fig, ax = plt.subplots(figsize=(9, 4.8), dpi=120)
    fig.patch.set_facecolor("white")
    bars = ax.bar(labels, values, color=colors_list, width=0.38, zorder=3, edgecolor="none")
    for i, (bar, v) in enumerate(zip(bars, values)):
        y = bar.get_height()
        lbl = f"{v:.3f}" if 0 < v < 1 else (f"{int(v)}" if v == int(v) else f"{v:.1f}")
        # 강조 값에는 더 굵게 + 살짝 큰 폰트
        _fs = 22 if i == _max_idx else 19
        _fw = "bold" if i == _max_idx else "semibold"
        ax.text(
            bar.get_x() + bar.get_width() / 2, y + y_off, lbl,
            ha="center", va="bottom", fontsize=_fs, color="#0F172A", fontweight=_fw,
        )
    if vs.title:  # 제목은 옵션 (슬라이드 헤딩과 중복되면 빈 값으로 생략)
        ax.set_title(_ensure_ascii(vs.title), fontsize=17, color="#0F172A", pad=16, loc="left", fontweight="bold")
    if zoomed:
        ax.text(0.995, 1.01, "y축 확대", transform=ax.transAxes, ha="right", va="bottom", fontsize=11, color="#64748B")
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#CBD5E1")
    ax.tick_params(axis="x", colors="#0F172A", labelsize=18, length=0)  # x 라벨 크게·검정
    ax.tick_params(axis="y", colors="#475569", labelsize=12)
    ax.grid(axis="y", linestyle="-", color="#EEF2F6", linewidth=1.0, zorder=0)
    ax.set_axisbelow(True)
    ax.set_ylim(y_lo, y_hi)
    plt.xticks(rotation=0)  # 일자 (기울임 금지)
    plt.tight_layout()
    out = _tmp_png()
    plt.savefig(out, dpi=130, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def _render_line(vs: VisualSpec, ctx: ReportContext, primary: str, accent: str, plt) -> str:
    """선 차트 — 순서/추세가 있는 축(가입 기간 등)에 적합."""
    items = (vs.spec or {}).get("items") or []
    if not items:
        return _render_bar(vs, ctx, primary, accent, plt)
    labels = [_ensure_ascii(str(i[0]))[:20] for i in items]
    values = [float(i[1]) for i in items]
    x = list(range(len(values)))
    mx, mn = max(values), min(values)
    fig, ax = plt.subplots(figsize=(9, 4.8), dpi=120)
    fig.patch.set_facecolor("white")
    _lc = primary or "#185FA5"
    ax.plot(x, values, color=_lc, linewidth=3.5, marker="o", markersize=11,
            markerfacecolor=_lc, markeredgecolor="white", markeredgewidth=2.5, zorder=3)
    ax.fill_between(x, values, mn - (mx - mn + 1) * 0.3, color=_lc, alpha=0.07, zorder=1)
    for xi, v in zip(x, values):
        lbl = f"{int(v)}" if v == int(v) else f"{v:.1f}"
        ax.text(xi, v + (mx - mn + 1) * 0.05, lbl, ha="center", va="bottom", fontsize=21, color="#0F172A", fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    if vs.title:
        ax.set_title(_ensure_ascii(vs.title), fontsize=17, color="#0F172A", pad=16, loc="left", fontweight="bold")
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#CBD5E1")
    ax.tick_params(axis="x", colors="#0F172A", labelsize=18, length=0)
    ax.tick_params(axis="y", colors="#475569", labelsize=12)
    ax.grid(axis="y", color="#EEF2F6", linewidth=1.0, zorder=0)
    ax.set_axisbelow(True)
    ax.margins(y=0.2)
    plt.tight_layout()
    out = _tmp_png()
    plt.savefig(out, dpi=130, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def _render_hbar(vs: VisualSpec, ctx: ReportContext, primary: str, accent: str, plt) -> str:
    """가로 막대 — 범주가 많거나 라벨이 길 때 적합 (읽기 쉬움)."""
    items = (vs.spec or {}).get("items") or []
    if not items:
        return _render_bar(vs, ctx, primary, accent, plt)
    labels = [_ensure_ascii(str(i[0]))[:24] for i in items]
    values = [float(i[1]) for i in items]
    mx = max(values) if values else 1.0
    y = list(range(len(values)))[::-1]
    # jh 2026-06-12 — _render_bar 와 동일하게 팔레트 primary 강조 (하드코딩 제거)
    _max_idx = values.index(max(values)) if values else -1
    _ACCENT = primary or "#185FA5"
    _MUTED = "#94A3B8"    # 묻힘 색
    colors_list = [_ACCENT if i == _max_idx else _MUTED for i in range(len(values))]
    fig, ax = plt.subplots(figsize=(9, max(3.2, len(values) * 0.8)), dpi=120)
    fig.patch.set_facecolor("white")
    ax.barh(y, values, color=colors_list, height=0.42, zorder=3)  # 두께 절반(날씬하게)
    for yi, v in zip(y, values):
        lbl = f"{int(v)}" if v == int(v) else f"{v:.1f}"
        ax.text(v + mx * 0.02, yi, lbl, va="center", ha="left", fontsize=21, color="#0F172A", fontweight="bold")
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    if vs.title:
        ax.set_title(_ensure_ascii(vs.title), fontsize=17, color="#0F172A", pad=14, loc="left", fontweight="bold")
    for s in ("top", "right", "bottom"):
        ax.spines[s].set_visible(False)
    ax.tick_params(axis="y", colors="#0F172A", labelsize=18, length=0)
    ax.tick_params(axis="x", colors="#475569", labelsize=11)
    ax.set_xlim(0, mx * 1.18)
    ax.grid(axis="x", color="#EEF2F6", linewidth=1.0, zorder=0)
    ax.set_axisbelow(True)
    plt.tight_layout()
    out = _tmp_png()
    plt.savefig(out, dpi=130, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def _render_process_linear(
    vs: VisualSpec, ctx: ReportContext, primary: str, accent: str, secondary: str, plt, slide
) -> str:
    """좌→우 단계 박스 다이어그램."""
    spec = vs.spec or {}
    steps = (
        spec.get("steps")
        or spec.get("pipeline_steps")
        or [
            "Upload",
            "Profile",
            "Preprocess",
            "EDA",
            "Model",
            "Eval",
            "Output",
        ]
    )
    steps = [_ensure_ascii(str(s))[:18] for s in steps]
    n = len(steps)
    if n == 0:
        return ""
    fig, ax = plt.subplots(figsize=(10, 3.5), dpi=100)
    box_w = 1.6
    gap = 0.4
    total_w = n * box_w + (n - 1) * gap
    x0 = -total_w / 2
    for i, s in enumerate(steps):
        x = x0 + i * (box_w + gap)
        rect = plt.Rectangle((x, -0.5), box_w, 1.0, facecolor=primary, edgecolor="white", linewidth=2, alpha=0.92)
        ax.add_patch(rect)
        ax.text(x + box_w / 2, 0, s, ha="center", va="center", color="white", fontsize=10, fontweight="bold")
        # 화살표
        if i < n - 1:
            ax.annotate(
                "",
                xy=(x + box_w + gap, 0),
                xytext=(x + box_w, 0),
                arrowprops=dict(arrowstyle="->", color=secondary, lw=2),
            )
    ax.set_xlim(x0 - 0.5, x0 + total_w + 0.5)
    ax.set_ylim(-1.5, 1.5)
    ax.axis("off")
    ax.set_title(
        _ensure_ascii(vs.title or "Pipeline"), fontsize=13, color="#0F172A", pad=14, loc="left", fontweight="bold"
    )
    out = _tmp_png()
    plt.savefig(out, dpi=120, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def _render_gantt(vs: VisualSpec, ctx: ReportContext, primary: str, plt) -> str:
    """간트 차트 — 단순 horizontal bar."""
    events = (vs.spec or {}).get("events") or [
        {"phase": "Phase 1", "start": 0, "duration": 30},
        {"phase": "Phase 2", "start": 30, "duration": 60},
        {"phase": "Phase 3", "start": 90, "duration": 90},
    ]
    fig, ax = plt.subplots(figsize=(9, 3.5), dpi=100)
    labels = [_ensure_ascii(str(e.get("phase", f"P{i}")))[:24] for i, e in enumerate(events)]
    starts = [float(e.get("start_offset_days", e.get("start", 0))) for e in events]
    durations = [float(e.get("duration_days", e.get("duration", 30))) for e in events]
    y = list(range(len(events)))
    ax.barh(y, durations, left=starts, color=primary, edgecolor="white", height=0.6)
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlabel("Days")
    ax.set_title(
        _ensure_ascii(vs.title or "Roadmap"), fontsize=13, color="#0F172A", pad=12, loc="left", fontweight="bold"
    )
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    out = _tmp_png()
    plt.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out


def _render_tree(vs: VisualSpec, ctx: ReportContext, primary: str, plt) -> str:
    """간단 트리 다이어그램."""
    # 가설 트리는 보통 H1~H4 — 박스로 표현
    fig, ax = plt.subplots(figsize=(9, 5), dpi=100)
    root_text = _ensure_ascii(vs.spec.get("root", "Root") if vs.spec else "Root")[:20]
    rect = plt.Rectangle((-1.2, 1), 2.4, 0.8, facecolor=primary, edgecolor="white", linewidth=2)
    ax.add_patch(rect)
    ax.text(0, 1.4, root_text, ha="center", va="center", color="white", fontweight="bold", fontsize=11)
    # 4 자식 박스
    children = ["H1", "H2", "H3", "H4"]
    for i, c in enumerate(children):
        x = -4.5 + i * 3.0
        rect = plt.Rectangle((x - 1, -0.6), 2, 0.8, facecolor="#CBD5E1", edgecolor="white", linewidth=2)
        ax.add_patch(rect)
        ax.text(x, -0.2, c, ha="center", va="center", color="#0F172A", fontweight="bold")
        ax.plot([0, x], [1, 0.2], color="#94A3B8", lw=1.5)
    ax.set_xlim(-6, 6)
    ax.set_ylim(-1.5, 2.5)
    ax.axis("off")
    ax.set_title(
        _ensure_ascii(vs.title or "Hypothesis Tree"),
        fontsize=13,
        color="#0F172A",
        pad=12,
        loc="left",
        fontweight="bold",
    )
    out = _tmp_png()
    plt.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out


def _render_table(vs: VisualSpec, ctx: ReportContext, primary: str, accent: str, plt, slide) -> str:
    """표 — matplotlib table 로 컬러 헤더 표 렌더."""
    spec = vs.spec or {}
    # 기본 columns/rows — slide.body_outline 활용
    cols = spec.get("columns") or ["항목", "값"]
    rows = spec.get("rows")
    if not rows:
        # slide.body_outline 의 각 항목 → (label, value) 분리 시도
        rows = []
        if slide and slide.body_outline:
            for line in slide.body_outline[:8]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    rows.append([_ensure_ascii(k.strip())[:30], _ensure_ascii(v.strip())[:40]])
                else:
                    rows.append([_ensure_ascii(line)[:50], ""])
    if not rows:
        rows = [["data", "-"]]

    fig, ax = plt.subplots(figsize=(10, max(2, len(rows) * 0.35 + 1)), dpi=100)
    ax.axis("off")
    ax.set_title(
        _ensure_ascii(vs.title or "Table"), fontsize=13, color="#0F172A", pad=12, loc="left", fontweight="bold"
    )
    cell_text = [[_ensure_ascii(str(c))[:50] for c in row] for row in rows]
    col_labels = [_ensure_ascii(str(c)) for c in cols]
    tbl = ax.table(cellText=cell_text, colLabels=col_labels, loc="center", cellLoc="left")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.scale(1, 1.5)
    # 헤더 컬러
    for i in range(len(col_labels)):
        cell = tbl[(0, i)]
        cell.set_facecolor(primary)
        cell.set_text_props(color="white", weight="bold")
    # zebra striping
    for r in range(1, len(rows) + 1):
        for c in range(len(col_labels)):
            if r % 2 == 0:
                tbl[(r, c)].set_facecolor("#F8FAFC")
    out = _tmp_png()
    plt.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out


def _render_kpi_cards(vs: VisualSpec, ctx: ReportContext, primary: str, plt, slide) -> str:
    """KPI 카드 그리드 (3~6개)."""
    items: list[tuple[str, str, str]] = []
    # body_outline 첫 4개를 KPI 카드로
    if slide and slide.body_outline:
        for line in slide.body_outline[:6]:
            if ":" in line:
                k, v = line.split(":", 1)
                items.append((_ensure_ascii(k.strip())[:18], _ensure_ascii(v.strip())[:14], ""))
            else:
                items.append((_ensure_ascii(line)[:18], "—", ""))
    # 폴백 — 메트릭에서
    if not items and ctx.evaluation.metrics:
        for k, m in list(ctx.evaluation.metrics.items())[:4]:
            v = m.get("value")
            items.append((k, f"{v:.3f}" if isinstance(v, float) else str(v), ""))
    if not items:
        items = [("Metric", "—", "")]

    n = len(items)
    cols = 3 if n <= 3 else 4 if n == 4 else 3 if n == 6 else 4
    rows = (n + cols - 1) // cols
    fig, ax = plt.subplots(figsize=(10, rows * 2.5), dpi=100)
    ax.set_xlim(0, cols)
    ax.set_ylim(0, rows)
    ax.invert_yaxis()
    ax.axis("off")
    for i, (name, value, cap_) in enumerate(items):
        r, c = i // cols, i % cols
        # 박스
        ax.add_patch(plt.Rectangle((c + 0.05, r + 0.05), 0.9, 0.9, facecolor="#F8FAFC", edgecolor=primary, linewidth=2))
        # 라벨
        ax.text(c + 0.5, r + 0.22, name, ha="center", va="center", fontsize=10, color="#64748B")
        # 값
        ax.text(c + 0.5, r + 0.55, value, ha="center", va="center", fontsize=20, color=primary, fontweight="bold")
        # 캡션
        if cap_:
            ax.text(c + 0.5, r + 0.85, cap_, ha="center", va="center", fontsize=8, color="#94A3B8")
    ax.set_title(_ensure_ascii(vs.title or "KPI"), fontsize=13, color="#0F172A", pad=12, loc="left", fontweight="bold")
    out = _tmp_png()
    plt.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out


def _render_kpi_single(vs: VisualSpec, ctx: ReportContext, primary: str, plt, slide) -> str:
    """1개 큰 수치 카드."""
    pm = ctx.evaluation.primary_metric or {}
    value = pm.get("value", "—")
    name = pm.get("name", "Metric")
    value_str = f"{value:.3f}" if isinstance(value, float) else str(value)
    fig, ax = plt.subplots(figsize=(8, 3.5), dpi=100)
    ax.axis("off")
    ax.text(
        0.5,
        0.7,
        value_str,
        ha="center",
        va="center",
        fontsize=64,
        color=primary,
        fontweight="bold",
        transform=ax.transAxes,
    )
    ax.text(
        0.5, 0.25, _ensure_ascii(name), ha="center", va="center", fontsize=14, color="#64748B", transform=ax.transAxes
    )
    ax.set_title(
        _ensure_ascii(vs.title or "Key Number"), fontsize=13, color="#0F172A", pad=12, loc="left", fontweight="bold"
    )
    out = _tmp_png()
    plt.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out


def _render_risk_matrix(vs: VisualSpec, ctx: ReportContext, primary: str, plt) -> str:
    """[RiskMatrix] 2×2 리스크 매트릭스 — 확률(X) × 영향(Y) 사분면.

    spec.items: [(label, prob, impact), ...]  — prob/impact 는 0~1.
    사분면:
        좌하(낮음·낮음) = 무시 가능 (녹색)
        우하(높음·낮음) = 주의 (노랑)
        좌상(낮음·높음) = 모니터링 (노랑)
        우상(높음·높음) = 즉각 대응 (빨강)
    """
    items = (vs.spec or {}).get("items") or []
    fig, ax = plt.subplots(figsize=(9, 6), dpi=120)
    fig.patch.set_facecolor("white")
    # 사분면 배경 (axhspan/axvspan 사용)
    ax.fill_betweenx([0, 0.5], 0, 0.5, color="#D1FAE5", alpha=0.7, zorder=0)   # 좌하 녹색
    ax.fill_betweenx([0, 0.5], 0.5, 1.0, color="#FEF3C7", alpha=0.7, zorder=0)  # 우하 노랑
    ax.fill_betweenx([0.5, 1.0], 0, 0.5, color="#FEF3C7", alpha=0.7, zorder=0)  # 좌상 노랑
    ax.fill_betweenx([0.5, 1.0], 0.5, 1.0, color="#FECACA", alpha=0.7, zorder=0)  # 우상 빨강
    # 사분면 라벨 (모서리)
    ax.text(0.02, 0.97, _ensure_ascii("모니터링"), ha="left", va="top", fontsize=12, color="#92400E", fontweight="bold", zorder=2)
    ax.text(0.98, 0.97, _ensure_ascii("즉각 대응"), ha="right", va="top", fontsize=12, color="#991B1B", fontweight="bold", zorder=2)
    ax.text(0.02, 0.03, _ensure_ascii("무시 가능"), ha="left", va="bottom", fontsize=12, color="#065F46", fontweight="bold", zorder=2)
    ax.text(0.98, 0.03, _ensure_ascii("주의"), ha="right", va="bottom", fontsize=12, color="#92400E", fontweight="bold", zorder=2)
    # 격자 가운데 선
    ax.axhline(0.5, color="#475569", linewidth=1.5, zorder=1)
    ax.axvline(0.5, color="#475569", linewidth=1.5, zorder=1)
    # 리스크 점 + 라벨 (번호 표시)
    for idx, item in enumerate(items[:8], 1):
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            continue
        _label, prob, impact = str(item[0]), float(item[1]), float(item[2])
        # 점
        ax.scatter([prob], [impact], s=550, color=(primary or "#185FA5"), edgecolor="white", linewidth=2.5, zorder=4)
        ax.text(prob, impact, str(idx), ha="center", va="center", fontsize=14, color="white", fontweight="bold", zorder=5)
    # 축
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.02, 1.02)
    ax.set_xticks([0.25, 0.75])
    ax.set_xticklabels([_ensure_ascii("낮음"), _ensure_ascii("높음")], fontsize=13)
    ax.set_yticks([0.25, 0.75])
    ax.set_yticklabels([_ensure_ascii("낮음"), _ensure_ascii("높음")], fontsize=13)
    ax.set_xlabel(_ensure_ascii("확률 (Likelihood)"), fontsize=14, labelpad=8)
    ax.set_ylabel(_ensure_ascii("영향 (Impact)"), fontsize=14, labelpad=8)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_color("#94A3B8")
    ax.spines["bottom"].set_color("#94A3B8")
    plt.tight_layout()
    out = _tmp_png()
    plt.savefig(out, dpi=130, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def _render_generic_box(vs: VisualSpec, ctx: ReportContext, primary: str, plt, slide) -> str:
    """타입 매칭 실패 시 — 단순 텍스트 카드."""
    fig, ax = plt.subplots(figsize=(9, 4), dpi=100)
    ax.axis("off")
    ax.add_patch(
        plt.Rectangle(
            (0.05, 0.05), 0.9, 0.9, facecolor="#F8FAFC", edgecolor=primary, linewidth=2, transform=ax.transAxes
        )
    )
    ax.text(
        0.5,
        0.5,
        _ensure_ascii(vs.title or vs.type or "Visual"),
        ha="center",
        va="center",
        fontsize=14,
        color=primary,
        fontweight="bold",
        transform=ax.transAxes,
    )
