"""agents.handlers — 카테고리 종주 핸들러 패키지 (Day 0 H0-1 골격).

각 카테고리 폴더(``timeseries`` / ``anomaly`` / ``tabular``) 는 한 멤버 단독.
공유 에이전트(`agents/data_profiler.py` 등) 는 본 패키지의 핸들러로 dispatch.

다른 멤버 폴더는 **읽기만**, 수정은 단독 담당자만.

서브 패키지:
    timeseries/   ← CS 단독
    anomaly/      ← NY 단독
    tabular/      ← jh 단독 (tabular_ml + tabular_dl 공통)
    common/       ← HJ 단독 (카테고리 무관 헬퍼)
"""

from agents.handlers._base import (  # noqa: F401
    HANDLER_REGISTRY,
    HandlerProtocol,
    get_handler,
    register_handler,
)
