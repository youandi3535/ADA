"""outputs.localization — 한국어 포맷·종결어미·단위 (Phase 5).

영어 버전은 향후 추가 — 현재는 한국어만.

모듈:
    korean.py        — 종결어미 / 만·억 단위 / 날짜 / 통화
    formatters.py    — 공통 숫자·퍼센트 포맷 (로케일 무관)
"""

from outputs.localization.formatters import (  # noqa: F401
    format_decimal,
    format_int_with_commas,
    format_percent,
)
from outputs.localization.korean import (  # noqa: F401
    enforce_ending_consistency,
    format_currency_ko,
    format_date_ko,
    format_datetime_ko,
    format_number_ko,
)
