"""outputs.architect.skeletons — Skeleton 1 종 (HJ 2026-06-08 정리).

기존 6 종 (SCQA/PSI/Pyramid/Analysis Standard/Comparative/Diagnostic) 삭제.
사용자가 ML Pitch 만 남기고 나머지 4 카테고리 (tabular_dl·timeseries·anomaly_detection)
용 Skeleton 을 하나씩 직접 추가 예정.

현재 등록:
    ML Pitch — ML 카테고리 전용 컨설팅·세일즈 피치 (20장 고정).
               Cover · Executive Summary · Agenda + 본문 16장 + Closing.
               컨설팅(Pyramid·Action Title·MECE) + FAANG(Baseline·Error Analysis·
               Segment·Monitoring) 표준 코드 레벨 강제.

추가 예정 (사용자 직접):
    Timeseries Pitch — 시계열 카테고리 전용
    Anomaly Pitch    — 이상탐지 카테고리 전용
    Tabular DL Pitch — 정형 DL 카테고리 전용

공통 규약 (모든 Skeleton 이 따라야 할 룰):
    - 모든 Skeleton 은 첫 슬라이드 = Cover, 두 번째 = Executive Summary, 세 번째 = Agenda.
    - 모든 Skeleton 은 마지막 슬라이드 = Closing.
    - 모든 Skeleton 의 본문에 기술스택 / 기술아키텍처 슬라이드 강제 삽입.
    - SlideSpec.so_what 은 Action Title 스타일 (완전 문장 결론).
    - body_outline 은 MECE 3개 기본, 5개 이내.
"""

from outputs.architect.skeletons.ml_pitch import build as build_ml_pitch  # noqa: F401

# Skeleton 이름 → build 함수 dispatch.
# 추가 시: from outputs.architect.skeletons.<name> import build as build_<name>
# SKELETON_REGISTRY["<Name>"] = build_<name>
SKELETON_REGISTRY = {
    "ML Pitch": build_ml_pitch,
}

SKELETON_NAMES = tuple(SKELETON_REGISTRY.keys())

# 기본 Skeleton — Architect 가 알 수 없는 이름을 받았을 때 폴백.
# 사용자가 새 Skeleton 을 카테고리별로 추가하면, ML 외 카테고리는
# 자기 Skeleton 으로 라우팅되도록 architect.pick_skeleton 에서 분기.
DEFAULT_SKELETON = "ML Pitch"
