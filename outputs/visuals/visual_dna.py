"""outputs.visuals.visual_dna — 보고서 단위 공유 스타일 시스템 (Phase 3, Part 11-3).

같은 보고서의 모든 차트·표·다이어그램이 동일 팔레트·축·범례·폰트를 사용하도록
한 번 고정 → 모든 비주얼이 이를 따른다.

데이터 → 색 매핑도 여기서 고정 (예: '이탈' = danger, '정상' = neutral).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from outputs.context.schema import ReportContext

# ==============================================================
# 카테고리별 컬러 팔레트 (outputs/base.py 의 CATEGORY_THEME 확장)
# ==============================================================

_CATEGORY_PALETTE: dict[str, dict[str, str]] = {
    "tabular_ml": {
        "primary": "#2563eb",
        "accent": "#93c5fd",
        "secondary": "#1e40af",
    },
    "tabular_dl": {
        "primary": "#0891b2",
        "accent": "#67e8f9",
        "secondary": "#155e75",
    },
    "timeseries": {
        "primary": "#16a34a",
        "accent": "#86efac",
        "secondary": "#15803d",
    },
    "anomaly_detection": {
        "primary": "#dc2626",
        "accent": "#fca5a5",
        "secondary": "#991b1b",
    },
}

# 의미 컬러 (전 카테고리 공통)
_SEMANTIC_COLORS: dict[str, str] = {
    "success": "#16A34A",
    "warning": "#D97706",
    "danger": "#DC2626",
    "info": "#2563EB",
    "ink_900": "#0F172A",
    "ink_700": "#334155",
    "ink_500": "#64748B",
    "ink_300": "#CBD5E1",
    "ink_100": "#F1F5F9",
    "white": "#FFFFFF",
}

# 데이터 의미 → 색 매핑 (휴리스틱)
_DATA_SEMANTIC_MAP: dict[str, str] = {
    "이탈": "danger",
    "churn": "danger",
    "이상": "danger",
    "anomaly": "danger",
    "정상": "info",
    "normal": "info",
    "baseline": "ink_500",
    "성공": "success",
    "달성": "success",
    "통과": "success",
    "실패": "warning",
    "미달": "warning",
}


# ==============================================================
# Typography
# ==============================================================

_TYPOGRAPHY: dict[str, dict[str, Any]] = {
    "cover_title": {"family": "Pretendard", "size_pt": 54, "weight": 800, "leading": 1.1},
    "slide_so_what": {"family": "Pretendard", "size_pt": 22, "weight": 700, "leading": 1.3},
    "section_header": {"family": "Pretendard", "size_pt": 36, "weight": 700, "leading": 1.2},
    "body": {"family": "Pretendard", "size_pt": 16, "weight": 400, "leading": 1.45},
    "body_strong": {"family": "Pretendard", "size_pt": 16, "weight": 600, "leading": 1.45},
    "caption": {"family": "Pretendard", "size_pt": 11, "weight": 400, "leading": 1.35},
    "footnote": {"family": "Pretendard", "size_pt": 9, "weight": 400, "leading": 1.3},
    "kpi_number": {"family": "Pretendard", "size_pt": 44, "weight": 700, "leading": 1.0},
    "kpi_unit": {"family": "Pretendard", "size_pt": 14, "weight": 500, "leading": 1.0},
    "code": {"family": "JetBrains Mono", "size_pt": 11, "weight": 400, "leading": 1.4},
}


# ==============================================================
# VisualDNA dataclass
# ==============================================================


@dataclass
class VisualDNA:
    """보고서 1편의 공유 스타일.

    Architect 가 1회 생성 → SlideContentGenerator / VisualGenerator / Carrier 가
    모두 이 객체만 참조 → 결과적으로 모든 비주얼이 동일 시각 언어를 가짐.
    """

    palette: dict[str, str] = field(default_factory=dict)  # primary/accent/secondary 등
    semantic: dict[str, str] = field(default_factory=dict)  # success/warning/...
    data_semantic_map: dict[str, str] = field(default_factory=dict)  # 단어 → semantic 키
    typography: dict[str, dict[str, Any]] = field(default_factory=dict)
    grid: dict[str, Any] = field(default_factory=dict)  # 12x8 그리드 (Phase 4)
    chart_defaults: dict[str, Any] = field(default_factory=dict)  # 축 스타일·범례 위치
    icon_set: str = "lucide"  # 아이콘 라이브러리

    # 보고서 단위 고정 매핑 — 같은 메트릭이 다른 슬라이드에서도 같은 색·축범위
    metric_color_map: dict[str, str] = field(default_factory=dict)
    metric_axis_range: dict[str, list[float]] = field(default_factory=dict)

    def color_for_data(self, label: str) -> str:
        """라벨 → 색 HEX. 의미 매핑 우선, 없으면 primary."""
        key = (label or "").strip().lower()
        # 이미 보고서 단위 매핑이 있으면 우선
        if key in self.metric_color_map:
            return self.metric_color_map[key]
        # 의미 매핑
        for token, semantic_key in self.data_semantic_map.items():
            if token in key:
                return self.semantic.get(semantic_key, self.palette.get("primary", "#2563eb"))
        return self.palette.get("primary", "#2563eb")

    def get_axis_range(self, metric_name: str) -> list[float] | None:
        """같은 메트릭은 모든 차트에서 동일 y 범위 (Part 11-3)."""
        return self.metric_axis_range.get(metric_name)


# ==============================================================
# 빌더
# ==============================================================


def default_dna(ctx: ReportContext) -> VisualDNA:
    """ReportContext 로부터 VisualDNA 1회 생성.

    Architect 의 ``build_plan`` 직후 호출 권장. 같은 ctx → 같은 DNA (결정론적).
    """
    palette = _CATEGORY_PALETTE.get(ctx.meta.category, _CATEGORY_PALETTE["tabular_ml"]).copy()
    dna = VisualDNA(
        palette=palette,
        semantic=dict(_SEMANTIC_COLORS),
        data_semantic_map=dict(_DATA_SEMANTIC_MAP),
        typography={k: dict(v) for k, v in _TYPOGRAPHY.items()},
        grid={"columns": 12, "rows": 8, "gutter_cm": 0.4, "margin_cm": {"x": 1.4, "y": 0.9}},
        chart_defaults={
            "legend_position": "bottom",
            "axis_color": _SEMANTIC_COLORS["ink_500"],
            "grid_color": _SEMANTIC_COLORS["ink_300"],
            "background": _SEMANTIC_COLORS["white"],
            "annotation_color": _SEMANTIC_COLORS["ink_900"],
        },
    )

    # 메트릭 컬러 고정 — primary_metric 은 primary 색, 나머지 metrics 는 ink_500
    pm_name = (ctx.evaluation.primary_metric or {}).get("name")
    if pm_name:
        dna.metric_color_map[pm_name.lower()] = palette["primary"]
    for mname in ctx.evaluation.metrics:
        dna.metric_color_map.setdefault(mname.lower(), palette["secondary"])

    # 메트릭 축 범위 고정 — value 가 [0, 1] 사이면 [0, 1]
    for mname, m in ctx.evaluation.metrics.items():
        v = m.get("value") if isinstance(m, dict) else None
        if isinstance(v, (int, float)) and 0 <= v <= 1:
            dna.metric_axis_range[mname] = [0.0, 1.0]

    return dna
