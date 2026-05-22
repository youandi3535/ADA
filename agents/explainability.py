"""agents.explainability — ExplainabilityAgent (Day11).

v2 — GradCAM/Attention 제거. SHAP + 시계열 분해만 사용.
SHAP 층화 샘플링(R-501) — 큰 데이터에서 stratified sample 1000 row.
"""

from __future__ import annotations

import tempfile
from typing import Any

import numpy as np

from ada.core.state import PipelineState
from agents.base import BaseAgent


class ExplainabilityAgent(BaseAgent):
    uses_llm = False
    SAMPLE_SIZE = 1000

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            artifacts: dict[str, Any] = {}
            if state.category == "timeseries":
                artifacts.update(await self._timeseries_decompose(state))
            else:
                artifacts.update(await self._shap(state))
            return state.with_update(explanations=artifacts, next_agent="insight")

    # ------------------------------------------------------------------
    async def _shap(self, state: PipelineState) -> dict[str, Any]:
        import joblib  # noqa: WPS433
        import shap  # type: ignore

        from tools.minio_tool import get_minio_client

        mc = get_minio_client()
        best = state.best_model or {}
        if "minio_path" not in best:
            return {"shap_skipped": "no model path"}

        try:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".joblib")
            tmp.close()
            with open(tmp.name, "wb") as f:
                # MinIO 에서 다운로드
                f.write(mc.download_bytes(best["minio_path"].replace(f"s3://{mc.bucket}/", "")))
            model = joblib.load(tmp.name)
        except Exception as e:
            return {"shap_error": str(e)}

        try:
            df = mc.load_dataframe(state.file_id, fmt=state.file_id.rsplit(".", 1)[-1].lower())
            X = df.select_dtypes(include=[np.number, "bool"]).fillna(0)
            if state.target_column in X.columns:
                X = X.drop(columns=[state.target_column])
            if len(X) > self.SAMPLE_SIZE:
                X = X.sample(self.SAMPLE_SIZE, random_state=42)
            explainer = shap.Explainer(model, X[:100])
            sv = explainer(X[:200])
            top_features = (
                np.abs(sv.values).mean(axis=0) if sv.values.ndim == 2 else np.abs(sv.values).mean(axis=(0, 2))
            )
            order = np.argsort(-top_features)
            ranking = [{"feature": str(X.columns[i]), "importance": float(top_features[i])} for i in order[:20]]

            # SHAP summary plot 저장
            import matplotlib  # noqa: WPS433

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt  # noqa: WPS433

            plt.figure(figsize=(8, 6))
            try:
                shap.plots.beeswarm(sv, show=False, max_display=15)
            except Exception:
                shap.summary_plot(sv.values, X[:200], show=False)
            tmpf = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            tmpf.close()
            plt.savefig(tmpf.name, dpi=120, bbox_inches="tight")
            plt.close()
            shap_path = mc.save_artifact(tmpf.name, "explanations/shap", state.job_id)
            return {"shap_top_features": ranking, "shap_summary_path": shap_path}
        except Exception as e:
            return {"shap_error": str(e)}

    # ------------------------------------------------------------------
    async def _timeseries_decompose(self, state: PipelineState) -> dict[str, Any]:
        import matplotlib  # noqa: WPS433

        from tools.minio_tool import get_minio_client

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # noqa: WPS433
        from statsmodels.tsa.seasonal import seasonal_decompose

        mc = get_minio_client()
        try:
            df = mc.load_dataframe(state.file_id, fmt=state.file_id.rsplit(".", 1)[-1].lower())
            y = df[state.target_column].dropna().astype(float)
            period = 7 if len(y) >= 60 else max(2, len(y) // 4)
            dec = seasonal_decompose(y, model="additive", period=period)
            fig = dec.plot()
            fig.set_size_inches(10, 6)
            tmpf = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            tmpf.close()
            fig.savefig(tmpf.name, dpi=120)
            plt.close(fig)
            path = mc.save_artifact(tmpf.name, "explanations/ts_decompose", state.job_id)
            return {"timeseries_decompose_path": path, "period": period}
        except Exception as e:
            return {"timeseries_decompose_error": str(e)}
