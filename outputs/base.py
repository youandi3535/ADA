"""outputs.base - 산출물 생성기 추상 클래스 + 카테고리 훅 Protocol."""

from __future__ import annotations

import abc
import tempfile
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ada.core.state import PipelineState


# ==============================================================
# OutputExtrasHandler - Day 9 카테고리 훅 시그니처 (사전 정의)
# ==============================================================
# Day 9 에 HJ 가 carrier (ppt/pdf/html_dashboard) 에서 본 Protocol 을
# 호출하는 본구현을 추가하지만, 시그니처는 미리 박아둬서 팀원이
# Day 1~8 동안 자기 handlers/{cat}/output_extras.py 를 본 형식에
# 맞춰 작성하게 함.
#
# 수정 권한:
#   - 본 Protocol 시그니처: HJ 단독
#   - 구현 함수 build(state, ctx): 각 카테고리 종주 (CS/NY/jh)
# ==============================================================


@runtime_checkable
class OutputExtrasHandler(Protocol):
    """Category output_extras function signature contract.

    각 카테고리의 ``agents/handlers/{cat}/output_extras.py`` 모듈의
    ``build`` 함수가 본 Protocol 을 만족해야 carrier 가 자동 호출.

    구현 예시 (handlers/timeseries/output_extras.py)::

        from typing import Any
        from ada.core.state import PipelineState

        def build(state: PipelineState, ctx: dict[str, Any]) -> dict[str, Any]:
            return {
                "charts":      [],
                "tables":      [],
                "text_blocks": [],
            }

    반환 dict 의 키는 carrier 가 알 수 있는 약속된 키만 사용.
    상세 키 스펙은 Day 9 HJ 머지 시점에 본 docstring 에 명시.
    """

    def __call__(
        self,
        state: "PipelineState",
        ctx: dict[str, Any],
    ) -> dict[str, Any]: ...


# 약속된 반환 키 (Day 9 본구현 시 carrier 가 이 키들만 인식)
OUTPUT_EXTRAS_KEYS: tuple[str, ...] = (
    "charts",  # list[str] - MinIO 경로 (PNG/SVG)
    "tables",  # list[dict] - 행 리스트
    "text_blocks",  # list[str] - 보조 텍스트
)


# ==============================================================
# OutputGenerator - carrier 추상 클래스 (5종 산출물 공통 베이스)
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
    # 카테고리 훅 호출 (Day 9 본구현 예정)
    # --------------------------------------------------------------
    def _call_extras(self, state: "PipelineState", ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        """Category output_extras hook caller (Day 9 stub).

        Day 9 carrier 본구현 시 본 메서드를 호출하여 카테고리별 차트/테이블
        을 끌어옴. handler 가 없거나 build 함수가 없으면 빈 dict 반환 (안전).

        본 메서드는 Day 9 HJ 본구현 전까지는 빈 dict 만 반환 (현재 stub).
        """
        # Day 9 본구현 시:
        #     from agents.handlers import get_handler
        #     handler = get_handler(state.category, "output_extras")
        #     if handler is None:
        #         return {}
        #     try:
        #         result = handler(state, ctx or {})
        #         return {k: v for k, v in result.items() if k in OUTPUT_EXTRAS_KEYS}
        #     except Exception:
        #         return {}
        return {}
