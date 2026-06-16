"""agents.handlers.timeseries.eda — 시계열 EDA 차트 (CS 담당, cs-day3 v3 디벨롭).

방법론 2단계(EDA — 시간 구조) 전부를 차트·수치로 표현 + profiler 진단 승계.

차트 (모두 MinIO 저장, 인라인 try/except 독립):
  ① missing 막대 (Chart 0)
  ② line plot + 레짐/이벤트 오버레이 (Chart 1)   ← 2-1 레짐변화·이벤트 표시
  ③ ACF (Chart 2, statsmodels lazy import)         ← 2-4 ACF
  ④ PACF (Chart 2b, statsmodels lazy import)        ← 2-4 PACF (신규)
  ⑤ STL 4단 분해 (Chart 3, n ≥ 2s 가드)             ← 2-2 분해
  ⑥ seasonality heatmap year×month (Chart 4)
  ⑦ rolling std — 이분산 (Chart 5, 신규)            ← 2-1 분산의 시간변화
  ⑧ CCF — 시차상관 (Chart 6, exog 있을 때, 신규)     ← 2-5 시차상관

진입함수 (dispatcher 자동 등록):
  - charts(df, state) -> list[str]   MinIO 경로 list
    (부수효과로 charts.last_eda_summary 에 dict 부착 → dispatcher 가 state.eda_summary 로 전달)

DoD: 4+ chart MinIO 저장 + eda_summary 갱신 (seasonal_period · stationary · acf_peaks
     · changepoints · is_multiplicative · ccf_top_lags · heteroscedastic).

핵심 설계 원칙:
  - 인라인 try/except 우선 — 각 차트 독립 (한 차트 실패가 전체로 안 번짐)
  - 자연 발생 롤백 3 개만 (target/n_rows/모든 실패) — A-1/A-2/G-1 가드 (불변)
  - lazy import (statsmodels, seaborn) — 미설치 인라인 skip
  - seasonal_period 우선순위 — eda → acf → freq fallback (D=7, M=12)
  - 임시 컬럼명 충돌 회피 — _year, _month
  - ★ profiler 산출물 재사용(재계산 X) — data_profile 의 진단을 eda_summary 로 승계
  - ★ 정상성은 profiler ADF+KPSS 4-case 우선, 없으면 자체 ADF fallback (방법론 2-3 교차)
"""

from __future__ import annotations

from typing import Any

# ── 모듈 상수 ─────────────────────────────────────────────────────
MIN_ROWS_FOR_EDA = 10  # A-2 가드 (cs-day2 RB-5 와 일관)
MIN_ROWS_FOR_ACF = 20  # D-2a 가드
ACF_PEAK_HEIGHT = 0.1
MISSING_TOP_K = 20
FREQ_SEASONAL_FALLBACK = {"D": 7, "W": 4, "M": 12, "MS": 12, "H": 24}
MAX_CHANGEPOINT_MARKS = 20  # 오버레이 수직선 상한


# ════════════════════════════════════════════════════════════════
# seasonal_period 추정 (3 단 우선순위)
# ════════════════════════════════════════════════════════════════
def _infer_seasonal_period(eda_summary: dict, freq: Any, acf_peaks: list[int], n_rows: int) -> int:
    """seasonal_period 추정 — eda 명시 → acf 첫 유의 peak → freq fallback."""
    # 1. eda_summary 명시 (외부 입력)
    s = (eda_summary or {}).get("seasonal_period")
    if isinstance(s, int) and 1 < s <= n_rows // 2:
        return s
    # 2. acf_peaks 첫 유의 peak (lag 1 제외)
    valid_peaks = [p for p in acf_peaks if 1 < p <= n_rows // 2]
    if valid_peaks:
        return int(valid_peaks[0])
    # 3. freq 기반 fallback
    return int(FREQ_SEASONAL_FALLBACK.get(freq, 0))


def _eda_summary_dict(state: Any) -> dict:
    """state.eda_summary 가 str(또는 None)일 수 있으므로 dict 로 안전 변환.

    PipelineState.eda_summary 는 Optional[str] 타입이라 직접 .get() 불가.
    dispatcher 가 dict 를 넣어주는 경우(테스트/확장)와 None/str 모두 graceful.
    """
    raw = getattr(state, "eda_summary", None)
    if isinstance(raw, dict):
        return raw
    return {}


# ════════════════════════════════════════════════════════════════
# ★ profiler 산출물 승계 (재계산 X — 방법론 2 전부를 다운스트림으로 전달)
# ════════════════════════════════════════════════════════════════
def _carry_from_profile(profile: dict) -> dict[str, Any]:
    """profiler 가 이미 계산한 진단을 eda_summary 로 승계한다.

    profiler Phase 결과를 None-안전하게 평탄화. 소비처(proposer/selector/insight)가
    eda_summary 에서 바로 읽도록 키 이름을 맞춘다. profiler 미실행 시 모두 None.
    """
    p = profile or {}

    def _g(key: str, sub: str | None = None) -> Any:
        v = p.get(key)
        if sub is None:
            return v
        return (v or {}).get(sub) if isinstance(v, dict) else None

    # 정상성 — profiler ADF+KPSS 4-case 우선 (방법론 2-3 교차검정)
    stat = p.get("stationarity") or {}
    stationary = stat.get("is_stationary") if isinstance(stat, dict) else None
    consensus = stat.get("consensus") if isinstance(stat, dict) else None

    carry: dict[str, Any] = {
        # 2-1 레짐/이벤트
        "changepoints": _g("changepoints"),
        "outlier_recommend": _g("outlier_kind", "recommend"),
        # 2-2 가법/승법
        "is_multiplicative": _g("is_multiplicative", "is_multiplicative"),
        # 2-1 이분산
        "heteroscedastic": _g("heteroscedasticity", "is_heteroscedastic"),
        # 2-5 CCF + 누수
        "ccf_top_lags": _g("ccf_leakage", "ccf_top_lags"),
        "leakage_suspect_cols": _g("ccf_leakage", "leakage_suspect_cols"),
        # 0단계 성격
        "is_multivariate": _g("ccf_leakage", "is_multivariate"),
        "target_kind": _g("target_kind", "target_kind"),
        # 2-3 정상성 (교차검정)
        "stationarity_consensus": consensus,
    }
    if stationary is not None:
        carry["stationary"] = bool(stationary)
    return {k: v for k, v in carry.items() if v is not None}


def _exog_columns(state: Any, df: Any, target: str) -> list[str]:
    """exog 컬럼 — category_extras 우선, 없으면 수치형 중 target·date 제외 추론."""
    try:
        cols = (getattr(state, "category_extras", None) or {}).get("timeseries", {}).get("exog_columns")
        if cols:
            return [c for c in cols if c in df.columns]
    except (TypeError, AttributeError):
        pass
    import pandas as pd  # noqa: WPS433

    exog: list[str] = []
    for c in df.columns:
        if c == target:
            continue
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            continue
        if pd.api.types.is_numeric_dtype(df[c]):
            exog.append(c)
    return exog[:5]  # 차트 비용 상한


# ════════════════════════════════════════════════════════════════
# 신규 차트 헬퍼 (각 독립 try/except — 실패 시 None 반환, 전체 안 죽임)
# ════════════════════════════════════════════════════════════════
def _chart_pacf(plt: Any, y: Any, target: str, job_id: str, save: Any) -> str | None:
    """PACF 차트 (방법론 2-4 — 직접 영향 시차)."""
    try:
        from statsmodels.tsa.stattools import pacf  # noqa: WPS433

        n = len(y)
        if n < MIN_ROWS_FOR_ACF or float(y.var()) <= 0:
            return None
        pacf_vals = pacf(y, nlags=min(40, n // 2 - 1))
        fig, ax = plt.subplots(figsize=(10, 3))
        ax.bar(range(len(pacf_vals)), pacf_vals)
        ax.axhline(0, color="black", linewidth=0.5)
        ax.set_title(f"PACF — {target}")
        return save(fig, kind="timeseries/pacf", job_id=job_id)
    except Exception:
        return None


def _chart_rolling_std(plt: Any, y: Any, target: str, period: int, job_id: str, save: Any) -> str | None:
    """rolling std 시간 플롯 (방법론 2-1 — 분산의 시간 변화 = 이분산)."""
    try:
        n = len(y)
        if n < MIN_ROWS_FOR_ACF:
            return None
        w = max(5, period if period and period >= 2 else 7)
        rstd = y.rolling(w, min_periods=max(2, w // 2)).std()
        if rstd.notna().sum() < 2:
            return None
        fig, ax = plt.subplots(figsize=(10, 3))
        rstd.plot(ax=ax)
        ax.set_title(f"Rolling std (w={w}) — 이분산 진단 — {target}")
        ax.set_ylabel("std")
        return save(fig, kind="timeseries/rolling_std", job_id=job_id)
    except Exception:
        return None


def _chart_changepoints(plt: Any, y: Any, target: str, cp_indices: list[int], job_id: str, save: Any) -> str | None:
    """line plot + changepoint/이벤트 시점 수직선 (방법론 2-1 — 레짐 변화·이벤트)."""
    try:
        if not cp_indices:
            return None
        fig, ax = plt.subplots(figsize=(10, 3))
        y.reset_index(drop=True).plot(ax=ax, color="steelblue", linewidth=1)
        marked = 0
        for idx in cp_indices[:MAX_CHANGEPOINT_MARKS]:
            if isinstance(idx, (int, float)) and 0 <= idx < len(y):
                ax.axvline(int(idx), color="red", linestyle="--", alpha=0.6, linewidth=0.8)
                marked += 1
        if marked == 0:
            plt.close(fig)
            return None
        ax.set_title(f"Regime/event changepoints ({marked}) — {target}")
        return save(fig, kind="timeseries/changepoints", job_id=job_id)
    except Exception:
        return None


def _chart_ccf(plt: Any, df: Any, target: str, exog_cols: list[str], job_id: str, save: Any) -> str | None:
    """CCF 차트 (방법론 2-5 — 시차상관, 차분 후 허위상관 방지). exog 있을 때만."""
    try:
        import numpy as np  # noqa: WPS433
        import pandas as pd  # noqa: WPS433

        if not exog_cols:
            return None
        t = pd.to_numeric(df[target], errors="coerce").diff()  # 차분 (허위상관 방지)
        max_lag = 14
        fig, ax = plt.subplots(figsize=(10, 3))
        plotted = 0
        for col in exog_cols[:3]:  # 최대 3개 중첩
            ex = pd.to_numeric(df[col], errors="coerce").diff()
            corrs = []
            for lag in range(0, max_lag + 1):
                pair = pd.concat([t, ex.shift(lag)], axis=1).dropna()
                if len(pair) < 3:
                    corrs.append(0.0)
                    continue
                c = float(pair.iloc[:, 0].corr(pair.iloc[:, 1]))
                corrs.append(0.0 if np.isnan(c) else c)
            ax.plot(range(max_lag + 1), corrs, marker="o", markersize=3, label=col)
            plotted += 1
        if plotted == 0:
            plt.close(fig)
            return None
        ax.axhline(0, color="black", linewidth=0.5)
        ax.set_title(f"CCF (차분 후) — {target} vs exog")
        ax.set_xlabel("lag")
        ax.legend(fontsize=8)
        return save(fig, kind="timeseries/ccf", job_id=job_id)
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════
# §A. 입력 검증 + 차트 진입점
# ════════════════════════════════════════════════════════════════
def _chart_distribution(plt: Any, y: Any, target: str, job_id: str, save: Any) -> str | None:
    """타깃 분포 히스토그램 + 정규성(왜도/첨도) 진단 — 변환 필요성 판단 신호 (P2-2)."""
    try:
        s = y.dropna().astype(float)
        if len(s) < 8:
            return None
        skew = float(s.skew())
        kurt = float(s.kurtosis())
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.hist(s.values, bins=min(40, max(10, len(s) // 5)), color="#3b82f6", alpha=0.85)
        ax.axvline(float(s.mean()), color="#dc2626", lw=1.5, label=f"mean {s.mean():.3g}")
        ax.axvline(float(s.median()), color="#16a34a", lw=1.5, ls="--", label=f"median {s.median():.3g}")
        verdict = "near-normal" if abs(skew) < 0.5 else ("right-skewed (log?)" if skew > 0 else "left-skewed")
        ax.set_title(f"{target} distribution — skew {skew:.2f}, kurt {kurt:.2f} ({verdict})")
        ax.legend(fontsize=8)
        fig.tight_layout()
        return save(fig, kind="timeseries/distribution", job_id=job_id)
    except Exception:
        return None


def charts(df: Any, state: Any) -> list[str]:
    """4+ chart 생성 + MinIO 업로드 + 경로 list 반환.

    A-1 target 가드 / A-2 n_rows 가드 → ValueError (dispatcher 가 RB 처리).
    각 차트는 try/except 로 독립 — 한 차트 실패가 전체로 번지지 않음.
    G-1 모든 차트 실패 시 RuntimeError (RB-3).
    """
    import matplotlib  # noqa: WPS433

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: WPS433

    from agents.handlers.common.shared import save_chart_to_minio

    paths: list[str] = []
    target = getattr(state, "target_column", None)
    job_id = getattr(state, "job_id", "unknown")

    # ── A-1 : target 가드 ──
    if not target or target not in df.columns:
        raise ValueError("target_column missing — preprocessor 검증 필요")  # → RB-1

    # ── A-2 : n_rows 가드 ──
    if len(df) < MIN_ROWS_FOR_EDA:
        raise ValueError("n_rows < 10 — EDA 의미 부족")  # → RB-2

    profile = getattr(state, "data_profile", None) or {}
    freq = profile.get("freq")
    eda_in = _eda_summary_dict(state)
    # ★ profiler 진단 승계 (재계산 X)
    carry = _carry_from_profile(profile)

    # ── §B : Chart 0 — missing 막대 ──
    try:
        miss = df.isnull().mean().sort_values(ascending=False).head(MISSING_TOP_K)
        if not miss.empty and miss.sum() > 0:
            fig, ax = plt.subplots(figsize=(8, 4))
            miss.plot(kind="barh", ax=ax)
            ax.set_title("Missing rate (top 20) — timeseries")
            paths.append(save_chart_to_minio(fig, kind="timeseries/missing", job_id=job_id))
    except Exception:
        pass  # 인라인 skip 안전

    # ── §C : Chart 1 — line plot ──
    if target and target in df.columns:
        try:
            fig, ax = plt.subplots(figsize=(10, 3))
            df[target].plot(ax=ax)
            ax.set_title(f"{target} over time")
            paths.append(save_chart_to_minio(fig, kind="timeseries/line", job_id=job_id))
        except Exception:
            pass

    # ── §D : Chart 2 — ACF + seasonal_period 추정 ──
    acf_peaks: list[int] = []
    _acf_ok = False
    try:
        from scipy.signal import find_peaks  # noqa: WPS433
        from statsmodels.tsa.stattools import acf  # noqa: WPS433

        _acf_ok = True
    except ImportError:
        _acf_ok = False  # → D-2b skip (CI 최소 deps)

    if _acf_ok:
        try:
            y = df[target].dropna()
            if len(y) >= MIN_ROWS_FOR_ACF and y.var() > 0:  # 분산 0 가드
                acf_vals = acf(y, nlags=min(40, len(y) // 2))
                peaks, _ = find_peaks(acf_vals, height=ACF_PEAK_HEIGHT)
                acf_peaks = peaks.tolist()

                fig, ax = plt.subplots(figsize=(10, 3))
                ax.bar(range(len(acf_vals)), acf_vals)
                ax.axhline(0, color="black", linewidth=0.5)
                ax.set_title(f"ACF — {target}")
                paths.append(save_chart_to_minio(fig, kind="timeseries/acf", job_id=job_id))
        except Exception:
            pass

    # ── §D2 : Chart 2b — PACF (신규, 방법론 2-4) ──
    try:
        y_pacf = df[target].dropna()
        p_path = _chart_pacf(plt, y_pacf, target, job_id, save_chart_to_minio)
        if p_path:
            paths.append(p_path)
    except Exception:
        pass

    # ── §E : Chart 3 — STL ──
    s = _infer_seasonal_period(eda_in, freq, acf_peaks, len(df))
    eda_extras: dict[str, Any] = {}
    if s == 0:
        skip_reason: Any = "no_period"
    elif len(df) < 2 * s:
        skip_reason = "too_short"
    else:
        skip_reason = None

    if skip_reason is None:
        try:
            from statsmodels.tsa.seasonal import seasonal_decompose  # noqa: WPS433
            from statsmodels.tsa.stattools import adfuller  # noqa: WPS433

            y = df[target].dropna()
            if len(y) < 5:
                skip_reason = "NaN_dominant"
            else:
                res = seasonal_decompose(y, period=s, model="additive")

                fig, axes = plt.subplots(4, 1, figsize=(10, 8), sharex=True)
                res.observed.plot(ax=axes[0], title="Observed")
                res.trend.plot(ax=axes[1], title="Trend")
                res.seasonal.plot(ax=axes[2], title="Seasonal")
                res.resid.plot(ax=axes[3], title="Residual")
                paths.append(save_chart_to_minio(fig, kind="timeseries/stl", job_id=job_id))

                # eda_summary 갱신 (부수효과) — profiler 정상성 없을 때 fallback
                adf_p = adfuller(y)[1]
                eda_extras = {
                    "stationary": bool(adf_p <= 0.05),
                    "residual_std": float(res.resid.dropna().std()),
                    "total_std": float(y.std()),
                }
        except Exception:
            skip_reason = "fit_error"
            eda_extras = {}

    # ── §F : Chart 4 — seasonality heatmap (year × month) ──
    try:
        import pandas as pd  # noqa: WPS433

        if isinstance(df.index, pd.DatetimeIndex):
            try:
                import seaborn as sns  # noqa: WPS433

                tmp = df[[target]].copy()
                tmp["_year"] = tmp.index.year
                tmp["_month"] = tmp.index.month
                tmp = tmp.dropna(subset=["_year", "_month"])  # NaT 제거

                pivot = tmp.groupby(["_year", "_month"])[target].mean().unstack()
                fig, ax = plt.subplots(figsize=(10, 6))
                sns.heatmap(pivot, annot=True, cmap="YlGnBu", ax=ax, fmt=".1f")
                ax.set_title(f"Seasonality heatmap (year × month) — {target}")
                paths.append(save_chart_to_minio(fig, kind="timeseries/seasonality_heatmap", job_id=job_id))
            except Exception:
                pass  # seaborn 미설치 / pivot 실패 → skip
    except Exception:
        pass

    # ── §F2 : Chart 5 — rolling std (이분산, 신규 2-1) ──
    try:
        y_rs = df[target].dropna().reset_index(drop=True)
        rs_path = _chart_rolling_std(plt, y_rs, target, s, job_id, save_chart_to_minio)
        if rs_path:
            paths.append(rs_path)
    except Exception:
        pass

    # ── §F3 : Chart 6 — 레짐/이벤트 오버레이 (신규 2-1) ──
    try:
        cp_detail = profile.get("changepoints_detail") or {}
        cp_indices = cp_detail.get("indices") if isinstance(cp_detail, dict) else None
        if cp_indices:
            y_cp = df[target].dropna()
            cp_path = _chart_changepoints(plt, y_cp, target, cp_indices, job_id, save_chart_to_minio)
            if cp_path:
                paths.append(cp_path)
    except Exception:
        pass

    # ── §F4 : Chart 7 — CCF (시차상관, 신규 2-5) — exog 있을 때만 ──
    try:
        exog_cols = _exog_columns(state, df, target)
        if exog_cols:
            ccf_path = _chart_ccf(plt, df, target, exog_cols, job_id, save_chart_to_minio)
            if ccf_path:
                paths.append(ccf_path)
    except Exception:
        pass

    # ── §F5 : Chart 8 — 타깃 분포/정규성 진단 (P2-2, 2026-06-16) ──
    try:
        d_path = _chart_distribution(plt, df[target], target, job_id, save_chart_to_minio)
        if d_path:
            paths.append(d_path)
    except Exception:
        pass

    # ── §G : paths 가드 + eda_summary 반환 정보 부착 ──
    if not paths:
        raise RuntimeError("all_charts_failed — 데이터 비정상 의심")  # → RB-3

    # dispatcher 가 state.with_update(eda_summary=...) 하도록 메타를 함수 속성에
    # 동봉 (반환은 paths list[str] 계약 유지).
    # 병합 순서: 자체 계산(eda_extras) → profiler 승계(carry) 가 우선
    # (profiler 의 ADF+KPSS 4-case 가 자체 ADF 단독보다 정확하므로 carry 가 덮어씀).
    try:
        summary = {
            "charts": list(paths),
            "seasonal_period": s,
            "acf_peaks": acf_peaks,
        }
        summary.update(eda_extras)  # stationary(자체 ADF) / residual_std / total_std
        summary.update(carry)  # ★ profiler 진단 승계 — stationary 등은 carry 가 우선
        charts.last_eda_summary = summary  # type: ignore[attr-defined]
    except Exception:
        pass

    return paths
