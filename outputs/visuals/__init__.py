"""outputs.visuals — Diagram / Chart / Card / Table 생성 카탈로그 (Phase 3).

Phase 3 의 책임은 **spec 생성**. 실제 렌더링 (Mermaid → PNG, Plotly → PNG)
은 Phase 6 carrier 와 zip_bundler 가 담당.

모듈 구조:
    visual_dna.py    — 보고서 단위 공유 스타일 (한 번 고정 → 모든 비주얼 따름)
    selector.py      — SlideSpec.visual_spec.type 자동 선정
    diagrams/        — 9종 다이어그램 primitive (Mermaid spec 생성)
    charts/          — 8종 차트 annotator pattern (Plotly spec 생성)
    cards/           — 4종 KPI 카드
    tables/          — 5종 비교 표
"""

from outputs.visuals.selector import select_visual_type  # noqa: F401
from outputs.visuals.visual_dna import VisualDNA, default_dna  # noqa: F401
