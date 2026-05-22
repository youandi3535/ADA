"""SchemaValidator 룰 단위 테스트."""

from __future__ import annotations

from agents.schema_validator import CATEGORY_RULES, SchemaValidatorAgent


def test_tabular_ml_min_rows_fail():
    profile = {"rows": 50, "cols": 5, "has_target": True, "class_distribution": {"0": 0.5, "1": 0.5}}
    v = SchemaValidatorAgent._validate(profile, CATEGORY_RULES["tabular_ml"])
    assert not v["is_valid"]
    assert any("행 수" in e for e in v["errors"])


def test_tabular_ml_ok():
    profile = {
        "rows": 1000,
        "cols": 5,
        "has_target": True,
        "class_distribution": {"0": 0.6, "1": 0.4},
        "missing": {"a": 0.0},
    }
    v = SchemaValidatorAgent._validate(profile, CATEGORY_RULES["tabular_ml"])
    assert v["is_valid"]


def test_timeseries_requires_date():
    profile = {"rows": 200, "cols": 3, "has_target": True}
    v = SchemaValidatorAgent._validate(profile, CATEGORY_RULES["timeseries"])
    assert not v["is_valid"]
    assert any("날짜" in e for e in v["errors"])
