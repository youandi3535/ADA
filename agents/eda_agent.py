"""agents.eda_agent — Day 0 dispatcher 패턴.

카테고리별 차트 생성은 ``handlers/{cat}/eda.charts(df, state)`` 가 담당.
수정 권한: **HJ 단독** (dispatcher).
"""

from __future__ import annotations

import agents.handlers.anomaly  # noqa: F401
import agents.handlers.tabular  # noqa: F401
import agents.handlers.timeseries  # noqa: F401
from ada.core.state import PipelineState
from agents.base import BaseAgent
from agents.handlers import get_handler
from agents.handlers.common.shared import load_dataframe_from_state


def _safe_publish_stage_partial(job_id: str | None, partial: dict) -> None:
    """HJ 2026-06-10 — orchestrator.runner.publish_stage_partial 로 안전 위임.

    import 실패·Redis 실패 어떤 경우에도 본 agent 흐름에 영향 주지 않음.
    """
    if not job_id or not partial:
        return
    try:
        from orchestrator.runner import publish_stage_partial as _psp

        _psp(job_id, partial)
    except Exception:  # noqa: BLE001
        pass


class EDAAgent(BaseAgent):
    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            charts: list[str] = []
            _safe_publish_stage_partial(state.job_id, {"eda_status": "데이터셋 로드 중…", "eda_phase": "load"})
            try:
                df = load_dataframe_from_state(state)
            except Exception as e:
                self.logger.warning("eda_load_failed", error=str(e))
                _safe_publish_stage_partial(
                    state.job_id,
                    {"eda_status": f"데이터 로드 실패: {str(e)[:160]}", "eda_phase": "error"},
                )
                return state.with_update(next_agent="gate_methodology")

            _safe_publish_stage_partial(
                state.job_id,
                {
                    "eda_status": f"EDA 차트 생성 시작 (카테고리: {state.category})",
                    "eda_phase": "charts",
                    "eda_rows": int(len(df)),
                    "eda_cols": int(df.shape[1]),
                },
            )

            handler = get_handler(state.category, "charts")
            if handler is not None:
                try:
                    charts = handler(df, state) or []
                except Exception as e:
                    self.logger.warning("eda_handler_failed", category=state.category, error=str(e))
                    _safe_publish_stage_partial(
                        state.job_id,
                        {"eda_status": f"차트 핸들러 일부 실패: {str(e)[:160]}"},
                    )

            _safe_publish_stage_partial(
                state.job_id,
                {
                    "eda_status": f"차트 {len(charts)}종 생성 완료 — 데이터 인사이트 추출 중",
                    "eda_phase": "insights",
                    "eda_charts_count": len(charts),
                },
            )

            # HJ 2026-06-10 — EDA 데이터 인사이트 추출 (1단계 도메인 분석처럼 사용자에게 의미 설명).
            # 결측·상관·클래스 분포·분포 비대칭 4개 축으로 quick analysis → 자연어 문장 N개 생성.
            insights: list[str] = []
            try:
                import pandas as _pd  # noqa: F401  (df 가 pd.DataFrame)

                # 1) 결측치 top 3
                try:
                    miss = df.isnull().mean()
                    miss_top = miss[miss > 0.1].nlargest(3)
                    for col, ratio in miss_top.items():
                        pct = ratio * 100
                        if ratio > 0.5:
                            tail = "과반 결측 — 컬럼 자체 활용 어려움. '값 보유 여부' 를 boolean 파생 피처로 만드는 편이 효과적."
                        elif ratio > 0.3:
                            tail = "결측이 많음 — KNN/median imputation 또는 결측 자체를 정보로 인코딩."
                        else:
                            tail = "중간 수준 결측 — 단순 imputation 으로 처리 가능."
                        insights.append(f"결측 분석: '{col}' {pct:.1f}% 결측 — {tail}")
                except Exception:  # noqa: BLE001
                    pass

                # 2) 타깃과의 상관 top 3 (지도학습 + 타깃 있을 때)
                try:
                    tgt = state.target_column
                    if tgt and tgt in df.columns:
                        target = df[tgt]
                        # target 이 수치형이면 직접 상관, 범주형이면 점이연(Sex 같이 0/1 encoded) 만 처리
                        num_df = df.select_dtypes(include="number")
                        if tgt in num_df.columns:
                            corrs = num_df.corr(numeric_only=True)[tgt].drop(tgt).abs().nlargest(3)
                        else:
                            # target 을 numeric 으로 cast 시도 (binary string 등)
                            try:
                                tnum = _pd.to_numeric(target, errors="coerce")
                                if tnum.notna().sum() > 0:
                                    corrs = num_df.corrwith(tnum).abs().nlargest(3)
                                else:
                                    corrs = _pd.Series(dtype=float)
                            except Exception:  # noqa: BLE001
                                corrs = _pd.Series(dtype=float)
                        for col, c in corrs.items():
                            if _pd.isna(c) or c < 0.05:
                                continue
                            if c >= 0.6:
                                hint = f"매우 강한 예측력 — 단독으로도 분류·회귀 핵심 피처. '{col}' 만 잘 다루면 베이스라인 모델 성능 빠르게 확보."
                            elif c >= 0.35:
                                hint = "중간 예측력 — 다른 피처와 결합 시 추가 신호로 작용. 결측·이상치 정제가 효과 크게 좌우."
                            else:
                                hint = "약한 단독 신호이지만 다른 변수와 교호작용·파생 피처로 의미 있는 기여 가능."
                            insights.append(f"상관관계: '{col}' ↔ '{tgt}' 상관계수 {c:.2f} — {hint}")
                except Exception:  # noqa: BLE001
                    pass

                # 3) 클래스 분포 (분류일 때)
                try:
                    tgt = state.target_column
                    if tgt and tgt in df.columns:
                        target = df[tgt]
                        if target.dtype.kind in "biOu" or target.nunique(dropna=True) < 10:
                            vc = target.value_counts(normalize=True, dropna=True)
                            if len(vc) >= 2:
                                top_r, bot_r = float(vc.iloc[0]), float(vc.iloc[-1])
                                ratio = top_r / max(bot_r, 1e-9)
                                vc_txt = ", ".join([f"{k}: {v * 100:.1f}%" for k, v in vc.head(4).items()])
                                if ratio > 4:
                                    hint = (
                                        f"심한 불균형 ({ratio:.1f}배). 단순 accuracy 는 misleading — "
                                        "F1/AUROC·SMOTE/언더샘플링·class_weight 조정 필수."
                                    )
                                elif ratio > 2:
                                    hint = f"약한 불균형 ({ratio:.1f}배). 대부분 모델에서 stratified split + class_weight 만으로 OK."
                                else:
                                    hint = "균형 잡힌 분포 — 일반적인 metric/샘플링 전략 자유롭게 선택."
                                insights.append(f"클래스 분포: {vc_txt} — {hint}")
                except Exception:  # noqa: BLE001
                    pass

                # 4) 분포 비대칭 (skew top 2)
                try:
                    num = df.select_dtypes(include="number")
                    if len(num.columns) > 0:
                        skews = num.skew(numeric_only=True).abs().nlargest(2)
                        for col, sk in skews.items():
                            if _pd.isna(sk) or sk < 1.0:
                                continue
                            insights.append(
                                f"분포 비대칭: '{col}' 컬럼 skew {sk:.2f} — 오른쪽으로 긴 꼬리. "
                                "log/Box-Cox 변환으로 정규성 개선 시 선형 모델 안정성 큰 폭 향상."
                            )
                except Exception:  # noqa: BLE001
                    pass
            except Exception as e:  # noqa: BLE001
                self.logger.warning("eda_insight_compute_failed", error=str(e))

            if insights:
                insights = await self._dynamic_insights(insights, backend="ollama", context=f"G2 EDA·{state.category}")
                _safe_publish_stage_partial(
                    state.job_id,
                    {"eda_insights": insights, "eda_phase": "insights_done"},
                )

            summary = f"행수={len(df):,}, 열수={df.shape[1]:,}, 카테고리={state.category}, 생성 차트 {len(charts)}종."
            _safe_publish_stage_partial(
                state.job_id,
                {
                    "eda_status": "EDA 완료 — 방법론 추천 단계로 이동",
                    "eda_phase": "done",
                    "eda_summary_text": summary,
                },
            )

            new_state = state.with_update(
                eda_charts=charts,
                eda_summary=summary,
                next_agent="gate_methodology",
            )

            # Phase 1.4 — ReportContext ⑤ eda 적립.
            # MinIO 경로만 받으므로 chart_type/finding 은 unknown. ChartAnnotator(Phase 3)
            # 가 메타를 보강. severity 는 info 기본.
            try:
                eda_charts_meta = [
                    {
                        "path": str(p),
                        "chart_type": "unknown",
                        "title_ko": "",
                        "finding": "",
                        "severity": "info",
                    }
                    for p in charts
                ]
                new_state = self.contribute_to_context(
                    new_state,
                    "eda",
                    {"charts": eda_charts_meta},
                )
            except Exception as e:
                self.logger.warning("contribute_eda_failed", error=str(e))
            return new_state
