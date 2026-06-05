"""테스트 — HJ-A (preprocessed_data_id 우선 로드) + HJ-7 (chosen_recipe 채움) (2026-06-05).

HJ-A: agents.handlers.common.shared.load_dataframe_from_state 가
      state.preprocessed_data_id 가 있으면 그 parquet 을 우선 로드.
      prefer_processed=False 시 항상 원본 uploads/.

HJ-7: agents.gates.methodology_proposer.ModelStrategyProposerAgent._apply_choice 가
      state.chosen_recipe 정식 필드를 채움.
"""

from __future__ import annotations

import pytest


# ════════════════════════════════════════════════════════
# HJ-A — preprocessed_data_id 우선 로드
# ════════════════════════════════════════════════════════
class TestPreprocessedDataIdLoad:
    def test_signature_has_prefer_processed_kw(self):
        import inspect

        from agents.handlers.common.shared import load_dataframe_from_state

        sig = inspect.signature(load_dataframe_from_state)
        assert "prefer_processed" in sig.parameters
        assert sig.parameters["prefer_processed"].default is True

    def test_processed_loaded_when_id_set(self, monkeypatch):
        """state.preprocessed_data_id 가 있으면 그것 로드."""
        import sys
        import types

        from agents.handlers.common import shared

        calls: list[tuple[str, str]] = []

        class FakeClient:
            bucket = "test"

            def load_dataframe(self, key, fmt):
                calls.append((key, fmt))
                import pandas as pd

                return pd.DataFrame({"y": [1, 2, 3]})

            def list_objects(self, prefix):
                return []

        fake_mod = types.ModuleType("tools.minio_tool")
        fake_mod.get_minio_client = lambda: FakeClient()  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "tools.minio_tool", fake_mod)

        class FakeState:
            file_id = "raw_id_xyz"
            preprocessed_data_id = "processed/jobX/data.parquet"

        df = shared.load_dataframe_from_state(FakeState())
        assert len(df) == 3
        assert calls[0][0] == "processed/jobX/data.parquet"
        assert calls[0][1] == "parquet"

    def test_uploads_fallback_when_no_processed(self, monkeypatch):
        """preprocessed_data_id 미설정 → uploads/ 로드."""
        import sys
        import types

        from agents.handlers.common import shared

        calls: list[tuple[str, str]] = []

        class FakeClient:
            bucket = "test"

            def load_dataframe(self, key, fmt):
                calls.append((key, fmt))
                import pandas as pd

                return pd.DataFrame({"y": [10, 20]})

            def list_objects(self, prefix):
                return [prefix + "data.csv"]

        fake_mod = types.ModuleType("tools.minio_tool")
        fake_mod.get_minio_client = lambda: FakeClient()  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "tools.minio_tool", fake_mod)

        class FakeState:
            file_id = "abc"
            preprocessed_data_id = None

        df = shared.load_dataframe_from_state(FakeState())
        assert len(df) == 2
        assert calls[0][0].startswith("uploads/")

    def test_prefer_processed_false_forces_uploads(self, monkeypatch):
        """prefer_processed=False → preprocessed_data_id 있어도 uploads/ 로드."""
        import sys
        import types

        from agents.handlers.common import shared

        calls: list[tuple[str, str]] = []

        class FakeClient:
            bucket = "test"

            def load_dataframe(self, key, fmt):
                calls.append((key, fmt))
                import pandas as pd

                return pd.DataFrame({"y": [99]})

            def list_objects(self, prefix):
                return [prefix + "raw.csv"]

        fake_mod = types.ModuleType("tools.minio_tool")
        fake_mod.get_minio_client = lambda: FakeClient()  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "tools.minio_tool", fake_mod)

        class FakeState:
            file_id = "fid"
            preprocessed_data_id = "processed/jobX/data.parquet"

        df = shared.load_dataframe_from_state(FakeState(), prefer_processed=False)
        assert len(df) == 1
        # processed 경로 호출 X — uploads 경로만
        assert all("processed/" not in c[0] for c in calls)


# ════════════════════════════════════════════════════════
# HJ-7 — chosen_recipe 채워짐
# ════════════════════════════════════════════════════════
class TestChosenRecipeFill:
    def test_chosen_recipe_set_when_proposal_adopted(self):
        from ada.core.state import PipelineState
        from agents.gates.methodology_proposer import MethodologyProposerAgent

        agent = MethodologyProposerAgent.__new__(MethodologyProposerAgent)
        # logger mock
        import logging

        agent.logger = logging.getLogger("test_g3")

        state = PipelineState(job_id="j", file_id="f", category="timeseries")
        proposals = [
            {
                "id": 1,
                "title": "시계열 분해",
                "rationale": "STL 분해로 추세·계절·잔차 분리",
                "category": "timeseries",
                "meta": {
                    "variate": "univariate",
                    "forecast_kind": "point",
                    "task_kind": "regression",
                    "horizon_hint": 7,
                },
            }
        ]

        new_state = agent._apply_choice(state, {"adopted_rank": 1}, proposals)
        assert new_state.chosen_recipe is not None
        assert new_state.chosen_recipe["title"] == "시계열 분해"
        assert new_state.chosen_recipe["meta"]["forecast_kind"] == "point"
        assert new_state.chosen_recipe["is_custom"] is False

    def test_chosen_recipe_custom_intent(self):
        from ada.core.state import PipelineState
        from agents.gates.methodology_proposer import MethodologyProposerAgent

        agent = MethodologyProposerAgent.__new__(MethodologyProposerAgent)
        import logging

        agent.logger = logging.getLogger("test_g3_custom")

        state = PipelineState(job_id="j", file_id="f", category="timeseries")
        new_state = agent._apply_choice(state, {"custom_intent": "Prophet + 추세 분해"}, [])
        assert new_state.chosen_recipe is not None
        assert new_state.chosen_recipe["is_custom"] is True
        assert "Prophet" in new_state.chosen_recipe["title"]
        assert "meta" in new_state.chosen_recipe

    def test_chosen_recipe_none_when_no_choice(self):
        from ada.core.state import PipelineState
        from agents.gates.methodology_proposer import MethodologyProposerAgent

        agent = MethodologyProposerAgent.__new__(MethodologyProposerAgent)
        import logging

        agent.logger = logging.getLogger("test_g3_none")

        state = PipelineState(job_id="j", file_id="f", category="timeseries")
        new_state = agent._apply_choice(state, {}, [])
        assert new_state.chosen_recipe is None
