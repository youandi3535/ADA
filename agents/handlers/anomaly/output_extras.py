"""agents.handlers.anomaly.output_extras — 이상탐지 산출물 추가 (NY 담당)."""

from __future__ import annotations

from typing import Any


def assets(state: Any, ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "charts": [],
        "tables": [],
        "text_blocks": [],
    }
