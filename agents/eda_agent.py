"""agents.eda_agent — EDAAgent (Day10).

v2 — 워드클라우드/이미지 그리드 차트 제거. 정형/시계열 차트만 생성.
차트는 MinIO 에 PNG 로 저장 후 state.eda_charts 에 경로 추가.
"""
from __future__ import annotations

import io
import tempfile
import uuid
from typing import Any

from ada.core.state import PipelineState
from agents.base import BaseAgent


class EDAAgent(BaseAgent):
    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            from tools.minio_tool import get_minio_client
            mc = get_minio_client()
            try:
                fmt = state.file_id.rsplit(".", 1)[-1].lower()
                df = mc.load_dataframe(state.file_id, fmt=fmt)
            except Exception as e:
                self.logger.warning("eda_load_failed", error=str(e))
                return state.with_update(next_agent="gate_methodology")

            charts = []
            try:
                import matplotlib  # noqa: WPS433
                matplotlib.use("Agg")
                import matplotlib.pyplot as plt  # noqa: WPS433

                # 1) 결측 막대 차트
                miss = df.isnull().mean().sort_values(ascending=False).head(20)
                if not miss.empty:
                    fig, ax = plt.subplots(figsize=(8, 4))
                    miss.plot(kind="barh", ax=ax)
                    ax.set_title("Missing rate (top 20)")
                    charts.append(self._save_fig(fig, state.job_id, "missing"))

                # 2) 수치형 분포 — 첫 6 컬럼
                num_cols = df.select_dtypes(include="number").columns[:6]
                if len(num_cols):
                    fig, axes = plt.subplots(2, 3, figsize=(12, 6))
                    for i, c in enumerate(num_cols):
                        ax = axes[i // 3, i % 3]
                        df[c].plot(kind="hist", ax=ax, bins=30)
                        ax.set_title(c)
                    fig.tight_layout()
                    charts.append(self._save_fig(fig, state.job_id, "hist"))

                # 3) 상관관계 히트맵
                if len(num_cols) >= 2:
                    corr = df[num_cols].corr()
                    fig, ax = plt.subplots(figsize=(6, 5))
                    im = ax.imshow(corr.values, vmin=-1, vmax=1, cmap="RdBu")
                    ax.set_xticks(range(len(corr.columns)))
                    ax.set_yticks(range(len(corr.columns)))
                    ax.set_xticklabels(corr.columns, rotation=45, ha="right")
                    ax.set_yticklabels(corr.columns)
                    fig.colorbar(im, ax=ax)
                    ax.set_title("Correlation")
                    charts.append(self._save_fig(fig, state.job_id, "corr"))

                # 4) 시계열 plot
                if state.category == "timeseries" and state.target_column in df.columns:
                    fig, ax = plt.subplots(figsize=(10, 3))
                    df[state.target_column].plot(ax=ax)
                    ax.set_title(f"{state.target_column} over time")
                    charts.append(self._save_fig(fig, state.job_id, "ts"))
            except Exception as e:
                self.logger.warning("eda_chart_failed", error=str(e))

            summary = (
                f"행수={len(df):,}, 열수={df.shape[1]:,}, "
                f"수치형 컬럼 {len(df.select_dtypes(include='number').columns)}개. "
                f"카테고리={state.category}."
            )
            return state.with_update(
                eda_charts=charts,
                eda_summary=summary,
                next_agent="gate_methodology",
            )

    def _save_fig(self, fig: Any, job_id: str, kind: str) -> str:
        import matplotlib.pyplot as plt  # noqa: WPS433
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as f:
            fig.savefig(f.name, dpi=120, bbox_inches="tight")
            tmp = f.name
        plt.close(fig)
        from tools.minio_tool import get_minio_client
        return get_minio_client().save_artifact(tmp, f"eda/{kind}", job_id)
