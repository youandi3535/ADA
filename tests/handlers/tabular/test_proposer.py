"""jh Day 4 — test_proposer.py: G1/G2 카드 카탈로그 테스트 (32 unit + 5 integration)."""

from __future__ import annotations

import pytest

# ── helpers ───────────────────────────────────────────────────────────────────

REQUIRED_G1_KEYS = {"id", "gate", "title", "rationale", "score", "triggered"}
REQUIRED_G2_KEYS = REQUIRED_G1_KEYS | {"is_recommendation"}


def _wrap_hints(state, hints: dict):
    """proposer_hints 주입 wrapper (PipelineState에 해당 필드 없음)."""

    class _W:
        def __getattr__(self, name):
            return getattr(state, name)

        @property
        def proposer_hints(self):
            return hints

    return _W()


def _small_state(tab_state, *, rows=120, cv=None):
    """tab_state 기반 data_profile + optional eda_baseline 생성."""
    extras: dict = {}
    if cv is not None:
        extras = {"tabular": {"eda_baseline": {"cv_score": cv, "metric": "f1_macro"}}}
    profile = {"rows": rows, "columns": 5, "class_distribution": {0: rows // 2, 1: rows // 2}}
    return tab_state.with_update(data_profile=profile, category_extras=extras)


# ── TestG1Unit ────────────────────────────────────────────────────────────────


class TestG1Unit:
    def test_returns_exactly_3_cards(self, tab_state):
        from agents.handlers.tabular.proposer import g1

        assert len(g1(tab_state)) == 3

    def test_standard_keys_present(self, tab_state):
        from agents.handlers.tabular.proposer import g1

        for card in g1(tab_state):
            assert REQUIRED_G1_KEYS.issubset(card.keys()), f"card {card['id']} missing keys"

    def test_sorted_score_descending(self, tab_state):
        from agents.handlers.tabular.proposer import g1

        scores = [c["score"] for c in g1(tab_state)]
        assert scores == sorted(scores, reverse=True)

    def test_predict_clf_triggered(self, tab_state):
        from agents.handlers.tabular.proposer import g1

        cards = g1(tab_state)
        clf = next((c for c in cards if c["id"] == "g1_predict_classification"), None)
        assert clf is not None, "g1_predict_classification not in top-3"
        assert clf["triggered"] is True

    def test_predict_clf_disabled_without_target(self, tab_state):
        from agents.handlers.tabular.proposer import CARD_REGISTRY

        no_target = tab_state.with_update(target_column=None)
        spec = CARD_REGISTRY["g1_predict_classification"]
        import pandas as pd

        df = pd.DataFrame({"A": range(10), "B": range(10)})
        assert spec.trigger_fn(no_target, df, {}) is False

    def test_predict_regression_triggered(self, tab_state_regression):
        from agents.handlers.tabular.proposer import CARD_REGISTRY

        spec = CARD_REGISTRY["g1_predict_regression"]
        assert spec.trigger_fn(tab_state_regression, None, {}) is True

    def test_segment_triggered_with_numeric_df(self, tab_state, tab_df):
        from agents.handlers.tabular.proposer import CARD_REGISTRY

        spec = CARD_REGISTRY["g1_segment"]
        assert spec.trigger_fn(tab_state, tab_df, {}) is True

    def test_segment_score_high_without_target(self, tab_df_unsupervised):
        from ada.core.state import PipelineState
        from agents.handlers.tabular.proposer import CARD_REGISTRY

        no_tgt = PipelineState(
            job_id="00000000-0000-0000-0000-000000000t01",
            file_id="uploads/test/titanic.csv",
            category="tabular_ml",
            target_column=None,
            user_intent="데이터 세그먼트 파악",
        )
        spec = CARD_REGISTRY["g1_segment"]
        score = spec.score_fn(no_tgt, tab_df_unsupervised, {}, spec.base_score)
        assert score >= 0.8

    def test_importance_triggered_sufficient_rows(self, tab_state):
        import pandas as pd

        from agents.handlers.tabular.proposer import CARD_REGISTRY

        state = tab_state.with_update(data_profile={"rows": 60, "columns": 2})
        df = pd.DataFrame({"A": range(60), "Survived": [0, 1] * 30})
        spec = CARD_REGISTRY["g1_importance"]
        assert spec.trigger_fn(state, df, {}) is True

    def test_importance_not_triggered_tiny_rows(self, tab_state):
        import pandas as pd

        from agents.handlers.tabular.proposer import CARD_REGISTRY

        state = tab_state.with_update(data_profile={"rows": 10, "columns": 2})
        tiny_df = pd.DataFrame({"A": range(10), "Survived": [0, 1] * 5})
        spec = CARD_REGISTRY["g1_importance"]
        assert spec.trigger_fn(state, tiny_df, {}) is False

    def test_hybrid_triggered_with_both_keywords(self, tab_state):
        from agents.handlers.tabular.proposer import CARD_REGISTRY

        state = tab_state.with_update(
            user_intent="매출 예측 및 결과 해석",
            data_profile={"rows": 2000, "columns": 5},
        )
        spec = CARD_REGISTRY["g1_hybrid"]
        assert spec.trigger_fn(state, None, {}) is True

    def test_anomaly_handoff_triggered_high_outlier(self, tab_state):
        from agents.handlers.tabular.proposer import CARD_REGISTRY

        state = tab_state.with_update(data_profile={"rows": 120, "columns": 4, "outlier_ratio": 0.15})
        spec = CARD_REGISTRY["g1_anomaly_handoff"]
        assert spec.trigger_fn(state, None, {}) is True

    def test_timeseries_handoff_triggered(self, tab_state):
        from agents.handlers.tabular.proposer import CARD_REGISTRY

        state = tab_state.with_update(
            data_profile={
                "rows": 120,
                "columns": 4,
                "datetime_columns": ["date"],
                "max_acf_lag1": 0.85,
            }
        )
        spec = CARD_REGISTRY["g1_timeseries_handoff"]
        assert spec.trigger_fn(state, None, {}) is True

    def test_survival_triggered_by_column_names(self, tab_state):
        import pandas as pd

        from agents.handlers.tabular.proposer import CARD_REGISTRY

        surv_df = pd.DataFrame(
            {
                "duration": range(60),
                "event": [0, 1] * 30,
                "age": range(60),
                "Survived": [0, 1] * 30,
            }
        )
        spec = CARD_REGISTRY["g1_survival_analysis"]
        assert spec.trigger_fn(tab_state, surv_df, {}) is True

    def test_multi_target_triggered(self, tab_state):
        from agents.handlers.tabular.proposer import CARD_REGISTRY

        class _MultiState:
            def __getattr__(self, name):
                return getattr(tab_state, name)

            @property
            def target_columns(self):
                return ["Survived", "Fare"]

        spec = CARD_REGISTRY["g1_multi_target"]
        assert spec.trigger_fn(_MultiState(), None, {}) is True

    def test_keyword_predict_boosts_score(self, tab_state):
        from agents.handlers.tabular.proposer import g1

        state_with = tab_state.with_update(user_intent="매출 예측 분류")
        state_without = tab_state.with_update(user_intent="단순 분석")
        cards_with = g1(state_with)
        cards_without = g1(state_without)
        clf_with = next((c for c in cards_with if c["id"] == "g1_predict_classification"), None)
        clf_without = next((c for c in cards_without if c["id"] == "g1_predict_classification"), None)
        if clf_with and clf_without and clf_with["triggered"] and clf_without["triggered"]:
            assert clf_with["score"] > clf_without["score"]

    def test_rationale_korean_formal_tone(self, tab_state):
        from agents.handlers.tabular.proposer import g1

        formal_endings = {"됩니다", "드립니다", "예상됩니다", "진행됩니다", "가능합니다", "사용됩니다"}
        for card in g1(tab_state):
            if card["triggered"]:
                rat = card["rationale"]
                assert any(tok in rat for tok in formal_endings), (
                    f"Card {card['id']} rationale missing formal tone: {rat!r}"
                )
                assert "할 수 있어요" not in rat

    def test_g1_no_state_mutation(self, tab_state):
        from agents.handlers.tabular.proposer import g1

        profile_id_before = id(tab_state.data_profile)
        g1(tab_state)
        assert id(tab_state.data_profile) == profile_id_before


# ── TestG2Unit ────────────────────────────────────────────────────────────────


class TestG2Unit:
    def test_exactly_one_recommendation(self, tab_state):
        from agents.handlers.tabular.proposer import g2

        cards = g2(tab_state)
        recs = [c for c in cards if c["is_recommendation"]]
        assert len(recs) == 1

    def test_dod_large_includes_dl(self, tab_state_large):
        """★DoD★ n_rows≥5000 + classes≤10 → dl 카드 반드시 포함."""
        from agents.handlers.tabular.proposer import g2

        cards = g2(tab_state_large)
        assert any(c["id"].startswith("g2_dl") for c in cards), "DoD 위반: 5000행+5클래스에 DL 카드 없음"

    def test_small_data_no_dl(self, tab_state):
        from agents.handlers.tabular.proposer import g2

        cards = g2(tab_state)
        assert not any(c["id"].startswith("g2_dl") for c in cards)

    def test_classes_over_10_no_dl(self, tab_state):
        from agents.handlers.tabular.proposer import g2

        state = tab_state.with_update(
            data_profile={
                "rows": 20_000,
                "columns": 10,
                "class_distribution": {i: 1000 for i in range(20)},
            }
        )
        cards = g2(state)
        assert not any(c["id"].startswith("g2_dl") for c in cards)

    def test_big_simple_recommends_ml_standard(self, tab_state_huge):
        """rows=1M, baseline_cv=0.95 → weight_score≈0.37 → g2_ml_standard."""
        from agents.handlers.tabular.proposer import g2

        cards = g2(tab_state_huge)
        rec = next(c for c in cards if c["is_recommendation"])
        assert rec["id"] == "g2_ml_standard"

    def test_small_complex_recommends_dl_light(self, tab_state_complex_medium):
        """rows=10000, cv=0.55, imbalance → weight_score≈0.795 → g2_dl_light."""
        from agents.handlers.tabular.proposer import g2

        cards = g2(tab_state_complex_medium)
        rec = next(c for c in cards if c["is_recommendation"])
        assert rec["id"] == "g2_dl_light"

    def test_weight_score_4_scenarios(self, tab_state):
        """§3-6 시나리오 4가지 weight_score → 추천 카드 검증."""
        from agents.handlers.tabular.proposer import g2

        def _scenario_state(rows, n_cls, cv, top_feat=None, nonlin=None, entropy=1.0):
            cd = {i: rows // n_cls for i in range(n_cls)} if n_cls else {}
            bl: dict = {"cv_score": cv, "metric": "f1_macro"}
            if top_feat is not None:
                bl["top_feature_concentration"] = top_feat
            if nonlin is not None:
                bl["nonlinearity_estimate"] = nonlin
            return tab_state.with_update(
                data_profile={
                    "rows": rows,
                    "columns": 10,
                    "class_distribution": cd,
                    "class_entropy_ratio": entropy,
                },
                category_extras={"tabular": {"eda_baseline": bl}},
            )

        # S1: 100만행 binary, cv=0.95 → ~0.37 → ml_standard
        r1 = next(c for c in g2(_scenario_state(1_000_000, 2, 0.95)) if c["is_recommendation"])
        assert r1["id"] == "g2_ml_standard"

        # S2: 1만행 5클래스, cv=0.55, imbalance, top_feat<0.40, nonlin>0.15 → ~0.755 → dl_light
        r2 = next(c for c in g2(_scenario_state(10_000, 5, 0.55, 0.30, 0.20, entropy=0.25)) if c["is_recommendation"])
        assert r2["id"] == "g2_dl_light"

        # S3: 1,000행 binary, cv=0.82, 깨끗 → ~0.32 → ml_standard
        r3 = next(c for c in g2(_scenario_state(1_000, 2, 0.82)) if c["is_recommendation"])
        assert r3["id"] == "g2_ml_standard"

        # S4: 50만행 binary, cv=0.92 → ~0.34 → ml_standard
        r4 = next(c for c in g2(_scenario_state(500_000, 2, 0.92)) if c["is_recommendation"])
        assert r4["id"] == "g2_ml_standard"

    def test_baseline_absent_complexity_is_mid(self):
        """eda_baseline 없을 때 complexity_signal 기본값 0.5."""
        from agents.handlers.tabular.proposer import _complexity_signal

        assert _complexity_signal(None, None, None) == 0.5

    def test_g1_segment_choice_boosts_ml_light(self, tab_state):
        """g1_segment 선택 → g2_ml_light 점수 +0.15 보정."""
        from agents.handlers.tabular.proposer import g2

        # 1000행 cv=0.82 → rec=ml_standard, alt=[ml_light, ml_heavy]
        state = tab_state.with_update(
            data_profile={"rows": 1000, "columns": 5, "class_distribution": {0: 500, 1: 500}},
            category_extras={"tabular": {"eda_baseline": {"cv_score": 0.82, "metric": "f1_macro"}}},
            gate_responses={"g1": "g1_segment"},
        )
        cards = g2(state)
        ml_light = next((c for c in cards if c["id"] == "g2_ml_light"), None)
        ml_heavy = next((c for c in cards if c["id"] == "g2_ml_heavy"), None)
        if ml_light and ml_heavy:
            assert ml_light["score"] >= ml_heavy["score"]

    def test_hint_disable_dl(self, tab_state_large):
        from agents.handlers.tabular.proposer import g2

        state = _wrap_hints(tab_state_large, {"disable_dl": True})
        cards = g2(state)
        assert not any(c["id"].startswith("g2_dl") for c in cards)

    def test_hint_prefer_speed(self, tab_state_large):
        from agents.handlers.tabular.proposer import g2

        state = _wrap_hints(tab_state_large, {"prefer_speed": True})
        rec = next(c for c in g2(state) if c["is_recommendation"])
        assert rec["id"] == "g2_ml_light"

    def test_hint_force_card(self, tab_state):
        from agents.handlers.tabular.proposer import g2

        state = _wrap_hints(tab_state, {"force_card": ["g2_ml_heavy"]})
        rec = next(c for c in g2(state) if c["is_recommendation"])
        assert rec["id"] == "g2_ml_heavy"

    def test_pii_content_inside_token_not_matched(self, tab_state):
        """PII 토큰 내부 키워드는 매칭 제외."""
        from agents.handlers.tabular.proposer import g1

        # "예측" 이 PII 토큰 안에만 있음 → keyword boost 없음
        state_pii = tab_state.with_update(user_intent="<PII:keyword:예측>")
        # "예측" 이 평문에 있음 → keyword boost 있음
        state_plain = tab_state.with_update(user_intent="예측")

        cards_pii = g1(state_pii)
        cards_plain = g1(state_plain)
        clf_pii = next((c for c in cards_pii if c["id"] == "g1_predict_classification"), None)
        clf_plain = next((c for c in cards_plain if c["id"] == "g1_predict_classification"), None)
        if clf_pii and clf_plain and clf_pii["triggered"] and clf_plain["triggered"]:
            assert clf_plain["score"] > clf_pii["score"]

    def test_rationale_no_pii_decoded(self, tab_state):
        """rationale에 PII 디코딩 값 미포함 — proposer는 decode 하지 않음."""
        from agents.handlers.tabular.proposer import g2

        state = tab_state.with_update(
            data_profile={"rows": 120, "columns": 4},
            user_intent="<PII:name:john_doe>의 생존 확인",
        )
        for card in g2(state):
            assert "john_doe" not in card["rationale"]
            assert card["rationale"]  # 비어 있지 않아야 함


# ── TestIntegration ───────────────────────────────────────────────────────────


class TestIntegration:
    def test_small_data_full_flow(self, tab_state, tab_df):
        """120행 — g1 3개 + g2 DL 없음."""
        from agents.handlers.tabular.proposer import g1, g2

        g1_cards = g1(tab_state, tab_df)
        assert len(g1_cards) == 3
        assert all(REQUIRED_G1_KEYS.issubset(c.keys()) for c in g1_cards)

        g2_cards = g2(tab_state, tab_df)
        assert 1 <= len(g2_cards) <= 3
        assert sum(1 for c in g2_cards if c["is_recommendation"]) == 1
        assert not any(c["id"].startswith("g2_dl") for c in g2_cards)

    def test_large_simple_scenario(self, tab_state_huge):
        """1M행 cv=0.95 — g1 3개 + g2 ml_standard 추천."""
        from agents.handlers.tabular.proposer import g1, g2

        assert len(g1(tab_state_huge)) == 3
        rec = next(c for c in g2(tab_state_huge) if c["is_recommendation"])
        assert rec["id"] == "g2_ml_standard"

    def test_complex_medium_scenario(self, tab_state_complex_medium):
        """10000행 cv=0.55 복잡 — g1 3개 + g2 dl_light 추천."""
        from agents.handlers.tabular.proposer import g1, g2

        assert len(g1(tab_state_complex_medium)) == 3
        rec = next(c for c in g2(tab_state_complex_medium) if c["is_recommendation"])
        assert rec["id"] == "g2_dl_light"

    def test_g1_segment_to_g2_ml_light_boost(self, tab_state):
        """g1=segment 선택 → g2 ml_light 점수 보정 확인."""
        from agents.handlers.tabular.proposer import g2

        state = tab_state.with_update(
            data_profile={"rows": 1000, "columns": 5, "class_distribution": {0: 500, 1: 500}},
            category_extras={"tabular": {"eda_baseline": {"cv_score": 0.82, "metric": "f1_macro"}}},
            gate_responses={"g1": "g1_segment"},
        )
        cards = g2(state)
        ml_light = next((c for c in cards if c["id"] == "g2_ml_light"), None)
        if ml_light:
            assert ml_light["score"] >= 0.75  # 0.60 + 0.15 boost

    def test_dod_large_dl_present(self, tab_state_large):
        """★DoD★ 10000행+5클래스 — g1+g2 완전 흐름, DL 반드시 포함."""
        from agents.handlers.tabular.proposer import g1, g2

        assert len(g1(tab_state_large)) == 3
        g2_cards = g2(tab_state_large)
        assert any(c["id"].startswith("g2_dl") for c in g2_cards), "DoD 위반: 10000행+5클래스에 DL 카드 없음"
        assert sum(1 for c in g2_cards if c["is_recommendation"]) == 1
