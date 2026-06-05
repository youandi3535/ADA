"""outputs.style.classification — 분류 마킹 (Phase 4, Part 8-7).

Public / Internal / Confidential / Strictly Confidential 4 등급.
각 등급별 footer 표시·헤더 띠·워터마크 정책.
"""

from __future__ import annotations

_CLASSIFICATION_TREATMENT: dict[str, dict[str, object]] = {
    "Public": {
        "footer_text": "PUBLIC",
        "footer_color": "#64748B",
        "header_band": False,
        "watermark": None,
        "redact_default": False,
    },
    "Internal": {
        "footer_text": "INTERNAL",
        "footer_color": "#334155",
        "header_band": False,
        "watermark": None,
        "redact_default": False,
    },
    "Confidential": {
        "footer_text": "CONFIDENTIAL",
        "footer_color": "#DC2626",
        "header_band": True,
        "header_band_color": "#DC2626",
        "watermark": None,
        "redact_default": True,
    },
    "Strictly Confidential": {
        "footer_text": "STRICTLY CONFIDENTIAL",
        "footer_color": "#DC2626",
        "header_band": True,
        "header_band_color": "#991B1B",
        "watermark": {"text": "STRICTLY CONFIDENTIAL", "opacity": 0.05, "angle": -30},
        "redact_default": True,
    },
}


def classification_treatment(classification: str) -> dict:
    """등급명 → 표시 정책. 알 수 없는 등급은 Internal 폴백."""
    return dict(_CLASSIFICATION_TREATMENT.get(classification, _CLASSIFICATION_TREATMENT["Internal"]))


def is_blocking(classification: str) -> bool:
    """공유 차단 등급 여부 (carrier 가 사전 검증)."""
    return classification in ("Confidential", "Strictly Confidential")
