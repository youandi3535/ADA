"""outputs.architect — ReportPlan 동적 목차 설계 (Phase 2).

ReportArchitect 가 ``ReportContext`` + 청중 + 출력형식 으로부터 보고서 목차를 동적
생성. 등록된 Skeleton 중 적합 1개 선정 + 길이 조정 + Pyramid/MECE 검증.

핵심:
    architect.py             — 메인 진입점 + Skeleton 선정 로직
    audience_adapter.py      — 청중 자동 추정 (c_level/manager/analyst/external_client)
    skeletons/               — Skeleton 1종 (ML Pitch). 카테고리별 추가 예정 (HJ 2026-06-08).
    plan.py                  — ReportPlan / SectionSpec / SlideSpec dataclass
    length_adjuster.py       — 10~20 hard limit 조정
    message_tree.py          — Pyramid Principle 강제
    mece_validator.py        — MECE 자가 검증
    domain_enricher.py       — KB·웹 인용 보강
    business_impact_quantifier.py — metric → 비즈니스 단위 환산

Public re-exports (편의용).
"""

from outputs.architect.plan import (  # noqa: F401
    SLIDE_LAYOUT_TOKENS,
    SLIDE_ROLES,
    MessageNode,
    NarrativeThread,
    ReportPlan,
    SectionSpec,
    SlideSpec,
)
