"""ada.error_handler.generated_fixers — 자동 생성 Tier 0 Fixer.

⚠️  이 파일은 fixer_promoter.py 가 자동으로 생성·업데이트한다. 직접 편집 금지.

생성 원리:
    Tier 1/2/3 에서 동일·유사 패턴이 PROMOTE_THRESHOLD(기본 3) 회 이상
    성공 자동 수정되면 → Claude 가 패턴을 분석해 이 파일에 fixer 함수를 자동 추가.
    새 변형(variation) 이 관찰될 때마다 기존 함수에 elif 분기가 추가됨.

함수 시그니처: (error_message: str, stack_trace: str) -> dict | None
"""

from __future__ import annotations

# static_fixers.py 의 유틸 함수 재사용

# =============================================================================
# 자동 생성 fixer 함수들이 아래에 추가됨 — fixer_promoter 가 관리
# =============================================================================


# GENERATED_FIXERS_START
# GENERATED_FIXERS_END


def get_generated_fixers() -> list:
    """현재 파일에 정의된 _fix_gen_* 함수 목록 반환."""
    import sys

    module = sys.modules[__name__]
    return [obj for name, obj in vars(module).items() if name.startswith("_fix_gen_") and callable(obj)]
