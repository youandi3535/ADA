"""outputs.base — 산출물 생성기 추상 클래스 + 카테고리 훅 Protocol.

Day 9: _call_extras() 본구현 (카테고리 핸들러의 build/assets 호출).
ADR-008 L2: reattach_pii() 헬퍼 — carrier 의 사용자 노출 직전 PII 마스킹.
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
@runtime_checkable
class OutputExtrasHandler(Protocol):
    """Category output_extras function signature contract."""

    def __call__(
        self,
        state: "PipelineState",
        ctx: dict[str, Any],
    ) -> dict[str, Any]: ...


OUTPUT_EXTRAS_KEYS: tuple[str, ...] = (
    "charts",
    "tables",
    "text_blocks",
)


# ==============================================================
# 카테고리 테마 (Day 9)
# ==============================================================
CATEGORY_THEME: dict[str, dict[str, Any]] = {
    "tabular_ml": {
        "label_ko": "정형 ML",
        "primary_rgb": (37, 99, 235),
        "accent_rgb": (147, 197, 253),
        "primary_hex": "#2563eb",
    },
    "tabular_dl": {
        "label_ko": "정형 DL",
        "primary_rgb": (8, 145, 178),
        "accent_rgb": (103, 232, 249),
        "primary_hex": "#0891b2",
    },
    "timeseries": {
        "label_ko": "시계열",
        "primary_rgb": (22, 163, 74),
        "accent_rgb": (134, 239, 172),
        "primary_hex": "#16a34a",
    },
    "anomaly_detection": {
        "label_ko": "이상 탐지",
        "primary_rgb": (220, 38, 38),
        "accent_rgb": (252, 165, 165),
        "primary_hex": "#dc2626",
    },
}

DEFAULT_THEME: dict[str, Any] = {
    "label_ko": "기타",
    "primary_rgb": (75, 85, 99),
    "accent_rgb": (209, 213, 219),
    "primary_hex": "#4b5563",
}


def get_theme(category: str | None) -> dict[str, Any]:
    if not category:
        return DEFAULT_THEME
    return CATEGORY_THEME.get(category, DEFAULT_THEME)


# ==============================================================
# OutputGenerator — carrier 추상 클래스
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

    def _upload(self, local_path: str) -> str:
        from tools.minio_tool import get_minio_client

        return get_minio_client().save_artifact(local_path, f"outputs/{self.output_code}", self.job_id)

    def _tmp(self) -> str:
        return tempfile.NamedTemporaryFile(
            delete=False,
            suffix=f".{self.extension}",
        ).name

    def _call_extras(
        self,
        state: "PipelineState | None",
        ctx: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """카테고리 핸들러의 output_extras.build/assets 호출."""
        if state is None:
            return {}
        try:
            from agents.handlers import get_handler
        except Exception:
            return {}

        cat = getattr(state, "category", None)
        fn = get_handler(cat, "build") or get_handler(cat, "assets")
        if fn is None:
            # 카테고리에 build/assets 핸들러가 없는 것 자체는 정상(선택적 훅).
            # 하지만 디버깅 시 어떤 carrier 가 무엇을 못 받는지 추적할 수 있도록 debug 로 남김.
            try:
                from ada.core.logger import get_logger as _gl

                _gl("output_extras").debug("no_extras_handler", category=cat, carrier=type(self).__name__)
            except Exception:  # noqa: BLE001
                pass
            return {}
        try:
            result = fn(state, ctx or {})
            if not isinstance(result, dict):
                return {}
            return {k: v for k, v in result.items() if k in OUTPUT_EXTRAS_KEYS}
        except Exception as e:  # noqa: BLE001
            # 핸들러 자체 예외 → warning (silent 실패 방지)
            try:
                from ada.core.logger import get_logger as _gl

                _gl("output_extras").warning(
                    "extras_handler_failed",
                    category=cat,
                    carrier=type(self).__name__,
                    error=str(e),
                )
            except Exception:  # noqa: BLE001
                pass
            return {}

    def _download_chart(self, chart_path: str) -> str | None:
        """MinIO/S3 경로의 차트를 로컬 PNG 로 받아 임시 파일 경로 반환."""
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


# ==============================================================
# ADR-008 L2 — PII Re-attach 헬퍼 (모듈 레벨)
# ==============================================================


def reattach_pii(state: "PipelineState | None", text: str | None) -> str:
    """LLM 응답 / 사용자 인텐트 등 사용자 노출 직전 텍스트의 PII 를 *** 로 치환.

    1. state.category_extras['_pii']['mapping'] 의 토큰을 *** 로 치환
    2. PIIAnonymizer.reattach() 가 정규식 안전망도 적용
    3. state=None 또는 mapping 비어있어도 정규식 안전망 작동
    4. 보안 모듈 부재/예외 시에도 carrier 가 죽지 않게 silent passthrough

    R-103 (PII 로그 출력 금지) 의 최종 게이트.
    """
    if not text:
        return text or ""
    try:
        from ada.security.guardrails import PIIAnonymizer
    except Exception:
        return text

    mapping: dict[str, str] = {}
    if state is not None:
        try:
            pii_meta = (getattr(state, "category_extras", None) or {}).get("_pii") or {}
            mapping = pii_meta.get("mapping") or {}
        except Exception:
            mapping = {}

    try:
        return PIIAnonymizer().reattach(text, mapping)
    except Exception:
        return text
