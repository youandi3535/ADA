"""agents.handlers.tabular — tabular_ml + tabular_dl 종주 (담당: jh).

다른 멤버는 본 폴더를 **읽기만**. 수정은 jh 단독.
tabular_ml 과 tabular_dl 은 코드 대부분을 공유하므로 한 폴더에서 관리.
"""

from agents.handlers._base import _auto_register_from_module
from agents.handlers.tabular import (
    eda,
    evaluator,
    insight,
    output_extras,
    preprocessor,
    profiler,
    proposer,
    selector,
)

for _cat in ("tabular_ml", "tabular_dl"):
    for _mod in (profiler, preprocessor, eda, selector, evaluator, insight, output_extras, proposer):
        _auto_register_from_module(_cat, _mod)
