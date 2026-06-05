"""tests/handlers/timeseries/test_insight — cs-day8 v3 디벨롭 검증.

검증 카테고리:
  회귀 가드 (5): 시그니처 (SYSTEM_PROMPT / prompt_payload / fallback / generate) + DoD (한국어 + 수치 2+ + 응급 안전망)
  H1 slope 버그 수정 (1): slope_per_obs 인용 정상 작동
  H2 0단계 메타 (2): proposer.g1 직접 호출 + chosen_recipe 폴백
  H3 누수 한계 안내 (1): leakage_signals 있을 때 한계 인정 문장
  H4 fold 분산 인용 (1): fold_diag.available 시 fold N개 인용
  H5 증상 + 롤백 (2): symptom ≠ normal 시 권장 조치 / symptom=C 누수 시 정직한 보고
  H6 도메인 가이드 (3): is_multiplicative / changepoints≥3 / heteroscedastic
  H7 task_kind_hint (1): 분류형 안내 등장
  엣지 (4): 빈 state / eval_result None / proposer 실패 / 모든 None
"""

from __future__ import annotations

import pytest


# ════════════════════════════════════════════════════════════════
# fixture
# ════════════════════════════════════════════════════════════════
class _StubState:
    """insight 가 getattr 로 다양한 키 추출 — 가벼운 stub."""

    def __init__(self, **kwargs):
        self.job_id = kwargs.get("job_id", "00000000-0000-0000-0000-000000000001")
        self.file_id = kwargs.get("file_id", "uploads/x.csv")
        self.category = "timeseries"
        self.target_column = kwargs.get("target_column", "y")
        self.user_intent = kwargs.get("user_intent", "예측")
        self.best_model = kwargs.get("best_model")
        self.data_profile = kwargs.get("data_profile")
        self.eda_summary = kwargs.get("eda_summary")
        self.eval_result = kwargs.get("eval_result")
        if "chosen_recipe" in kwargs:
            self.chosen_recipe = kwargs["chosen_recipe"]
        if "category_extras" in kwargs:
            self.category_extras = kwargs["category_extras"]


def _full_state(**overrides):
    """전형적 풀스택 state (AirPassengers-like 시나리오)."""
    base = {
        "best_model": {
            "model_name": "SARIMA",
            "metrics": {
                "rmse_improvement_vs_naive": 0.44,
                "MASE": 0.78,
                "sMAPE": 12.0,
                "pi_coverage": 0.93,
            },
        },
        "data_profile": {
            "freq": "MS",
            "trend": {"direction": "increasing", "slope_per_obs": 0.05, "has_trend": True},
            "seasonality": {"has_seasonality": True, "period": 12},
            "stationarity": {"is_stationary": False, "consensus": "non_stationary"},
        },
        "eda_summary": {
            "seasonal_period": 12,
            "stationary": False,
            "is_multiplicative": True,
            "changepoints": 1,
            "heteroscedastic": False,
        },
        "eval_result": {
            "passed": True,
            "rationale": "통과",
            "threshold_violations": [],
            "metrics": {},
            "fold_diagnostics": {"available": True, "n_folds": 3, "mean": 0.42, "stability": "stable"},
            "leakage_suspect_signals": [],
            "symptom_classification": {"symptom": "normal", "label": "정상", "rollback_priority": []},
            "task_kind_hint": None,
        },
    }
    base.update(overrides)
    return _StubState(**base)


# ════════════════════════════════════════════════════════════════
# 회귀 가드 — 시그니처 + DoD
# ════════════════════════════════════════════════════════════════
class TestRegression:
    def test_module_signature_unchanged(self):
        """SYSTEM_PROMPT / prompt_payload / fallback / generate 네 심볼 노출."""
        from agents.handlers.timeseries import insight as mod

        assert isinstance(mod.SYSTEM_PROMPT, str)
        assert callable(mod.prompt_payload)
        assert callable(mod.fallback)
        assert callable(mod.generate)

    def test_prompt_payload_returns_legacy_11_keys(self):
        """기존 11키 모두 보존 (cs-day8 v2 호환)."""
        from agents.handlers.timeseries.insight import prompt_payload

        p = prompt_payload(_full_state())
        for k in (
            "category",
            "user_intent",
            "best_model",
            "stationarity",
            "trend",
            "seasonality",
            "eval_result",
            "horizon_text",
            "horizon_n",
            "unit_ko",
            "system_prompt",
        ):
            assert k in p, f"기존 키 {k} 누락 — 회귀"

    def test_prompt_payload_new_keys_added(self):
        """신규 키 zero_step + eval_diagnostics 추가 (LLM 컨텍스트 풍부)."""
        from agents.handlers.timeseries.insight import prompt_payload

        p = prompt_payload(_full_state())
        assert "zero_step" in p
        assert "eval_diagnostics" in p
        assert isinstance(p["zero_step"], dict)
        assert isinstance(p["eval_diagnostics"], dict)

    def test_fallback_returns_korean_string(self):
        """fallback → str (한국어 1자+)."""
        from agents.handlers.timeseries.insight import fallback

        out = fallback(_full_state())
        assert isinstance(out, str)
        assert len(out) > 10
        # 한국어 음절 1자+ (가드 d 호환)
        assert any("가" <= c <= "힣" for c in out)

    def test_fallback_emergency_safety_on_exception(self):
        """fallback 자체 실패 시 응급 텍스트 반환 (no exception)."""
        from agents.handlers.timeseries.insight import fallback

        # 모든 getattr 실패 강제 — None 객체 전달
        class _Broken:
            def __getattr__(self, name):
                raise RuntimeError("강제 실패")

        out = fallback(_Broken())
        assert out == "이번 분석 결과는 추가 검토가 필요합니다."


# ════════════════════════════════════════════════════════════════
# H1 — slope_per_obs 인용 정상 작동 (버그 수정)
# ════════════════════════════════════════════════════════════════
class TestSlopeBugFix:
    def test_slope_per_obs_cited_in_fallback(self):
        """profiler 정식 키 slope_per_obs 사용 시 인용 등장."""
        from agents.handlers.timeseries.insight import fallback

        st = _full_state(
            data_profile={
                "freq": "D",
                "trend": {"direction": "increasing", "slope_per_obs": 0.025, "has_trend": True},
                "seasonality": {"has_seasonality": False},
                "stationarity": {"is_stationary": True},
            }
        )
        out = fallback(st)
        # +2.5% 같은 변화율 인용 등장
        assert "%" in out

    def test_legacy_slope_key_fallback(self):
        """legacy 'slope' 키도 fallback 으로 인식 (호환)."""
        from agents.handlers.timeseries.insight import fallback

        st = _full_state(
            data_profile={
                "freq": "D",
                "trend": {"direction": "increasing", "slope": 0.03},
                "seasonality": {"has_seasonality": False},
            }
        )
        out = fallback(st)
        assert "%" in out


# ════════════════════════════════════════════════════════════════
# H2 — 0단계 메타 (variate/forecast_kind)
# ════════════════════════════════════════════════════════════════
class TestZeroStepMeta:
    def test_chosen_recipe_meta_used_when_present(self):
        """chosen_recipe.meta 있을 때 1순위 사용."""
        from agents.handlers.timeseries.insight import fallback

        st = _full_state(
            chosen_recipe={"title": "단기 예측", "meta": {"variate": "multivariate", "forecast_kind": "interval"}}
        )
        out = fallback(st)
        # "다변량 구간 예측" 또는 그 일부 등장
        assert "다변량" in out or "구간 예측" in out

    def test_proposer_g1_fallback_when_no_chosen_recipe(self):
        """chosen_recipe 없으면 proposer.g1 호출 → meta 추출 (호환성 보강)."""
        from agents.handlers.timeseries.insight import fallback

        st = _full_state()
        # chosen_recipe 없음 — proposer.g1 이 호출돼야 함
        out = fallback(st)
        # 어떤 형식이든 0단계 일부 키워드 (단변량/다변량/예측) 등장
        assert "예측" in out


# ════════════════════════════════════════════════════════════════
# H3·H5 — 누수 한계 + 증상 + 롤백 우선순위
# ════════════════════════════════════════════════════════════════
class TestLeakageAndSymptom:
    def test_leakage_signals_trigger_honest_warning(self):
        """누수 신호 있으면 한계 인정 문장 등장 (낙관 톤 X)."""
        from agents.handlers.timeseries.insight import fallback

        st = _full_state(
            eval_result={
                "leakage_suspect_signals": [
                    {"kind": "too_good_vs_naive", "value": 0.98, "threshold": 0.95, "hint": "..."},
                ],
                "symptom_classification": {
                    "symptom": "C",
                    "label": "누수 의심",
                    "rollback_priority": ["3단계 horizon-aware lag"],
                },
            }
        )
        out = fallback(st)
        assert "누수" in out or "검증 신호" in out
        assert "운영" in out or "점검" in out

    def test_symptom_E_triggers_rollback_priority(self):
        """증상 E (naïve 못 이김) → 권장 조치 (롤백 top1) 등장."""
        from agents.handlers.timeseries.insight import fallback

        st = _full_state(
            eval_result={
                "leakage_suspect_signals": [],
                "symptom_classification": {
                    "symptom": "E",
                    "label": "naïve 기준선 못 이김",
                    "rollback_priority": ["3단계 차분/변화율 타겟", "3단계 외생변수 강화"],
                },
            }
        )
        out = fallback(st)
        assert "증상" in out or "E" in out
        assert "차분" in out or "타겟" in out or "권장 조치" in out


# ════════════════════════════════════════════════════════════════
# H4 — fold 분산 인용
# ════════════════════════════════════════════════════════════════
class TestFoldDiagnostics:
    def test_fold_diag_cited_when_available(self):
        """fold_diagnostics.available=True 시 fold 개수·평균·안정성 인용 (5문장 가드 통과 시).

        P10 보강 — 5문장 초과 시 fold 문장이 우선 drop 됨. 따라서 계절성·도메인
        가이드가 없는 단순 시나리오로 5문장 이내 보장하고 fold 인용 검증.
        """
        from agents.handlers.timeseries.insight import fallback

        # 단순 시나리오: 계절성 False + 도메인 가이드 없음 + 증상 normal → 4문장 보장
        st = _StubState(
            best_model={"model_name": "ARIMA", "metrics": {"rmse_improvement_vs_naive": 0.3, "MASE": 0.7}},
            data_profile={
                "freq": "D",
                "trend": {"direction": "increasing", "slope_per_obs": 0.02},
                "seasonality": {"has_seasonality": False},
            },
            eda_summary={"is_multiplicative": False, "changepoints": 0, "heteroscedastic": False},
            eval_result={
                "fold_diagnostics": {
                    "available": True,
                    "n_folds": 5,
                    "mean": 0.38,
                    "stability": "stable",
                },
                "leakage_suspect_signals": [],
                "symptom_classification": {"symptom": "normal", "rollback_priority": []},
            },
        )
        out = fallback(st)
        # fold 또는 walk-forward 키워드 + 숫자 (P10: 5문장 이내 시나리오)
        assert ("fold" in out or "walk-forward" in out) and "5" in out


# ════════════════════════════════════════════════════════════════
# H6 — 도메인 가이드 (승법/changepoint/이분산)
# ════════════════════════════════════════════════════════════════
class TestDomainHints:
    def test_multiplicative_triggers_log_hint(self):
        """is_multiplicative=True → 로그 변환 검토 가이드 등장."""
        from agents.handlers.timeseries.insight import fallback

        st = _full_state(eda_summary={"seasonal_period": 12, "is_multiplicative": True})
        out = fallback(st)
        assert "로그" in out or "승법" in out

    def test_changepoints_triggers_event_dummy_hint(self):
        """changepoints ≥ 3 → 이벤트 더미 권장."""
        from agents.handlers.timeseries.insight import fallback

        st = _full_state(eda_summary={"seasonal_period": 12, "changepoints": 5})
        out = fallback(st)
        assert "이벤트" in out or "레짐" in out or "5" in out

    def test_heteroscedastic_triggers_adaptive_pi_hint(self):
        """heteroscedastic=True → 시간 적응형 PI 검토."""
        from agents.handlers.timeseries.insight import fallback

        st = _full_state(eda_summary={"seasonal_period": 12, "heteroscedastic": True})
        out = fallback(st)
        assert "이분산" in out or "PI" in out or "적응형" in out


# ════════════════════════════════════════════════════════════════
# H7 — task_kind_hint (분류형 안내)
# ════════════════════════════════════════════════════════════════
class TestTaskKindHint:
    def test_task_kind_hint_appears_in_fallback(self):
        """eval_result.task_kind_hint 가 있으면 fallback 문장에 등장."""
        from agents.handlers.timeseries.insight import fallback

        st = _full_state(
            eval_result={
                "leakage_suspect_signals": [],
                "symptom_classification": {"symptom": "normal", "rollback_priority": []},
                "task_kind_hint": "결정 임계 검토 필요",
            }
        )
        out = fallback(st)
        assert "결정 임계" in out


# ════════════════════════════════════════════════════════════════
# 엣지 — 빈 state / None / 깨진 입력
# ════════════════════════════════════════════════════════════════
class TestEdgeCases:
    def test_empty_state_returns_graceful(self):
        """전부 None → 기본값 + 응급 안전망."""
        from agents.handlers.timeseries.insight import fallback

        st = _StubState()
        out = fallback(st)
        assert isinstance(out, str)
        assert len(out) > 5
        # 한국어 1자+
        assert any("가" <= c <= "힣" for c in out)

    def test_eval_result_none_still_works(self):
        """eval_result=None → eval_diagnostics 빈 dict 처리."""
        from agents.handlers.timeseries.insight import fallback

        st = _full_state(eval_result=None)
        out = fallback(st)
        assert isinstance(out, str)

    def test_proposer_import_failure_graceful(self):
        """proposer.g1 import 실패 시 _zero_step_meta 가 기본값 반환."""
        from agents.handlers.timeseries.insight import _zero_step_meta

        # state 가 비어서 proposer.g1 이 default 반환 시 graceful
        st = _StubState()
        meta = _zero_step_meta(st)
        assert isinstance(meta, dict)
        # 4 키 모두 존재
        for k in ("variate", "forecast_kind", "task_kind", "horizon_hint"):
            assert k in meta

    def test_all_metrics_none_still_returns_text(self):
        """모든 메트릭 None — 응급 보강 동작 (수치 0 위험 케이스)."""
        from agents.handlers.timeseries.insight import fallback

        st = _full_state(
            best_model={"model_name": "X", "metrics": {}},
            data_profile={
                "freq": "D",
                "trend": {"direction": "none"},
                "seasonality": {"has_seasonality": False},
            },
            eda_summary={},
            eval_result={},
        )
        out = fallback(st)
        assert isinstance(out, str)
        assert len(out) > 10


# ════════════════════════════════════════════════════════════════
# 통합 — AirPassengers 풀스택 (DoD 보장)
# ════════════════════════════════════════════════════════════════
class TestIntegrationDoD:
    def test_airpassengers_fullstack_meets_dod(self):
        """AirPassengers (SARIMA imp=+44%, MASE=0.78) → DoD 충족.
        한국어 3문장+ / 수치 2개+ / 마크다운/이모지 없음.
        """
        import re

        from agents.handlers.timeseries.insight import fallback

        st = _full_state()  # 기본 시나리오
        out = fallback(st)
        # 마크다운/이모지 없음
        assert "*" not in out
        assert "#" not in out
        # 한국어 1자+
        assert any("가" <= c <= "힣" for c in out)
        # 수치 2개+ (정규식 — 0.83, 12%, 144 등)
        nums = re.findall(r"-?\d+(?:[.,]\d+)?\s*%?", out)
        assert len(nums) >= 2
        # 문장 수 3+ (마침표 기준 대략)
        sentence_count = len([s for s in re.split(r"(?<!\d)[.!?](?!\d)\s+", out) if s.strip()])
        assert sentence_count >= 3
