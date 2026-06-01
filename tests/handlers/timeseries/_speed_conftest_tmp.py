# 모든 test 에 MinIO mock 자동 주입 — boto3 재시도 회피 (검증 속도용)
import pytest


@pytest.fixture(autouse=True)
def _mock_minio(monkeypatch):
    import agents.handlers.common.shared as shared

    def fake_save(fig, *, kind, job_id):
        try:
            import matplotlib.pyplot as plt

            plt.close(fig)
        except Exception:
            pass
        return f"s3://autoai-artifacts/eda/{kind}/{job_id}.png"

    def fake_load(state):
        import numpy as np
        import pandas as pd

        return pd.DataFrame(
            {"date": pd.date_range("2024-01-01", periods=60, freq="D"), "sales": np.linspace(100, 160, 60)}
        )

    monkeypatch.setattr(shared, "save_chart_to_minio", fake_save, raising=False)
    monkeypatch.setattr(shared, "load_dataframe_from_state", fake_load, raising=False)
