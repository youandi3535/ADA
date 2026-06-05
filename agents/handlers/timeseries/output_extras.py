"""agents.handlers.timeseries.output_extras — 시계열 산출물 추가 자산 (CS 담당, cs-day9 v3).

OUT-01(PPT) / OUT-02(PDF) / OUT-04(HTML) carrier 가 임베드할 시계열 전용 차트·표·텍스트.

진입함수 (dispatcher 자동 등록):
  - build(state, ctx=None) -> dict   {charts, tables, text_blocks}  ★ base.py _call_extras 가 우선 호출
  - assets(state, ctx=None) -> dict  build 호환 래퍼 (구 인터페이스 유지 + NY/jh 표준 함수명)

DoD: charts 에 forecast_chart + decomposition 둘 다 포함 (OUT-04 임베드).

v3 보완 사항 (cs-day9 디벨롭):
  CG-1  text_blocks list[str] 표준화 — NY/jh 와 동일, ppt.py carrier 호환
  CH-1  신뢰도 한계 배지 — eval_result 의 증상/누수/fold 안정성을 1줄로 (text_blocks[0])
  CH-2  forecast_chart 메타 풍부화 — 차트 제목·표 제목에 horizon/forecast_kind 명시
  CH-3  fold_diagnostics 표 — eval_result.fold_diagnostics.available 시 tables 추가
  CH-4  forecast_chart 신뢰도 오버레이 — 증상 C/D/E 시 PI 색·라벨 + 주의 텍스트

5 단 forecast (B) + 3 단 decomposition (C):
  B-1 PI 확인 / B-2 y 재로드 / B-3 모델별 PI 재추출 / B-4 matplotlib / B-5 MinIO
  C-1 STL 경로 확인 / C-2 재사용 vs 신규 / C-3 통합

핵심 설계 원칙:
  - 인라인 안전 우선 — 모든 차트 try/except (matplotlib/MinIO 실패 → path=None)
  - PI 3 단 분기 — 저장 활용 (B-1a) / 모델 객체 재추출 (B-3a) / point only (B-3b)
  - STL 재사용 우선 — cs-day3 결과 활용 · 신규는 fallback
  - insights 재사용 (cs-day8) — text_blocks 에 그대로
  - 행동권고 규칙 기반 — MASE/improvement 기반 (LLM 호출 없음)
  - OUTPUT_EXTRAS_KEYS 3 키만 반환 (category_label/color 은 base.py CATEGORY_THEME)
  - 롤백 1 개만 — best_model 부재 시 빈 dict
"""

from __future__ import annotations

import logging
from typing import Any

import matplotlib  # noqa: WPS433

matplotlib.use("Agg")  # GUI 없는 환경(서버/Docker) 대비 — pyplot import 전에 1회만

logger = logging.getLogger(__name__)

# E-1 freq → 한국어 단위
FREQ_UNIT_KO = {"D": "일", "W": "주", "M": "개월", "MS": "개월", "H": "시간"}
MAX_FORECAST_ROWS = 20  # E-1 표 최대 행
SEASONAL_FALLBACK = 7  # C-2b default period

# CH-4 — 신뢰도 제한 트리거 증상 (헌장 7단계 증상 코드)
LOW_TRUST_SYMPTOMS = {"C", "D", "E"}


# ════════════════════════════════════════════════════════════════
# 모델별 PI 재추출 (cs-day6 §F-Extension F-ext-2.2 와 일관)
# ════════════════════════════════════════════════════════════════
def _extract_pi_from_model(model: Any, n_steps: int, alpha: float = 0.05):
    """모델별 95% PI 추출 — SARIMA / Prophet / NeuralForecast 분기."""
    import numpy as np  # noqa: WPS433

    if hasattr(model, "get_forecast"):  # SARIMA/SARIMAX
        fc = model.get_forecast(steps=n_steps)
        ci = fc.conf_int(alpha=alpha)
        lower = np.asarray(ci.iloc[:, 0] if hasattr(ci, "iloc") else ci[:, 0])
        upper = np.asarray(ci.iloc[:, 1] if hasattr(ci, "iloc") else ci[:, 1])
        return lower, upper
    if hasattr(model, "predict") and hasattr(model, "make_future_dataframe"):  # Prophet
        future = model.make_future_dataframe(periods=n_steps)
        forecast = model.predict(future)
        return forecast["yhat_lower"].values[-n_steps:], forecast["yhat_upper"].values[-n_steps:]
    if hasattr(model, "predict_intervals"):  # NeuralForecast
        pi_df = model.predict_intervals(level=[95])
        return pi_df["lower_95"].values[:n_steps], pi_df["upper_95"].values[:n_steps]
    raise ValueError("PI 추출 불가 모델")


# ════════════════════════════════════════════════════════════════
# §D-0. 신뢰도 한계 배지 (CH-1 ★ 인수인계 9번 핵심)
# ════════════════════════════════════════════════════════════════
def _build_reliability_badge(eval_result: dict) -> str | None:
    """evaluator 의 증상/누수/fold 진단을 1 줄 배지로.

    헌장 누수 1-6 사후 진단 + 롤백 원칙 5 (fold 분산) 의 사용자 노출 표면.
    증상 normal 이고 누수 신호 없고 fold 안정이면 배지 미생성 (None).
    """
    if not isinstance(eval_result, dict) or not eval_result:
        return None

    parts: list[str] = []

    # (1) 증상 분류
    symptom_obj = eval_result.get("symptom_classification") or {}
    symptom = symptom_obj.get("symptom")
    label = symptom_obj.get("label")
    if symptom and symptom not in ("normal", None):
        parts.append(f"증상 {symptom} ({label})")

    # (2) 누수 의심 신호 개수
    leakage = eval_result.get("leakage_suspect_signals") or []
    if leakage:
        kinds = [s.get("kind", "?") for s in leakage if isinstance(s, dict)]
        parts.append(f"누수 신호 {len(leakage)}건 ({', '.join(kinds[:3])})")

    # (3) fold 안정성
    fold_diag = eval_result.get("fold_diagnostics") or {}
    if fold_diag.get("available"):
        stability = fold_diag.get("stability")
        if stability in ("unstable", "very_unstable"):
            parts.append(f"fold {stability} (cv={fold_diag.get('cv')})")

    # (4) G15 잔차 자기상관 — 모델이 신호 못 잡음
    residual_diag = eval_result.get("residual_diagnostics") or {}
    if residual_diag.get("kind") == "autocorrelated":
        lbp = residual_diag.get("ljung_box_p")
        parts.append(f"잔차 자기상관 (Ljung-Box p={lbp})")

    # (5) G13 DM 검정 — naïve 가 모델보다 통계적으로 우수
    dm = eval_result.get("dm_test") or {}
    if dm.get("verdict") == "naive_wins":
        parts.append(f"DM 검정 naïve 우수 (p={dm.get('p_value')})")

    if not parts:
        return None

    return "⚠ 신뢰도 한계 — " + " · ".join(parts) + ". 보고서 해석 시 주의 권장."


# ════════════════════════════════════════════════════════════════
# §D-2. 행동권고 (규칙 기반 — LLM 호출 없음)
# ════════════════════════════════════════════════════════════════
def _build_recommendations(metrics: dict, freq: str, eda: dict) -> str:
    """규칙 기반 행동권고 — MASE / improvement / seasonal_period 기반."""
    lines: list[str] = []

    mase = metrics.get("MASE")
    if mase is not None:
        if mase < 0.5:
            lines.append("모델 성능 매우 우수 (MASE<0.5) — 운영 안정 단계, 재고는 정상 수준 유지 권장.")
        elif mase < 1.0:
            lines.append(f"모델 성능 양호 (MASE={mase:.2f}) — 주간 단위 모니터링 + 분기별 검토 권장.")
        else:
            lines.append(f"모델 성능 주의 (MASE={mase:.2f} >= 1.0) — 재학습 권장 + 입력 데이터 점검.")

    improvement = metrics.get("rmse_improvement_vs_naive")
    if improvement is not None and improvement < 0:
        lines.append(f"naïve 대비 {improvement:+.1%} 열위 — 다른 모델 후보 검토 권장.")

    s = eda.get("seasonal_period")
    if s and s in (7, 12, 30, 365):
        unit_map = {7: "주간", 12: "월간", 30: "월간 (일별)", 365: "연간"}
        lines.append(f"{unit_map[s]} 계절성 명확 — 해당 주기 단위 의사결정에 우선 활용.")

    return "\n".join(lines) if lines else ""


def _eda_dict(state: Any) -> dict:
    raw = getattr(state, "eda_summary", None)
    return raw if isinstance(raw, dict) else {}


def _ts_extras(state: Any) -> dict:
    """state.category_extras['timeseries'] 안전 추출."""
    ce = getattr(state, "category_extras", None) or {}
    return ce.get("timeseries", {}) or {}


# ════════════════════════════════════════════════════════════════
# §A~§F. build — 메인 진입점
# ════════════════════════════════════════════════════════════════
def build(state: Any, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """OUT-01/02/04 carrier 추가 자산 (charts·tables·text_blocks). 설계도 cs-day9 §A~§F."""
    # ── A-1 : best_model 가드 ──
    bm = getattr(state, "best_model", None) or {}
    if not bm or not isinstance(bm, dict):
        return {}  # → RB-1 빈 dict 응급 (carrier 가 처리)

    # ── A-1b (D4, 2026-06-05) : 상수 시계열 graceful 안내 (cs-day10 단계 9 ❌) ──
    # _ConstantSeriesModel (pipeline D3) 이 학습되면 best_model.model_obj 가 _ada_constant_series 보유.
    # 이 경우 forecast/decomposition 차트는 의미 없고 "분석 불가" 명시가 정직한 보고.
    _model_obj = bm.get("model_obj")
    if _model_obj is not None and getattr(_model_obj, "_ada_constant_series", False):
        return {
            "charts": [],
            "tables": [
                {
                    "title": "상수 시계열 진단",
                    "columns": ["항목", "값"],
                    "rows": [
                        ["타깃 분산", "0 (모든 시점 값 동일)"],
                        ["모델 예측", f"{getattr(_model_obj, 'const_value', 0):.4f} (상수)"],
                        ["판정", "예측 의미 없음 — 운영 데이터 점검 권장"],
                    ],
                }
            ],
            "text_blocks": [
                "⚠ 분석 불가 — 입력 시계열의 분산이 0 입니다 (모든 시점이 동일 값). "
                "예측 모델의 의미 있는 학습이 불가능하며, 데이터 수집·전처리 과정에서 "
                "누락·고정값 주입·센서 오류 등이 없었는지 점검을 권장합니다."
            ],
        }

    # ── A-2 : eda_summary 가드 ──
    eda = _eda_dict(state)

    # ── A-3 : ctx 정규화 + 변수 추출 ──
    ctx = ctx or {}
    figsize = ctx.get("figsize", (12, 5))
    dpi = ctx.get("dpi", 100)
    metrics = bm.get("metrics") or {}
    ts_ext = _ts_extras(state)
    freq = ts_ext.get("freq", "D")
    forecast_kind = ts_ext.get("forecast_kind")  # CH-2: point / interval / quantile
    variate = ts_ext.get("variate")  # CH-2: univariate / multivariate
    horizon_hint = ts_ext.get("horizon_hint")
    model_name = bm.get("model_name", "Unknown")

    # ── A-4 : eval_result 추출 (CH-1·CH-3·CH-4) ──
    eval_result = getattr(state, "eval_result", None) or {}
    if not isinstance(eval_result, dict):
        eval_result = {}
    symptom_obj = eval_result.get("symptom_classification") or {}
    symptom_code = symptom_obj.get("symptom")
    leakage_signals = eval_result.get("leakage_suspect_signals") or []
    low_trust = bool(leakage_signals) or symptom_code in LOW_TRUST_SYMPTOMS

    charts: list[str] = []
    tables: list[dict] = []
    text_blocks: list[str] = []  # CG-1 — list[str] 표준화 (NY/jh 호환)

    import numpy as np  # noqa: WPS433

    # ════════════════════════════════════════════════════════════
    # §B. forecast_chart 5 단 (★ DoD 1)
    # ════════════════════════════════════════════════════════════
    # ── B-1 : PI 정보 확인 ──
    lower = metrics.get("pi_lower")
    upper = metrics.get("pi_upper")
    if isinstance(lower, list) and isinstance(upper, list):
        lower = np.asarray(lower)  # B-1a
        upper = np.asarray(upper)
    else:
        lower = upper = None  # B-1b

    # ── B-2 : y_train / y_val / y_pred 재로드 ──
    y_pred = metrics.get("y_pred_val")
    y_train = y_val = None
    forecast_path = None

    if y_pred is None:
        try:
            from agents.handlers.common.shared import load_dataframe_from_state
            from agents.training_executor import _split_xy

            df = load_dataframe_from_state(state, prefer_processed=True)
            X, y = _split_xy(df, getattr(state, "target_column", None))
            split = int(len(y) * 0.8)
            y_train, y_val = y[:split], y[split:]
            model_obj = bm.get("model_obj")
            if model_obj is not None:
                from pipelines.factory import PipelineFactory

                pipe = PipelineFactory.create(state.category)
                y_pred = pipe.predict(model_obj, X[split:])
        except Exception as e:
            logger.warning("y_reload_failed: %s", e)
    else:
        y_val = metrics.get("y_val_actual")
        y_train = metrics.get("y_train_tail")

    # ── B-3 : 모델 객체로 PI 재추출 ──
    if lower is None and bm.get("model_obj") is not None and y_val is not None:
        try:
            lower, upper = _extract_pi_from_model(bm["model_obj"], n_steps=len(y_val))  # B-3a
        except Exception:
            lower = upper = None  # B-3b

    # ── B-4 : matplotlib 차트 ──
    if y_pred is not None and y_val is not None:
        try:
            import matplotlib.pyplot as plt  # noqa: WPS433
            import pandas as pd  # noqa: WPS433

            y_pred_arr = np.asarray(y_pred).flatten()
            y_val_arr = np.asarray(y_val).flatten()

            fig, ax = plt.subplots(figsize=figsize, dpi=dpi)

            n_train = len(y_train) if y_train is not None else 0
            if y_train is not None:
                idx_train = pd.RangeIndex(start=0, stop=n_train)
                ax.plot(idx_train, np.asarray(y_train).flatten(), color="black", label="과거", linewidth=1)

            idx_val = pd.RangeIndex(start=n_train, stop=n_train + len(y_val_arr))
            ax.plot(idx_val, y_val_arr[: len(idx_val)], color="blue", label="실제 (val)", linewidth=1.5)
            ax.plot(idx_val[: len(y_pred_arr)], y_pred_arr, color="orange", label="예측", linewidth=1.5)

            # CH-4 — 95% PI 음영 (저신뢰 시 색·라벨 변경)
            if lower is not None and upper is not None:
                L = min(len(lower), len(upper), len(idx_val))
                pi_color = "red" if low_trust else "orange"
                pi_label = "95% PI (신뢰도 제한)" if low_trust else "95% PI"
                ax.fill_between(idx_val[:L], lower[:L], upper[:L], alpha=0.2, color=pi_color, label=pi_label)

            # CH-2 — 제목에 forecast_kind / horizon 명시
            horizon_n = horizon_hint or len(y_pred_arr)
            kind_label = forecast_kind or "point"
            variate_label = variate or "univariate"
            title = f"Forecast ({kind_label}, {variate_label}) — {model_name} (h={horizon_n})"
            ax.set_title(title)

            # CH-4 — 저신뢰 주의 오버레이
            if low_trust:
                try:
                    ax.text(
                        0.99,
                        0.97,
                        "⚠ 누수/증상 검토 권장",
                        transform=ax.transAxes,
                        ha="right",
                        va="top",
                        fontsize=10,
                        color="darkred",
                        bbox={"boxstyle": "round,pad=0.3", "facecolor": "mistyrose", "alpha": 0.8},
                    )
                except Exception:  # noqa: BLE001
                    pass  # 텍스트 실패해도 차트 자체는 살림

            ax.set_xlabel("time")
            ax.set_ylabel(getattr(state, "target_column", None) or "y")
            ax.legend()
            ax.grid(True, alpha=0.3)

            # ── B-5 : MinIO 저장 ──
            from agents.handlers.common.shared import save_chart_to_minio

            forecast_path = save_chart_to_minio(fig, kind="timeseries/forecast", job_id=getattr(state, "job_id", ""))
        except Exception as e:
            logger.warning("forecast_chart_failed: %s", e)
            forecast_path = None  # 인라인 안전

    if forecast_path:
        charts.append(forecast_path)

    # ════════════════════════════════════════════════════════════
    # §C. decomposition 3 단 (★ DoD 2)
    # ════════════════════════════════════════════════════════════
    decomp_path = None
    stl_paths = [c for c in (eda.get("charts") or []) if isinstance(c, str) and "/stl" in c]

    if stl_paths:
        decomp_path = stl_paths[0]  # C-2a 재사용 (간단 + 효율)
    else:
        try:  # C-2b 신규 생성
            import matplotlib.pyplot as plt  # noqa: WPS433
            from statsmodels.tsa.seasonal import seasonal_decompose  # noqa: WPS433

            from agents.handlers.common.shared import load_dataframe_from_state, save_chart_to_minio

            df = load_dataframe_from_state(state, prefer_processed=True)
            y = df[state.target_column].dropna()
            s = eda.get("seasonal_period") or SEASONAL_FALLBACK

            if len(y) >= 2 * s and y.var() > 0:  # 가드
                res = seasonal_decompose(y, period=s, model="additive")

                fig, axes = plt.subplots(4, 1, figsize=(12, 8), sharex=True, dpi=dpi)
                res.observed.plot(ax=axes[0], title="Observed")
                res.trend.plot(ax=axes[1], title="Trend")
                res.seasonal.plot(ax=axes[2], title="Seasonal")
                res.resid.plot(ax=axes[3], title="Residual")
                plt.tight_layout()

                decomp_path = save_chart_to_minio(
                    fig, kind="timeseries/decomposition", job_id=getattr(state, "job_id", "")
                )
        except Exception as e:
            logger.warning("decomp_chart_failed: %s", e)
            decomp_path = None  # 인라인 안전

    # ── C-3 : charts 통합 ──
    if decomp_path:
        charts.append(decomp_path)

    # ════════════════════════════════════════════════════════════
    # §D. text_blocks (CG-1 — list[str] 표준화)
    # ════════════════════════════════════════════════════════════
    # ── D-0 : 신뢰도 한계 배지 (CH-1, 맨 앞 우선순위 1) ──
    badge = _build_reliability_badge(eval_result)
    if badge:
        text_blocks.append(badge)

    # ── D-1 : insights 재사용 (cs-day8) ──
    insights = getattr(state, "insights", None)
    if insights and isinstance(insights, str) and insights.strip():
        text_blocks.append(f"분석 인사이트\n{insights.strip()}")

    # ── D-2 : 행동권고 카드 ──
    recommendations = _build_recommendations(metrics, freq, eda)
    if recommendations:
        text_blocks.append(f"권장 액션\n{recommendations}")

    # ════════════════════════════════════════════════════════════
    # §E. tables
    # ════════════════════════════════════════════════════════════
    # ── E-1 : forecast 값 표 (CH-2 — forecast_kind 명시) ──
    if y_pred is not None:
        y_pred_arr = np.asarray(y_pred).flatten()
        if len(y_pred_arr) > 0:
            unit_ko = FREQ_UNIT_KO.get(freq, "주기")
            horizon = len(y_pred_arr)
            kind_ko = {"point": "점예측", "interval": "구간예측", "quantile": "분위예측"}.get(
                forecast_kind or "point", "예측"
            )
            rows = []
            for i, pred in enumerate(y_pred_arr[: min(MAX_FORECAST_ROWS, horizon)]):
                row = [f"t+{i + 1}", f"{float(pred):.2f}"]
                if lower is not None and i < len(lower):
                    row.extend([f"{float(lower[i]):.2f}", f"{float(upper[i]):.2f}"])
                else:
                    row.extend(["-", "-"])
                rows.append(row)
            tables.append(
                {
                    "title": f"다음 {horizon}{unit_ko} {kind_ko}",
                    "columns": ["시점", "예측값", "하한 (95%)", "상한 (95%)"],
                    "rows": rows,
                }
            )

    # ── E-2 : 모델 성능 카드 ──
    perf_rows = []
    for key, label in [
        ("val_rmse", "RMSE"),
        ("val_mae", "MAE"),
        ("MASE", "MASE"),
        ("sMAPE", "sMAPE (%)"),
        ("rmse_improvement_vs_naive", "개선율 vs naïve"),
    ]:
        v = metrics.get(key)
        if v is not None:
            if key == "rmse_improvement_vs_naive":
                perf_rows.append([label, f"{v:+.1%}"])
            elif key == "sMAPE":
                perf_rows.append([label, f"{v:.1f}"])
            else:
                perf_rows.append([label, f"{v:.3f}"])
    if perf_rows:
        tables.append({"title": "모델 성능 요약", "columns": ["메트릭", "값"], "rows": perf_rows})

    # ── E-3 : fold_diagnostics 표 (CH-3, 가용 시) ──
    fold_diag = eval_result.get("fold_diagnostics") or {}
    if fold_diag.get("available"):
        fold_rows = []
        for label, key in [
            ("Fold 수", "n_folds"),
            ("평균", "mean"),
            ("표준편차", "std"),
            ("변동계수 (cv)", "cv"),
            ("범위 비율", "range_ratio"),
            ("안정성", "stability"),
        ]:
            v = fold_diag.get(key)
            if v is not None:
                fold_rows.append([label, str(v)])
        best_f = fold_diag.get("best_fold") or {}
        worst_f = fold_diag.get("worst_fold") or {}
        if best_f:
            fold_rows.append(["최고 fold", f"#{best_f.get('idx')} (score={best_f.get('score')})"])
        if worst_f:
            fold_rows.append(["최악 fold", f"#{worst_f.get('idx')} (score={worst_f.get('score')})"])
        if fold_rows:
            tables.append(
                {
                    "title": "Fold 안정성 진단 (walk-forward)",
                    "columns": ["지표", "값"],
                    "rows": fold_rows,
                }
            )

    # ── E-4 (G15+G13, 2026-06-05) : 잔차·DM 검정 표 ──
    residual_diag2 = eval_result.get("residual_diagnostics") or {}
    dm_test_obj = eval_result.get("dm_test") or {}
    diag_rows = []
    if residual_diag2.get("kind") and residual_diag2.get("kind") != "unknown":
        diag_rows.append(["잔차 진단", str(residual_diag2.get("kind"))])
        if residual_diag2.get("ljung_box_p") is not None:
            diag_rows.append(["Ljung-Box p", f"{residual_diag2.get('ljung_box_p')}"])
        if residual_diag2.get("mean_pct") is not None:
            diag_rows.append(["잔차 평균 편향", f"{residual_diag2.get('mean_pct'):.1%}"])
    if dm_test_obj.get("available"):
        diag_rows.append(["DM 검정 결과", str(dm_test_obj.get("verdict"))])
        if dm_test_obj.get("p_value") is not None:
            diag_rows.append(["DM p-value", f"{dm_test_obj.get('p_value')}"])
        if dm_test_obj.get("dm_stat") is not None:
            diag_rows.append(["DM 통계량", f"{dm_test_obj.get('dm_stat')}"])
    if diag_rows:
        tables.append({"title": "잔차·통계 비교 검정", "columns": ["지표", "값"], "rows": diag_rows})

    # ════════════════════════════════════════════════════════════
    # §F. 반환 (OUTPUT_EXTRAS_KEYS 3 키)
    # ════════════════════════════════════════════════════════════
    return {
        "charts": charts,
        "tables": tables,
        "text_blocks": text_blocks,
    }


# ════════════════════════════════════════════════════════════════
# assets — build 호환 래퍼 (구 인터페이스 유지 + NY/jh 표준 함수명)
# ════════════════════════════════════════════════════════════════
def assets(state: Any, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """carrier 가 수신하는 추가 자산 — build 위임 (base.py 는 build 우선 호출)."""
    return build(state, ctx)
