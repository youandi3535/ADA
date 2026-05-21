"""agents.handlers.anomaly — 이상탐지 카테고리 종주 (담당: B).

다른 멤버는 본 폴더를 **읽기만**. 수정은 B 단독.
"""
from agents.handlers._base import _auto_register_from_module
from agents.handlers.anomaly import (
    profiler, preprocessor, eda, selector,
    evaluator, insight, output_extras, proposer,
)

for _mod in (profiler, preprocessor, eda, selector,
             evaluator, insight, output_extras, proposer):
    _auto_register_from_module("anomaly_detection", _mod)
