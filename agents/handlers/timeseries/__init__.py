"""agents.handlers.timeseries — 시계열 카테고리 종주 (담당: CS).

다른 멤버는 본 폴더를 **읽기만**. 수정은 CS 단독.
8 모듈: profiler / preprocessor / eda / selector / evaluator / insight / output_extras / proposer
"""

from agents.handlers._base import _auto_register_from_module
from agents.handlers.timeseries import (
    eda,
    evaluator,
    insight,
    output_extras,
    preprocessor,
    profiler,
    proposer,
    selector,
)

for _mod in (profiler, preprocessor, eda, selector, evaluator, insight, output_extras, proposer):
    _auto_register_from_module("timeseries", _mod)
