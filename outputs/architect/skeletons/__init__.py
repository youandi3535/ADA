"""outputs.architect.skeletons — Skeleton 4 종 (HJ 2026-06-08).

기존 6 종 (SCQA/PSI/Pyramid/Analysis Standard/Comparative/Diagnostic) 삭제.
사용자가 카테고리별 skeleton 을 직접 추가하여 4 카테고리 모두 완성.

현재 등록 (4종):
    ML Pitch         — tabular_ml 카테고리 전용 (20장 고정).
    DL Pitch         — tabular_dl 카테고리 전용 (20장 고정).
    Timeseries Pitch — timeseries 카테고리 전용 (20장 고정).
    Anomaly Pitch    — anomaly_detection 카테고리 전용 (20장 + 6 도메인 적응).

공통 규약:
    - 모든 Skeleton 은 첫 슬라이드 = Cover.
    - 모든 Skeleton 은 마지막 슬라이드 = Closing (Thank You + Q&A).
    - SlideSpec.so_what 은 Action Title 스타일 (완전 문장 결론).
    - body_outline 은 MECE 3개 기본, 5개 이내.
    - 슬라이드 6 의 title_ko = "현행 방식의 한계" 통일.

도메인 적응 (Anomaly Pitch 전용):
    fraud / industrial_iot / system_logs / security / quality_control / medical / generic
    슬라이드 5 (Why) · 14 (Threshold 비용) · 17 (ROI) 가 도메인별 텍스트로 자동 변경.
"""

from outputs.architect.skeletons.anomaly_pitch import build as build_anomaly_pitch  # noqa: F401
from outputs.architect.skeletons.dl_pitch import build as build_dl_pitch  # noqa: F401
from outputs.architect.skeletons.ml_pitch import build as build_ml_pitch  # noqa: F401
from outputs.architect.skeletons.timeseries_pitch import build as build_timeseries_pitch  # noqa: F401

# Skeleton 이름 → build 함수 dispatch.
SKELETON_REGISTRY = {
    "ML Pitch": build_ml_pitch,
    "DL Pitch": build_dl_pitch,
    "Timeseries Pitch": build_timeseries_pitch,
    "Anomaly Pitch": build_anomaly_pitch,
}

SKELETON_NAMES = tuple(SKELETON_REGISTRY.keys())

# 기본 Skeleton — pick_skeleton 이 미매칭 시 폴백.
DEFAULT_SKELETON = "ML Pitch"
