"""outputs.architect.skeletons — Skeleton 6 종 (Phase 2).

각 Skeleton 은 ``ReportContext`` 를 받아 ``ReportPlan`` 의 초안 (sections + slides)
을 생성하는 ``build(ctx, audience_profile, length_target) -> ReportPlan`` 함수를 노출.

6 종:
    SCQA              — 일반 분석 보고서 (Situation·Complication·Question·Answer·Evidence·Action)
    PSI               — 솔루션 제안형 (Problem·Solution·Impact)
    Pyramid           — C-level 브리핑 (결론 → 3 근거 → 권고)
    Analysis Standard — 학술·규제형 (배경·데이터·방법·결과·토의·한계·참고)
    Comparative       — 비교 의사결정 (기준·대안·매트릭스·민감도·권고)
    Diagnostic        — 이상·장애 진단 (증상·타임라인·가설·근본원인·조치·재발방지)

공통 규약:
    - 모든 Skeleton 은 첫 슬라이드 = Cover, 두 번째 = Executive Summary, 세 번째 = Agenda.
    - 모든 Skeleton 은 마지막 슬라이드 = Closing.
    - 모든 Skeleton 의 본문에 **기술스택 / 기술아키텍처 파이프라인** 슬라이드 강제 삽입
      (여유 ≥ 14장 → 2 슬라이드 분리, 12~13장 → 1 슬라이드 통합).
"""

from outputs.architect.skeletons.analysis_standard import build as build_analysis  # noqa: F401
from outputs.architect.skeletons.comparative import build as build_comparative  # noqa: F401
from outputs.architect.skeletons.diagnostic import build as build_diagnostic  # noqa: F401
from outputs.architect.skeletons.psi import build as build_psi  # noqa: F401
from outputs.architect.skeletons.pyramid import build as build_pyramid  # noqa: F401
from outputs.architect.skeletons.scqa import build as build_scqa  # noqa: F401

# Skeleton 이름 → build 함수 dispatch
SKELETON_REGISTRY = {
    "SCQA": build_scqa,
    "PSI": build_psi,
    "Pyramid": build_pyramid,
    "Analysis Standard": build_analysis,
    "Comparative": build_comparative,
    "Diagnostic": build_diagnostic,
}

SKELETON_NAMES = tuple(SKELETON_REGISTRY.keys())
