"""tests.test_intent_tag — user_intent 태그 멱등 부착 회귀.

2026-06-11 사고: G2/G3/G4 가 "(분석 방향: ...)" 등을 중복 체크 없이 덧붙여
gate resume 마다 누적 (실측 6중첩) → S4 가설 슬라이드 오염.
"""

from __future__ import annotations

from agents.gates._intent import append_intent_tag


def test_fresh_append():
    assert append_intent_tag("생존여부", "분석 방향", "성별 분석") == "생존여부 (분석 방향: 성별 분석)"


def test_empty_base():
    assert append_intent_tag("", "분석 방향", "성별 분석") == "분석 방향: 성별 분석"
    assert append_intent_tag(None, "주제", "타이타닉") == "주제: 타이타닉"


def test_idempotent_same_value():
    once = append_intent_tag("생존여부", "분석 방향", "성별 분석")
    twice = append_intent_tag(once, "분석 방향", "성별 분석")
    assert twice == once


def test_reselection_replaces_value():
    once = append_intent_tag("생존여부", "분석 방향", "성별 분석")
    changed = append_intent_tag(once, "분석 방향", "클래스별 분석")
    assert changed == "생존여부 (분석 방향: 클래스별 분석)"
    assert "성별 분석" not in changed


def test_cleans_accumulated_contamination():
    dirty = "생존여부 (분석 방향: A) (주제: T) (분석 방향: B)"
    cleaned = append_intent_tag(dirty, "분석 방향", "C")
    assert cleaned.count("분석 방향") == 1
    assert "(주제: T)" in cleaned
    assert cleaned.endswith("(분석 방향: C)")


def test_different_tags_coexist():
    s = append_intent_tag("의도", "주제", "타이타닉")
    s = append_intent_tag(s, "분석 방향", "성별")
    s = append_intent_tag(s, "방법론", "분류 앙상블")
    s = append_intent_tag(s, "모델 전략", "부스팅")
    assert s == "의도 (주제: 타이타닉) (분석 방향: 성별) (방법론: 분류 앙상블) (모델 전략: 부스팅)"
    # 한 바퀴 더 (resume 시뮬) — 재부착 시 순서는 바뀔 수 있으나 길이·태그 수 불변
    s2 = append_intent_tag(s, "주제", "타이타닉")
    s2 = append_intent_tag(s2, "분석 방향", "성별")
    assert len(s2) == len(s)
    for tag in ("주제", "분석 방향", "방법론", "모델 전략"):
        assert s2.count(f"({tag}:") == 1
