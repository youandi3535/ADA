"""Day 8 — InsightAgent 가드레일 (수치 인용 + 한국어 강제 + 3~5문장 + top 피처).

DoD:
    - insight_must_cite 가 4 위반 모두 잡음
    - InsightAgent 가 가드 위반 시 retry 1회 후 fallback
    - 가드 통과 응답은 그대로 사용
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from ada.core.state import PipelineState


# ----- 1) insight_must_cite 단위 ----------------------------------------------
def test_guard_detects_english_only():
    from ada.security.guardrails import insight_must_cite

    r = insight_must_cite("This model has 0.83 f1 score.", top_features=["age"])
    assert r["passed"] is False
    assert "한국어 미사용" in r["violations"]


def test_guard_detects_missing_number():
    from ada.security.guardrails import insight_must_cite

    r = insight_must_cite("이 모델은 잘 작동합니다. 신중한 분석이 필요합니다. 추가 검증을 권장합니다.")
    assert r["passed"] is False
    assert any("수치" in v for v in r["violations"])


def test_guard_detects_missing_features():
    from ada.security.guardrails import insight_must_cite

    r = insight_must_cite(
        "이 모델의 F1 점수는 0.83 입니다. 정확도는 85% 입니다. 추가 분석이 필요합니다.",
        top_features=["age", "income"],
    )
    assert r["passed"] is False
    assert any("피처" in v for v in r["violations"])


def test_guard_detects_sentence_count():
    from ada.security.guardrails import insight_must_cite

    # 2 문장만 — 미달 (소수점 회피 위해 정수 사용)
    r = insight_must_cite("F1 점수 83% 입니다! age 가 중요합니다?", top_features=["age"])
    assert r["passed"] is False
    assert any("문장 부족" in v for v in r["violations"])

    # 7 문장 — 초과
    text = "! ".join([f"문장 {i} 와 12% 결과" for i in range(7)]) + "! age 중요!"
    r = insight_must_cite(text, top_features=["age"])
    assert r["passed"] is False
    assert any("문장 초과" in v for v in r["violations"])


def test_guard_passes_good_text():
    from ada.security.guardrails import insight_must_cite

    text = (
        "이 모델의 F1 점수는 0.83 입니다. age 피처가 결과의 32% 를 설명합니다. "
        "추가로 income 도 12% 기여했습니다. 다음 단계로 SHAP 분석을 권장합니다."
    )
    r = insight_must_cite(text, top_features=["age", "income"])
    assert r["passed"], r


# ----- 2) InsightAgent — 가드 통과 응답은 그대로 통과 -----------------------------
def test_insight_agent_uses_passing_response(monkeypatch):
    from agents.insight import InsightAgent

    good = "F1 점수 0.83 으로 양호합니다. age 피처가 32% 기여. 추가 검증 권장. 다음 분기 재학습 예정."

    async def fake_llm(self, **k):
        return good

    monkeypatch.setattr(InsightAgent, "_call_llm", fake_llm)

    state = PipelineState(
        job_id="00000000-0000-0000-0000-000000000001",
        file_id="f.csv",
        category="tabular_ml",
        target_column="y",
        eval_result={"feature_importance": {"age": 0.32, "income": 0.12, "gender": 0.05}},
        best_model={"model_name": "RandomForest", "metrics": {"val_f1": 0.83}},
    )
    out = asyncio.run(InsightAgent()(state))
    assert "0.83" in (out.insights or "")
    assert "age" in (out.insights or "")


# ----- 3) InsightAgent — 가드 실패 시 retry 후 통과 ------------------------------
def test_insight_agent_retries_on_guard_fail(monkeypatch):
    from agents.insight import InsightAgent

    calls: list[str] = []
    bad = "This model is good"
    good = "F1 점수 0.83 우수. age 피처 핵심. 다음 분기 재학습. 추가 SHAP 분석 권장."

    async def fake_llm(self, **k):
        calls.append(k.get("system_prompt", "")[:30])
        return bad if len(calls) == 1 else good

    monkeypatch.setattr(InsightAgent, "_call_llm", fake_llm)

    state = PipelineState(
        job_id="00000000-0000-0000-0000-000000000001",
        file_id="f.csv",
        category="tabular_ml",
        target_column="y",
        eval_result={"feature_importance": {"age": 0.32}},
        best_model={"model_name": "X", "metrics": {"val_f1": 0.83}},
    )
    out = asyncio.run(InsightAgent()(state))
    assert len(calls) == 2  # retry 1회
    assert "0.83" in (out.insights or "")
    assert "age" in (out.insights or "")


# ----- 4) InsightAgent — retry 도 실패하면 fallback ------------------------------
def test_insight_agent_uses_fallback_after_retry(monkeypatch):
    from agents.insight import InsightAgent

    async def fake_llm(self, **k):
        return "completely english nothing relevant"

    monkeypatch.setattr(InsightAgent, "_call_llm", fake_llm)

    # tabular handler 의 fallback 이 사용됨
    state = PipelineState(
        job_id="00000000-0000-0000-0000-000000000001",
        file_id="f.csv",
        category="tabular_ml",
        target_column="y",
        eval_result={"feature_importance": {"age": 0.32}},
        best_model={"model_name": "X", "metrics": {"val_f1": 0.83}},
    )
    out = asyncio.run(InsightAgent()(state))
    # fallback 텍스트 또는 default → 영문 그대로는 들어가지 않아야 함
    assert out.insights and out.insights != "completely english nothing relevant"


# ----- 5) Day 4 PII reattach 가 insight 결과에도 적용 ---------------------------
def test_insight_reattaches_pii(monkeypatch):
    from agents.insight import InsightAgent

    async def fake_llm(self, **k):
        # 의도적으로 토큰을 그대로 반환
        return "F1 점수 0.83. age 피처가 32% 기여. <PII:email:deadbeef> 에게 보고 권장. 다음 단계는 SHAP."

    monkeypatch.setattr(InsightAgent, "_call_llm", fake_llm)

    state = PipelineState(
        job_id="00000000-0000-0000-0000-000000000001",
        file_id="f.csv",
        category="tabular_ml",
        target_column="y",
        eval_result={"feature_importance": {"age": 0.32}},
        best_model={"model_name": "X", "metrics": {"val_f1": 0.83}},
        category_extras={"_pii": {"mapping": {"<PII:email:deadbeef>": "x@y.com"}, "redaction": "***"}},
    )
    out = asyncio.run(InsightAgent()(state))
    assert "<PII:" not in (out.insights or "")
    assert "x@y.com" not in (out.insights or "")
    assert "***" in (out.insights or "")
