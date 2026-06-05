"""outputs.templates — 카테고리별 마스터 템플릿 spec (Phase 4).

실제 .pptx 마스터 파일 대신 *동적 생성용 spec dict*.
Phase 6 의 pptx_carrier 가 이 spec 으로 python-pptx 마스터 슬라이드를 매번 빌드.

이렇게 하는 이유:
    - 사내 자산 (학습용) 정책 — 외부 .pptx 파일 의존 최소.
    - 카테고리별 색·아이콘 차이만 spec 으로 표현.
    - 마스터 파일 손상·버전 충돌 위험 0.
"""

from outputs.templates.master_spec import MASTER_SPECS, get_master_spec  # noqa: F401
