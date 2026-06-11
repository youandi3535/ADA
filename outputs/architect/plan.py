"""outputs.architect.plan — ReportPlan / SlideSpec dataclass (Phase 2 기초).

Architect 가 만들고, SlideContentGenerator·VisualGenerator·Carrier 가 소비하는
*동적 목차*. 보고서마다 다른 구조를 가질 수 있도록 dict 가 아닌 dataclass 로 정의.

핵심 데이터 모델:
    ReportPlan       — top-level (메타 + sections + narrative_thread + message_tree)
    SectionSpec      — 1 섹션 (id, title, kind, divider_required, slides[])
    SlideSpec        — 1 슬라이드 (layout 토큰, so_what, required_refs, visual_spec, ...)
    NarrativeThread  — setup/conflict/resolution 3문장 줄거리
    MessageNode      — Pyramid Principle 메시지 트리 노드

상수:
    SLIDE_LAYOUT_TOKENS  — 18종 layout 토큰 (Part 8-4)
    SLIDE_ROLES          — claim/evidence/caveat/action/transition 5종
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields as dc_fields, is_dataclass
from typing import Any, Optional

# ==============================================================
# 상수 — Layout & Role 화이트리스트
# ==============================================================

# 18 레이아웃 토큰 (Part 8-4 디자인 시스템과 1:1)
SLIDE_LAYOUT_TOKENS: tuple[str, ...] = (
    "cover",
    "agenda",
    "section_divider",
    "one_message",
    "one_message_big_number",
    "chart_callout",
    "chart_dual",
    "kpi_cards_3",
    "kpi_cards_4",
    "kpi_cards_6",
    "2x2_matrix",
    "process_flow",
    "process_flow_gantt",
    "comparison_table",
    "comparison_before_after",
    "quote",
    "appendix_table",
    "closing",
)

# Pyramid Principle 역할
SLIDE_ROLES: tuple[str, ...] = (
    "claim",  # 결론·주장
    "evidence",  # 근거·데이터
    "caveat",  # 한계·주의
    "action",  # 권고·실행
    "transition",  # 전환·연결
    "meta",  # 표지·목차·마무리 등 구조
)


# ==============================================================
# Dataclass — 줄거리 / 메시지 트리
# ==============================================================


@dataclass
class NarrativeThread:
    """보고서 줄거리 (Part 7-5). ES 는 headline(핵심 메세지) + 문제→원인→해결→대응."""

    headline: str = ""  # 핵심 메세지 1문장 — 결정권자가 이것만 봐도 되는 정수 (측정가능·단정조)
    setup: str = ""  # 문제 (상황)
    conflict: str = ""  # 원인 (핵심 동인)
    resolution: str = ""  # 해결 (결과 — 측정가능·기준선 대비)
    recommendation: str = ""  # 대응 (실행 방향)


@dataclass
class MessageNode:
    """Pyramid Principle 메시지 트리 1 노드 (Part 7-1)."""

    id: str = ""  # "root" / "claim_a" 등
    text: str = ""  # 1 줄 메시지
    role: str = "claim"  # SLIDE_ROLES 중 하나
    parent_id: Optional[str] = None  # root 면 None
    slide_ids: list[str] = field(default_factory=list)  # 이 메시지를 다루는 슬라이드들
    children: list[str] = field(default_factory=list)  # 자식 노드 id


# ==============================================================
# Dataclass — VisualSpec / SlideSpec
# ==============================================================


@dataclass
class VisualSpec:
    """비주얼 1개의 추상 명세 — VisualGenerator (Phase 3) 가 구체화.

    type 후보 (Part 9 카탈로그):
        diagram_*    : architecture_layered / process_linear / hub_spoke / agent_map / tree_diagram / funnel / timeline_gantt
        chart_*      : annotated_bar / annotated_line / scatter / histogram / heatmap / box / radar
        table_*      : feature_matrix / score_card / before_after / risk_register / pros_cons
        kpi_*        : single / delta / vs_baseline / trend_sparkline
        custom       : VisualGenerator 에 raw spec 위임
    """

    type: str = ""
    title: str = ""
    caption: str = ""
    spec: dict[str, Any] = field(default_factory=dict)  # type 별 구체 파라미터
    data_refs: list[str] = field(default_factory=list)  # 필요한 ReportContext ref_id
    severity: str = "info"  # info / important / critical — 색·강조 결정


@dataclass
class SlideSpec:
    """슬라이드 1장의 명세."""

    id: str = ""
    section_id: str = ""
    layout: str = "one_message"  # SLIDE_LAYOUT_TOKENS 중 하나
    role: str = "claim"  # SLIDE_ROLES 중 하나
    so_what: str = ""  # 상단 1줄 결론 (자체검증 통과본)
    body_outline: list[str] = field(default_factory=list)  # 본문 포인트 (각 ref_id 인용)
    visual_spec: Optional[VisualSpec] = None
    speaker_notes_hint: str = ""  # SlideContentGenerator 가 화자노트 생성 시 가이드
    data_refs: list[str] = field(default_factory=list)
    parent_message_id: Optional[str] = None  # Pyramid 부모 메시지
    contribution: str = ""  # 부모 메시지 어떻게 지지하는지
    thread_part: str = ""  # setup / conflict / resolution
    transition_in: str = ""  # 섹션 전환 시 연결구
    required_refs: list[str] = field(default_factory=list)  # 필수 ref_id (Architect 검증용)
    optional_refs: list[str] = field(default_factory=list)
    title_ko: str = ""  # 슬라이드 헤더 제목 (Section 명 또는 짧은 제목)
    prose_blocks: list[list[str]] = field(default_factory=list)  # [[라벨, 단락텍스트(<br/> 허용)], ...] — 산문형 본문


@dataclass
class SectionSpec:
    """섹션 1개 — 묶음 슬라이드 + 메타."""

    id: str = ""
    title: str = ""  # "Section 1 — 현황" 등
    kind: str = "evidence"  # cover / agenda / context / evidence / recommendation / appendix / closing
    divider_required: bool = False  # True 면 section_divider 슬라이드 자동 삽입
    slides: list[SlideSpec] = field(default_factory=list)
    short_summary: str = ""  # Agenda 슬라이드에 표기될 1줄 요약


# ==============================================================
# Top-level ReportPlan
# ==============================================================


@dataclass
class ReportPlan:
    """동적 보고서 목차 — Architect 산출.

    sections 는 Cover/Agenda/...(본문)/Closing 순. divider_required 섹션은
    carrier 가 자동으로 section_divider 슬라이드를 삽입.
    """

    skeleton: str = ""  # "SCQA" | "PSI" | "Pyramid" | ...
    audience: str = "analyst"  # 청중 final
    output_form: str = "pptx"  # "pptx" | "pdf" | "html" | "md"
    slide_count_target: int = 14  # length_adjuster 결과
    sections: list[SectionSpec] = field(default_factory=list)
    narrative_thread: NarrativeThread = field(default_factory=NarrativeThread)
    message_tree: list[MessageNode] = field(default_factory=list)
    citation_index: dict[str, str] = field(default_factory=dict)  # used_ref_id -> source_path 미러
    meta: dict[str, Any] = field(default_factory=dict)  # generated_at / architect_version 등
    warnings: list[str] = field(default_factory=list)  # Architect 자가 점검 메모

    # ----------------------------------------------------------
    # 직렬화
    # ----------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """state.report_plan 저장 가능 dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ReportPlan":
        """dict → ReportPlan. 누락 필드는 기본값."""
        if not data:
            return cls()
        return _hydrate(cls, data)

    # ----------------------------------------------------------
    # 조회 헬퍼
    # ----------------------------------------------------------

    def all_slides(self) -> list[SlideSpec]:
        out: list[SlideSpec] = []
        for s in self.sections:
            out.extend(s.slides)
        return out

    def slide_count(self) -> int:
        return sum(len(s.slides) for s in self.sections)

    def used_ref_ids(self) -> list[str]:
        ids: list[str] = []
        for s in self.sections:
            for sl in s.slides:
                ids.extend(sl.required_refs)
                ids.extend(sl.optional_refs)
                ids.extend(sl.data_refs)
                if sl.visual_spec:
                    ids.extend(sl.visual_spec.data_refs)
        # 중복 제거 (순서 보존)
        seen: set[str] = set()
        unique: list[str] = []
        for r in ids:
            if r and r not in seen:
                seen.add(r)
                unique.append(r)
        return unique


# ==============================================================
# 내부 hydrate (schema.py 와 동일 패턴)
# ==============================================================


def _hydrate(cls: type, data: Any) -> Any:
    if not is_dataclass(cls) or not isinstance(data, dict):
        return data
    try:
        from typing import get_type_hints

        hints = get_type_hints(cls)
    except Exception:
        hints = {f.name: f.type for f in dc_fields(cls)}
    field_map = {f.name: f for f in dc_fields(cls)}
    kwargs: dict[str, Any] = {}
    for k, v in data.items():
        if k not in field_map:
            continue
        kwargs[k] = _hydrate_value(hints.get(k), v)
    return cls(**kwargs)


def _hydrate_value(target_type: Any, value: Any) -> Any:
    if value is None:
        return None
    origin = getattr(target_type, "__origin__", None)
    args = getattr(target_type, "__args__", ())
    if origin is list and args and isinstance(value, list):
        item_type = args[0]
        if is_dataclass(item_type):
            return [_hydrate(item_type, v) if isinstance(v, dict) else v for v in value]
        return list(value)
    if origin is not None and args and isinstance(value, dict):
        non_none = [a for a in args if a is not type(None)]
        for arg in non_none:
            if is_dataclass(arg):
                return _hydrate(arg, value)
    if is_dataclass(target_type) and isinstance(value, dict):
        return _hydrate(target_type, value)
    return value
