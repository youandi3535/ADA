"""outputs.base — 산출물 생성기 추상 클래스 + 카테고리 훅 Protocol.

Day 9 변경:
    - `_call_extras()` stub → 본구현. 카테고리 핸들러의 build/assets 함수 호출.
    - `CATEGORY_THEME` — 4 카테고리 색상/테마 한 곳에 모음.
    - carrier 서브클래스(ppt/pdf/html_dashboard)가 이 hook 을 통해
      차트/테이블/텍스트 블록을 자동 임베드.
"""

from __future__ import annotations

import abc
import tempfile
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ada.core.state import PipelineState


# ==============================================================
# OutputExtrasHandler — Day 9 카테고리 훅 시그니처
# ==============================================================
# 각 카테고리의 ``agents/handlers/{cat}/output_extras.py`` 모듈의
# build 또는 assets 함수가 본 Protocol 을 만족해야 carrier 가 자동 호출.
#
# 수정 권한:
#   - 본 Protocol 시그니처: HJ 단독
#   - 구현 함수 build/assets(state, ctx): 각 카테고리 종주 (CS/NY/jh)
# ==============================================================


@runtime_checkable
class OutputExtrasHandler(Protocol):
    """Category output_extras function signature contract."""

    def __call__(
        self,
        state: "PipelineState",
        ctx: dict[str, Any],
    ) -> dict[str, Any]: ...


# 약속된 반환 키 (carrier 가 이 키들만 인식)
OUTPUT_EXTRAS_KEYS: tuple[str, ...] = (
    "charts",  # list[str]   — MinIO 경로 (PNG/SVG)
    "tables",  # list[dict]  — {"title": str, "rows": list[dict], "columns": list[str]}
    "text_blocks",  # list[str]   — 보조 텍스트 (한국어 prose 블록)
)


# ==============================================================
# 카테고리 테마 (Day 9) — PPT/PDF/HTML 모두 동일 팔레트
# ==============================================================
#
# RGB 튜플 (0-255), python-pptx/reportlab/HTML 모두에서 사용.
# 색상 의미:
#   tabular_ml:        파랑       — 정형 ML 기본
#   tabular_dl:        청록       — 정형 DL (ML 의 변종)
#   timeseries:        초록       — 성장/추세
#   anomaly_detection: 빨강       — 경고/이상
CATEGORY_THEME: dict[str, dict[str, Any]] = {
    "tabular_ml": {
        "label_ko": "정형 ML",
        "primary_rgb": (37, 99, 235),  # #2563eb
        "accent_rgb": (147, 197, 253),  # #93c5fd
        "primary_hex": "#2563eb",
    },
    "tabular_dl": {
        "label_ko": "정형 DL",
        "primary_rgb": (8, 145, 178),  # #0891b2
        "accent_rgb": (103, 232, 249),  # #67e8f9
        "primary_hex": "#0891b2",
    },
    "timeseries": {
        "label_ko": "시계열",
        "primary_rgb": (22, 163, 74),  # #16a34a
        "accent_rgb": (134, 239, 172),  # #86efac
        "primary_hex": "#16a34a",
    },
    "anomaly_detection": {
        "label_ko": "이상 탐지",
        "primary_rgb": (220, 38, 38),  # #dc2626
        "accent_rgb": (252, 165, 165),  # #fca5a5
        "primary_hex": "#dc2626",
    },
}

# 카테고리 미지정 시 기본 (회색)
DEFAULT_THEME: dict[str, Any] = {
    "label_ko": "기타",
    "primary_rgb": (75, 85, 99),
    "accent_rgb": (209, 213, 219),
    "primary_hex": "#4b5563",
}


def get_theme(category: str | None) -> dict[str, Any]:
    """카테고리 → 테마 dict 안전 조회."""
    if not category:
        return DEFAULT_THEME
    return CATEGORY_THEME.get(category, DEFAULT_THEME)


# ==============================================================
# OutputGenerator — carrier 추상 클래스 (5종 산출물 공통 베이스)
# ==============================================================


class OutputGenerator(abc.ABC):
    output_code: str = "OUT-XX"
    extension: str = "bin"

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id

    @abc.abstractmethod
    def generate(
        self,
        *,
        insights: str,
        best_model: dict[str, Any],
        eda_charts: list[str],
        category: str,
        user_intent: str,
        eval_result: dict[str, Any] | None,
    ) -> str:
        """생성 후 MinIO 경로 반환."""

    # --------------------------------------------------------------
    def _upload(self, local_path: str) -> str:
        from tools.minio_tool import get_minio_client

        return get_minio_client().save_artifact(local_path, f"outputs/{self.output_code}", self.job_id)

    def _tmp(self) -> str:
        return tempfile.NamedTemporaryFile(
            delete=False,
            suffix=f".{self.extension}",
        ).name

    # --------------------------------------------------------------
    # 카테고리 훅 호출 (Day 9 본구현)
    # --------------------------------------------------------------
    def _call_extras(
        self,
        state: "PipelineState | None",
        ctx: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """카테고리 핸들러의 output_extras.build/assets 호출.

        반환: ``{"charts": [...], "tables": [...], "text_blocks": [...]}``.
        핸들러 없거나 build/assets 함수가 없으면 빈 dict 반환 (안전).
        반환 dict 의 키 중 OUTPUT_EXTRAS_KEYS 에 없는 키는 제거됨.
        """
        if state is None:
            return {}
        try:
            from agents.handlers import get_handler
        except Exception:
            return {}

        # Day 9 계약: 우선 'build' (Protocol 권장), 미존재 시 'assets' (기존 호환)
        fn = get_handler(state.category, "build") or get_handler(state.category, "assets")
        if fn is None:
            return {}
        try:
            result = fn(state, ctx or {})
            if not isinstance(result, dict):
                return {}
            return {k: v for k, v in result.items() if k in OUTPUT_EXTRAS_KEYS}
        except Exception:
            return {}

    # --------------------------------------------------------------
    # MinIO 차트 다운로드 헬퍼 — 본 클래스에 집중시켜 ppt/pdf 중복 제거.
    # --------------------------------------------------------------
    def _download_chart(self, chart_path: str) -> str | None:
        """MinIO/S3 경로의 차트를 로컬 PNG 로 받아 임시 파일 경로 반환.

        실패 시 None. 호출자는 None 체크 후 skip.
        """
        try:
            from tools.minio_tool import get_minio_client

            mc = get_minio_client()
            key = chart_path.replace(f"s3://{mc.bucket}/", "") if chart_path.startswith("s3://") else chart_path
            body = mc.download_bytes(key)
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png").name
            with open(tmp, "wb") as f:
                f.write(body)
            return tmp
        except Exception:
            return None
