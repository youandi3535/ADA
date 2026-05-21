"""agents.handlers._base — 핸들러 인터페이스 + 레지스트리 (HJ 단독).

각 카테고리 핸들러는 다음 모듈을 갖는다 (모두 선택):
    profiler.profile(df, state) -> dict        # 데이터 프로파일 보강
    preprocessor.plan(state) -> list[dict]     # 전처리 계획 fallback
    preprocessor.apply(df, plan, state) -> df  # 카테고리별 step 적용
    eda.charts(df, state) -> list[str]         # 차트 MinIO 경로
    selector.score(state, recipes) -> dict     # {top3, rationale, citations}
    evaluator.evaluate(state) -> dict          # eval_result
    insight.generate(state) -> str             # 인사이트 텍스트
    output_extras.assets(state) -> dict        # OUT-04 등에 임베드할 추가 자산
    proposer.g1(state)/g2(state) -> list[dict] # 게이트 fallback 제안

핸들러는 모두 ``async`` 함수가 권장이지만 동기 함수도 허용. dispatcher 가 awaitable 확인.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Protocol


class HandlerProtocol(Protocol):
    """카테고리 핸들러 모듈 시그니처 — 모두 선택 구현."""

    # 각 함수는 모듈 레벨 함수 (클래스 아님)
    # 미구현 시 dispatcher 가 sensible default 사용


# (category, capability) -> callable
HANDLER_REGISTRY: Dict[str, Dict[str, Callable[..., Any]]] = {
    "timeseries":         {},
    "anomaly_detection":  {},
    "tabular_ml":         {},
    "tabular_dl":         {},
}


def register_handler(category: str, capability: str, fn: Callable[..., Any]) -> None:
    """런타임에 핸들러 함수 등록 (Day 1+ 멤버가 호출)."""
    if category not in HANDLER_REGISTRY:
        HANDLER_REGISTRY[category] = {}
    HANDLER_REGISTRY[category][capability] = fn


def get_handler(category: str, capability: str) -> Callable[..., Any] | None:
    """카테고리·기능별 핸들러 함수 조회. 없으면 None."""
    return HANDLER_REGISTRY.get(category, {}).get(capability)


# tabular_ml 과 tabular_dl 은 핸들러를 공유하므로 _tabular 라는 alias 도 노출
# (각 멤버 모듈은 carefully — A: timeseries / B: anomaly / C: tabular 만 import)


def _auto_register_from_module(category: str, module: Any) -> None:
    """모듈의 'profile/plan/apply/charts/score/evaluate/generate/assets/g1/g2' 함수를
    자동으로 카테고리 핸들러에 등록."""
    capabilities = (
        "profile", "plan", "apply", "charts", "score",
        "evaluate", "generate", "assets", "g1", "g2",
    )
    for cap in capabilities:
        fn = getattr(module, cap, None)
        if callable(fn):
            register_handler(category, cap, fn)
