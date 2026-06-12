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


# HJ 2026-06-12 — C′-1: EDA 규칙 인사이트 계산을 모듈 함수로 추출(노드 + prefetch 선계산 공유).
#   df + target_column 만 의존(주제·방향 무관) → 2단계 주제 선택 중 백그라운드 선계산 가능.
def compute_eda_rule_insights(df, target_column) -> list[str]:
    """EDA 규칙 기반 인사이트(결측·상관·클래스분포·분포비대칭 4축) → 자연어 문장 리스트."""
    import pandas as _pd  # noqa: F401

    insights: list[str] = []
    try:
        # 1) 결측치 top 3
        try:
            miss = df.isnull().mean()
            miss_top = miss[miss > 0.1].nlargest(3)
            for col, ratio in miss_top.items():
                pct = ratio * 100
                if ratio > 0.5:
                    tail = (
                        "과반 결측 — 컬럼 자체 활용 어려움. '값 보유 여부' 를 boolean 파생 피처로 만드는 편이 효과적."
                    )
                elif ratio > 0.3:
                    tail = "결측이 많음 — KNN/median imputation 또는 결측 자체를 정보로 인코딩."
                else:
                    tail = "중간 수준 결측 — 단순 imputation 으로 처리 가능."
                insights.append(f"결측 분석: '{col}' {pct:.1f}% 결측 — {tail}")
        except Exception:  # noqa: BLE001
            pass

        # 2) 타깃과의 상관 top 3 (지도학습 + 타깃 있을 때)
        try:
            tgt = target_column
            if tgt and tgt in df.columns:
                target = df[tgt]
                num_df = df.select_dtypes(include="number")
                if tgt in num_df.columns:
                    corrs = num_df.corr(numeric_only=True)[tgt].drop(tgt).abs().nlargest(3)
                else:
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
            tgt = target_column
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
    except Exception:  # noqa: BLE001
        pass
    return insights


def _eda_insights_cache_key(job_id: str) -> str:
    return f"ada:g2_eda_ins:{job_id}"


def _eda_insights_cache_get(job_id, category, target_column):
    """C′-1: 선계산된 EDA 윤색 인사이트 캐시 조회. category/target 일치 시에만 반환(데이터 정합)."""
    if not job_id:
        return None
    try:
        import json as _json

        import redis as _redis

        from ada.core.config import settings

        r = _redis.Redis.from_url(settings.redis_url)
        raw = r.get(_eda_insights_cache_key(job_id))
        if not raw:
            return None
        d = _json.loads(raw)
        if (
            d.get("status") == "done"
            and d.get("insights")
            and d.get("category") == category
            and d.get("target") == (target_column or None)
        ):
            return d["insights"]
    except Exception:  # noqa: BLE001
        return None
    return None


def _eda_insights_cache_set(job_id, category, target_column, insights) -> None:
    if not job_id or not insights:
        return
    try:
        import json as _json

        import redis as _redis

        from ada.core.config import settings

        r = _redis.Redis.from_url(settings.redis_url)
        r.set(
            _eda_insights_cache_key(job_id),
            _json.dumps(
                {"status": "done", "category": category, "target": (target_column or None), "insights": insights},
                ensure_ascii=False,
            ),
            ex=86400,
        )
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

            # HJ 2026-06-12 (마스터 지시) — 조기 발행: 차트(병목)·LLM 윤색(120~160초) 을 기다리지 않고,
            #   df 기반 규칙 인사이트(결측·상관·클래스·skew)를 즉시 publish → 모달 5초 후 실제 분석 글 표시.
            #   이후 아래에서 차트/LLM 윤색이 끝나면 정밀 인사이트로 교체 publish 한다(무중단).
            try:
                _early = compute_eda_rule_insights(df, state.target_column)
                if _early:
                    _safe_publish_stage_partial(
                        state.job_id,
                        {
                            "eda_insights": _early,
                            "eda_status": "기초 EDA 분석 결과 — 더 정밀한 해석으로 업그레이드 중…",
                            "eda_phase": "early",
                        },
                    )
            except Exception:  # noqa: BLE001
                pass

            charts_meta: list[dict] = []
            handler = get_handler(state.category, "charts")
            if handler is not None:
                try:
                    result = handler(df, state) or []
                    # HJ 2026-06-11 (jh 대행) — (paths, meta) 튜플 반환 허용.
                    # meta: list[dict] (EDAChart 필드 — x/finding/numbers/title_ko 등).
                    # 기존 핸들러 (paths 만 반환) 는 그대로 호환.
                    if isinstance(result, tuple) and len(result) == 2:
                        charts, charts_meta = list(result[0] or []), list(result[1] or [])
                    else:
                        charts = list(result)
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
            insights = compute_eda_rule_insights(df, state.target_column)
            if insights:
                # HJ 2026-06-12 — C′-1: prefetch 가 주제 선택 중 미리 만든 EDA 윤색 인사이트가 있으면 LLM 스킵.
                #   EDA 인사이트는 방향/주제와 무관(df+category+target만 의존) → resume 전 선계산 → 120~160초 절감.
                #   캐시 miss(미완·카테고리 변경)면 기존대로 그 자리에서 LLM 윤색(폴백).
                cached = _eda_insights_cache_get(state.job_id, state.category, state.target_column)
                if cached:
                    insights = cached
                    self.logger.info("eda_insights_cache_hit", n=len(cached))
                else:
                    insights = await self._dynamic_insights(
                        insights,
                        backend="ollama",
                        context=f"G2 EDA·{state.category}",
                        job_id=state.job_id,
                        key="eda_insights",
                    )
                    _eda_insights_cache_set(state.job_id, state.category, state.target_column, insights)
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
            # HJ 2026-06-11 (jh 대행) — 핸들러가 meta 를 주면 그대로 사용 (path 기준 매칭),
            # 없으면 기존처럼 빈 메타. (구주석의 ChartAnnotator 는 미구현 — meta 채널로 대체)
            try:
                _meta_by_path = {str(m.get("path", "")): m for m in charts_meta if isinstance(m, dict)}
                eda_charts_meta = [
                    {
                        "path": str(p),
                        "chart_type": "unknown",
                        "title_ko": "",
                        "finding": "",
                        "severity": "info",
                        **{k: v for k, v in _meta_by_path.get(str(p), {}).items() if k != "path"},
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
