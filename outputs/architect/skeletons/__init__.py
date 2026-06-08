"""outputs.architect.skeletons — Skeleton 2 종 (HJ 2026-06-08).

기존 6 종 (SCQA/PSI/Pyramid/Analysis Standard/Comparative/Diagnostic) 삭제.
사용자가 카테고리별 skeleton 을 하나씩 직접 추가.

현재 등록 (2종):
    ML Pitch — tabular_ml 카테고리 전용 컨설팅·세일즈 피치 (20장 고정).
               Cover · ExecSummary · Agenda + 본문 16장 + Closing.
               컨설팅(Pyramid·Action Title·MECE) + FAANG(Baseline·Error Analysis·
               Segment·Monitoring) 표준 코드 레벨 강제.
    DL Pitch — tabular_dl 카테고리 전용 (20장 고정).
               Cover · Agenda · ExecSummary + 본문 16장 + Closing.
               DL 특화 (Why DL·Architecture Deep·Training Dynamics·Calibration·
               Inference Cost·MLOps Stack) 표준 코드 레벨 강제.

추가 예정 (사용자 직접):
    Timeseries Pitch — 시계열 카테고리 전용
    Anomaly Pitch    — 이상탐지 카테고리 전용

공통 규약:
    - 모든 Skeleton 은 첫 슬라이드 = Cover.
    - 모든 Skeleton 은 마지막 슬라이드 = Closing (Thank You + Q&A).
    - SlideSpec.so_what 은 Action Title 스타일 (완전 문장 결론).
    - body_outline 은 MECE 3개 기본, 5개 이내.
"""

from outputs.architect.skeletons.dl_pitch import build as build_dl_pitch  # noqa: F401
from outputs.architect.skeletons.ml_pitch import build as build_ml_pitch  # noqa: F401

# Skeleton 이름 → build 함수 dispatch.
# 추가 시: from outputs.architect.skeletons.<name> import build as build_<name>
# SKELETON_REGISTRY["<Name>"] = build_<name>
SKELETON_REGISTRY = {
    "ML Pitch": build_ml_pitch,
    "DL Pitch": build_dl_pitch,
}

SKELETON_NAMES = tuple(SKELETON_REGISTRY.keys())

# 기본 Skeleton — pick_skeleton 이 미매칭 시 폴백.
DEFAULT_SKELETON = "ML Pitch"
