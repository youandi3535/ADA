"""agents.handlers.anomaly.output_extras — 이상탐지 산출물 추가 자산 (NY 담당, Day 9 v2).

OUT-01(PPT) · OUT-02(PDF) carrier 가 임베드할 anomaly 전용 표·차트·텍스트.

진입함수 (dispatcher 자동 등록, "assets" capability):
  - assets(state, ctx=None) -> dict   {charts, tables, text_blocks}

★ 시그니처 양쪽 호환 (E-1):
  - outputs/base.py::_call_extras → fn(state, ctx)        [2-arg]
  - agents/report_composer.py     → assets_handler(state) [1-arg]
  → ctx 기본값 None 으로 둘 다 수용.

반환 키 (E-3, OUTPUT_EXTRAS_KEYS):
  - charts: list[str]       MinIO 차트 경로 (Day 7 평가 곡선, eda_charts 중복 제거)
  - tables: list[dict]      {title, columns, rows} — carrier table 렌더 규격
  - text_blocks: list[str]  Top-N 사례 σ 요약 (state.insights 와 비중복)

DoD (TEAM_10DAY_SCHEDULE): top-N 이상치 테이블 + 분포 비교 + 시간축 이상 시점.
★ B-1: state 에 df 없음 → 신규 데이터 차트 생성 불가 → 기존 경로 재사용.
Day 8 insight 헬퍼 재사용 (F-1).
"""

from __future__ import annotations

from typing import Any

# ── 모듈 상수 ─────────────────────────────────────────────────────
TOP_N_TABLE = 5  # ★ A-1 — Day 8 A-1 (N=5) 일관
TOP_FEATURES_K = 3  # Day 8 top3 피처 일관
TABLE_TITLE = "Top-5 이상치 사례"
TABLE_COLUMNS = ["순위", "행 인덱스", "이상점수", "주요 피처", "편차(σ)"]

# Day 7 평가 결과에서 끌어올 차트 경로 키 후보 (E-5 — 비중복 anomaly 차트)
EVAL_CHART_KEYS = ("threshold_curve_path", "precision_recall_curve", "pr_curve_path")


# ── 헬퍼 ──────────────────────────────────────────────────────────


def _extras_evaluation(state: Any) -> dict[str, Any]:
    """★ X-3/X-6: 평가 결과(per-row + metrics)는 state.eval_result (top-level) 안전 조회."""
    er = getattr(state, "eval_result", None) or {}
    if er:
        return er
    ce = (getattr(state, "category_extras", {}) or {}).get("anomaly", {})
    return {**(ce.get("pipeline", {}) or {}), **(ce.get("evaluation", {}) or {})}


def _build_top_n_table(state: Any, n: int = TOP_N_TABLE) -> dict[str, Any] | None:
    """Top-N 이상치 표 (carrier 규격 {title, columns, rows}). 없으면 None."""
    from agents.handlers.anomaly.insight import (
        _compute_anomaly_sigma_from_df,
        _extract_top_n_anomalies,
        _get_top_features,
    )

    top_anomalies = _extract_top_n_anomalies(state, n=n)
    if not top_anomalies:
        return None

    top_features = _get_top_features(state, k=TOP_FEATURES_K)
    primary = top_features[0] if top_features else "-"

    rows: list[dict[str, Any]] = []
    for rank, case in enumerate(top_anomalies, start=1):
        idx = case["idx"]
        sigma = _compute_anomaly_sigma_from_df(state, idx, primary) if top_features else 0.0
        rows.append(
            {
                "순위": rank,
                "행 인덱스": idx,
                "이상점수": round(float(case["score"]), 4),
                "주요 피처": primary,
                "편차(σ)": f"{sigma:.1f}σ",
            }
        )

    return {"title": TABLE_TITLE, "columns": list(TABLE_COLUMNS), "rows": rows}


def _collect_anomaly_charts(state: Any) -> list[str]:
    """anomaly 전용 차트 경로 — Day 7 평가 곡선 등. eda_charts 중복 제거 (E-5).

    ★ B-1: output_extras 는 df 미수신 → 신규 차트 생성 불가. 기존 경로만 재사용.
    """
    eval_result = _extras_evaluation(state)
    already = set(getattr(state, "eda_charts", []) or [])

    charts: list[str] = []
    for key in EVAL_CHART_KEYS:
        path = eval_result.get(key)
        if isinstance(path, str) and path and path not in already and path not in charts:
            charts.append(path)
    return charts


def _build_text_blocks(state: Any) -> list[str]:
    """carrier 임베드용 텍스트 — Top-N 사례 σ 요약 1 블록 (state.insights 비중복)."""
    from agents.handlers.anomaly.insight import (
        _compute_anomaly_sigma_from_df,
        _extract_top_n_anomalies,
        _format_anomaly_case,
        _get_top_features,
    )

    top_anomalies = _extract_top_n_anomalies(state, n=TOP_N_TABLE)
    top_features = _get_top_features(state, k=TOP_FEATURES_K)
    if not top_anomalies or not top_features:
        return []

    primary = top_features[0]
    lines = [
        _format_anomaly_case(c["idx"], primary, _compute_anomaly_sigma_from_df(state, c["idx"], primary))
        for c in top_anomalies
    ]
    return ["주요 이상치 사례 요약: " + "; ".join(lines) + "."]


# ── 진입점 (dispatcher 자동 등록, "assets") ────────────────────────


def assets(state: Any, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """OUT-01/OUT-02 carrier 추가 자산 (charts·tables·text_blocks).

    ★ E-1 — ctx 기본값 None: base._call_extras(state, ctx)[2-arg] +
       report_composer assets_handler(state)[1-arg] 둘 다 호환.
    """
    _ = ctx  # 현재 carrier(output_code) 무관 동일 자산

    tables: list[dict[str, Any]] = []
    table = _build_top_n_table(state)
    if table is not None:
        tables.append(table)

    return {
        "charts": _collect_anomaly_charts(state),
        "tables": tables,
        "text_blocks": _build_text_blocks(state),
    }
