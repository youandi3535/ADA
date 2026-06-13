"""agents.handlers.common.gates.significant_lift 단위 테스트 (HJ).

카테고리 무관 "상대·유의성" 게이트 원시도구 검증.
"""

from agents.handlers.common.gates import significant_lift


class TestSignificantLift:
    def test_true_when_diff_exceeds_k_std(self):
        # higher_better: 0.9 vs 0.5, std 0.1, k=2 → 마진 0.2, diff 0.4 → True
        assert significant_lift(0.9, 0.5, 0.1, k=2.0) is True

    def test_false_when_within_noise(self):
        # diff 0.05 < 2*0.1=0.2 → noise 수준 → False
        assert significant_lift(0.55, 0.5, 0.1, k=2.0) is False

    def test_false_when_baseline_better(self):
        # 모델이 baseline 보다 나쁨 → diff 음수 → False
        assert significant_lift(0.4, 0.5, 0.1) is False

    def test_none_when_std_missing(self):
        assert significant_lift(0.9, 0.5, None) is None

    def test_none_when_std_zero(self):
        # std<=0 이면 유의성 판단 불가
        assert significant_lift(0.9, 0.5, 0.0) is None

    def test_none_when_scores_missing(self):
        assert significant_lift(None, 0.5, 0.1) is None
        assert significant_lift(0.9, None, 0.1) is None

    def test_lower_better_rmse(self):
        # higher_better=False: rmse 0.3 < baseline 1.0, std 0.1 → diff 0.7 >= 0.2 → True
        assert significant_lift(0.3, 1.0, 0.1, higher_better=False) is True
        # rmse 0.95 vs 1.0 → diff 0.05 < 0.2 → False
        assert significant_lift(0.95, 1.0, 0.1, higher_better=False) is False

    def test_k_controls_strictness(self):
        # diff 0.3, std 0.1 → k=2(마진0.2) True / k=4(마진0.4) False
        assert significant_lift(0.8, 0.5, 0.1, k=2.0) is True
        assert significant_lift(0.8, 0.5, 0.1, k=4.0) is False

    def test_non_numeric_returns_none(self):
        assert significant_lift("x", 0.5, 0.1) is None
