"""agents.handlers.timeseries.insight — 시계열 인사이트 (CS 담당, cs-day8 v3 디벨롭).

SYSTEM_PROMPT 수치 2+ 강제 + prompt_payload (horizon·0단계 메타 포함) +
fallback 다단 한국어 조립 + cs-day7 v3 evaluator 신규 4키 활용.

진입함수 (dispatcher 자동 등록):
  - generate(state) -> str          한국어 3~7 문장 (fallback 반환; LLM 은 dispatcher)
  - prompt_payload(state) -> dict   LLM 입력 (HJ BaseAgent._call_llm)
  - fallback(state) -> str          LLM 실패 시 한국어 템플릿

DoD (불변):
  - 한국어 3~5문장 이상 + 정확한 수치 2개 이상 + (있을 때) top features 1개+
  - 응급 안전망 보장 (fallback 자체 실패 시)

cs-day8 v3 디벨롭 (재정독 후 헌장 갭 7건 해소):
  H1 slope 키 버그 수정 — profiler 의 trend["slope_per_obs"] (legacy "slope" 도 fallback)
  H2 0단계 메타 명시 — proposer.g1(state) 직접 호출해서 meta(variate/forecast_kind/
     task_kind/horizon_hint) 추출. HJ-5 (2026-06-05) 이후 chosen_recipe 가 PipelineState
     정식 필드가 됐으나 채우는 곳은 HJ-7 후속 — 정상 채워질 때까지 proposer.g1 직접 호출 fallback 유지
  H3 누수 의심 한계 안내 — eval_result.leakage_suspect_signals 받아 정직한 한계 인정
     ("검증 신호 X 감지 — 운영 적용 전 점검 필요"). cs-day10 "정직한 실패" 원칙
  H4 fold 분산 인용 — eval_result.fold_diagnostics 받아 "fold N개 평균 X (안정성 Y)"
  H5 증상 + 롤백 우선순위 — eval_result.symptom_classification.rollback_priority
  H6 승법·changepoint·이분산 도메인 가이드 — eda_summary carry 활용
  H7 task_kind_hint (분류형) — eval_result.task_kind_hint 한국어 안내

핵심 설계 원칙 (불변):
  - 수치 2+ DoD 강제 — SYSTEM_PROMPT 규칙 3 + fallback 수치 보장 매트릭스
  - direction 한국어 매핑 — None / "none" 구분 (혼합 vs 횡보)
  - freq 폴백 3 단 — 정확 매칭 → prefix → "주기"
  - 수치 우선순위 — improvement > MASE > skip
  - 응급 안전망 — fallback 자체 실패 시 응급 텍스트
  - PII reattach — dispatcher 책임 (우리 fallback 은 LLM 호출 X → PII 무관)
  - R-501 KB 인용 — ModelSelection·Supervisor 책임 (insight 영역 외)
"""

from __future__ import annotations

from typing import Any, Optional

# ── 한국어 표현 매핑 ──────────────────────────────────────────────
DIRECTION_KO: dict[str, str] = {
    "increasing": "상승",
    "decreasing": "하락",
    "none": "횡보",
}

# pd.infer_freq 코드 → 한국어 단위 (정확 매칭 우선, prefix 폴백)
FREQ_UNIT_KO: dict[str, str] = {
    "D": "일",
    "B": "영업일",
    "W": "주",
    "M": "개월",
    "MS": "개월",
    "Q": "분기",
    "QS": "분기",
    "Y": "년",
    "YS": "년",
    "A": "년",
    "H": "시간",
    "T": "분",
    "S": "초",
}

FREQ_HORIZON_FALLBACK = {"D": 7, "W": 4, "M": 12, "MS": 12, "H": 24}

# H2 — 0단계 한국어 매핑
VARIATE_KO = {"univariate": "단변량", "multivariate": "다변량"}
FORECAST_KIND_KO = {"point": "점 예측", "interval": "구간 예측"}
TASK_KIND_KO = {"regression": "회귀형", "classification": "분류형 (이상 시점)"}

# H5 — 증상 코드 → 한국어 라벨 (evaluator.symptom_classification 호환)
SYMPTOM_KO_LABEL = {
    "C": "검증 성능 비현실적 좋음 (누수 의심)",
    "D": "fold 편차 큼",
    "E": "naïve 기준선 못 이김",
    "B": "학습/검증 둘 다 나쁨 (과소적합)",
    "A": "과적합 의심",
    "no_model": "모델 학습 실패",
}

SYSTEM_PROMPT = """당신은 시계열 분석 인사이트 작성자입니다.
다음 데이터를 보고 한국어 3~7문장으로 인사이트를 작성하세요.

규칙:
1. 추세 방향 (상승/하락/횡보) 을 1번째 문장에 명시
2. 계절성/주기 가 있다면 2번째 문장에 언급 (주기 숫자 포함)
3. 정확한 수치 2개 이상 인용 (★ 강화)
   - 예: 변화율 % (slope), naïve 대비 개선율, MASE, 주기 숫자, fold 평균
   - 도메인 예시 : "다음 7일 매출이 평균 12% 증가"
4. 0단계 성격 (단변량/다변량 · 점/구간 예측) 명시 (있을 때)
5. walk-forward 검증 결과 (fold 평균 + 안정성) 인용 (있을 때)
6. 검증 누수 의심 신호가 있으면 정직한 한계 인정 (낙관 톤 X)
7. 마지막 1문장은 행동 권고 + 권장 조치 (롤백 우선순위 인용)
8. 마크다운/리스트/이모지 금지, 순수 한국어 문단만 작성
"""


# ════════════════════════════════════════════════════════════════
# 헬퍼 — state 안전 추출
# ════════════════════════════════════════════════════════════════
def _eda_dict(state: Any) -> dict:
    raw = getattr(state, "eda_summary", None)
    return raw if isinstance(raw, dict) else {}


def _eval_result(state: Any) -> dict:
    raw = getattr(state, "eval_result", None)
    return raw if isinstance(raw, dict) else {}


def _unit_ko(freq: Any) -> str:
    """freq 단위 한국어 — 정확 매칭 → prefix 폴백 → "주기"."""
    if not freq:
        return "주기"
    return FREQ_UNIT_KO.get(freq) or FREQ_UNIT_KO.get(freq[:1] if freq else "") or "주기"


# H1 — slope 키 버그 수정 (profiler 정식 키 = slope_per_obs / legacy = slope)
def _trend_slope_compat(trend: dict) -> Optional[float]:
    """slope_per_obs (profiler 정식) → slope (legacy) → None."""
    if not isinstance(trend, dict):
        return None
    v = trend.get("slope_per_obs")
    if v is None:
        v = trend.get("slope")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# H2 — 0단계 메타 추출 (proposer.g1 직접 호출 — chosen_recipe 미존재 우회)
def _zero_step_meta(state: Any) -> dict:
    """proposer.g1(state) 의 top recipe 의 meta 추출 — 0단계 성격 (variate/
    forecast_kind/task_kind/horizon_hint).

    호환성: HJ-5 (2026-06-05) 이후 chosen_recipe 는 PipelineState 정식 필드이지만,
    채우는 dispatcher 로직은 HJ-7 후속 (현재 dead field). 채워질 때까지 1순위로
    state.chosen_recipe.meta 를 시도하고, 빈 경우 proposer.g1 의 top1 meta 로 fallback.
    실패해도 graceful (모든 키 None).
    """
    default = {"variate": None, "forecast_kind": None, "task_kind": None, "horizon_hint": None}
    # 1순위 — state.chosen_recipe.meta (운영 경로에서 들어오면 활용)
    chosen = getattr(state, "chosen_recipe", None)
    if isinstance(chosen, dict):
        meta = chosen.get("meta")
        if isinstance(meta, dict):
            return {
                "variate": meta.get("variate"),
                "forecast_kind": meta.get("forecast_kind"),
                "task_kind": meta.get("task_kind"),
                "horizon_hint": meta.get("horizon_hint"),
            }
    # 2순위 — proposer.g1(state) 직접 호출
    try:
        from agents.handlers.timeseries.proposer import g1 as _g1

        recipes = _g1(state) or []
        if recipes and isinstance(recipes[0], dict):
            meta = recipes[0].get("meta")
            if isinstance(meta, dict):
                return {
                    "variate": meta.get("variate"),
                    "forecast_kind": meta.get("forecast_kind"),
                    "task_kind": meta.get("task_kind"),
                    "horizon_hint": meta.get("horizon_hint"),
                }
    except Exception:
        pass
    return default


# H3·H4·H5·H7 — evaluator 신규 4 키 안전 추출
def _eval_diagnostics(state: Any) -> dict:
    """state.eval_result 에서 cs-day7 v3 신규 4키 + OF5 fit_quality 안전 추출.

    state.eval_result 는 EvalAgent 가 with_update(eval_result=...) 로 저장.
    우리 evaluator 가 채운 키 중 H3/H4/H5/H7/OF5 관련 5 키 추출.
    """
    er = _eval_result(state)
    return {
        "leakage_signals": er.get("leakage_suspect_signals") or [],
        "fold_diag": er.get("fold_diagnostics") or {},
        "symptom": er.get("symptom_classification") or {},
        "task_kind_hint": er.get("task_kind_hint"),
        "fit_quality": er.get("fit_quality") or {},
        "residual_diag": er.get("residual_diagnostics") or {},  # G15
        "dm_test": er.get("dm_test") or {},  # G13
    }


# ════════════════════════════════════════════════════════════════
# §B. prompt_payload — horizon 추론 + 0단계 메타 + 진단 (시그니처 호환)
# ════════════════════════════════════════════════════════════════
def prompt_payload(state: Any) -> dict[str, Any]:
    """LLM 호출용 payload — dispatcher 가 사용 (HJ BaseAgent._call_llm).

    cs-day8 v3 디벨롭: 기존 11키 + 신규 키 (zero_step / eval_diagnostics) 추가.
    dispatcher 는 payload 를 통째로 LLM 컨텍스트에 직렬화 → LLM 이 풍부한
    근거로 인사이트 작성. 기존 11키 키 이름 불변 (회귀 0).
    """
    bm = getattr(state, "best_model", None) or {}
    data_profile = getattr(state, "data_profile", None) or {}
    eda = _eda_dict(state)

    trend = data_profile.get("trend") or {}
    s = data_profile.get("seasonality") or {}
    period = s.get("period") or eda.get("seasonal_period") or 7

    freq = data_profile.get("freq") or eda.get("freq") or "D"
    horizon_n = period if (period and isinstance(period, int)) else FREQ_HORIZON_FALLBACK.get(freq, 7)
    unit_ko = _unit_ko(freq)
    horizon_text = f"다음 {horizon_n}{unit_ko}"

    # H2 신규 — 0단계 메타
    zero = _zero_step_meta(state)
    # H3·H4·H5·H7 신규 — evaluator 진단
    diag = _eval_diagnostics(state)

    return {
        # 기존 11 키 (불변, 회귀 0)
        "category": "timeseries",
        "user_intent": getattr(state, "user_intent", None),
        "best_model": bm,
        "stationarity": data_profile.get("stationarity"),
        "trend": trend,
        "seasonality": s,
        "eval_result": getattr(state, "eval_result", None),
        "horizon_text": horizon_text,
        "horizon_n": horizon_n,
        "unit_ko": unit_ko,
        "system_prompt": SYSTEM_PROMPT,
        # cs-day8 v3 신규 키 (LLM 컨텍스트 풍부화 — 호환 OK, 기존 키 불변)
        "zero_step": zero,
        "eval_diagnostics": diag,
    }


# ════════════════════════════════════════════════════════════════
# §F. fallback — 다단 한국어 조립 (수치 2+ 보장 + 디벨롭 7건 반영)
# ════════════════════════════════════════════════════════════════
def fallback(state: Any) -> str:
    """LLM 실패 시 한국어 3~7문장 fallback (수치 2+ 보장 + 정직한 한계 보고).

    응급 안전망: 본문 실패 시 "이번 분석 결과는 추가 검토가 필요합니다."
    """
    try:
        return _build_fallback(state)
    except Exception:
        return "이번 분석 결과는 추가 검토가 필요합니다."


def _build_fallback(state: Any) -> str:
    bm = getattr(state, "best_model", None) or {}
    data_profile = getattr(state, "data_profile", None) or {}
    eda = _eda_dict(state)
    metrics = bm.get("metrics") or {}
    eval_result_dict = _eval_result(state)
    # metrics 우선순위: best_model.metrics > eval_result.metrics
    if not metrics:
        metrics = eval_result_dict.get("metrics") or {}

    # ── F-1 : direction 한국어 ──
    trend = data_profile.get("trend") or {}
    direction_en = trend.get("direction")
    direction_ko = DIRECTION_KO.get(direction_en, "혼합")

    # ── F-2 : freq 단위 한국어 ──
    freq = data_profile.get("freq") or eda.get("freq") or "D"
    unit_ko = _unit_ko(freq)

    # ── seasonality + period ──
    s = data_profile.get("seasonality") or {}
    has_seas = s.get("has_seasonality")
    period = s.get("period") or eda.get("seasonal_period") or 7

    # ── F-3 (H1) : slope 변화율 (slope_per_obs 정식 키 사용) ──
    slope_pct = _trend_slope_compat(trend)
    if slope_pct is not None and abs(slope_pct) > 0.001:
        slope_text = f" (평균 {slope_pct:+.1%})"
    else:
        slope_text = ""

    # ── F-4 : improvement / MASE 대체 ──
    improvement = metrics.get("rmse_improvement_vs_naive")
    mase = metrics.get("MASE")
    if improvement is not None:
        perf_text = f"naïve 대비 {improvement:+.1%} 우수한 성능"
    elif mase is not None:
        if mase < 1.0:
            perf_text = f"MASE {mase:.2f} 의 양호한 성능"
        else:
            perf_text = f"MASE {mase:.2f} 의 추가 검토가 필요한 성능"
    else:
        perf_text = "추가 검토가 필요한 성능"

    model_name = bm.get("model_name", "미정")

    # horizon (proposer §F meta.horizon_hint 우선)
    zero = _zero_step_meta(state)
    horizon_n = zero.get("horizon_hint") or (
        period if (period and isinstance(period, int)) else FREQ_HORIZON_FALLBACK.get(freq, 7)
    )
    horizon_n = int(horizon_n) if isinstance(horizon_n, (int, float)) else 7
    horizon_text = f"다음 {horizon_n}{unit_ko}"

    # H6 — 도메인 가이드 (승법·changepoint·이분산)
    is_mult = eda.get("is_multiplicative")
    cp_count = int(eda.get("changepoints") or 0)
    hetero = eda.get("heteroscedastic")
    domain_hints: list[str] = []
    if is_mult is True:
        domain_hints.append("분산이 레벨에 비례하는 승법 구조로 로그 변환 검토")
    if cp_count >= 3:
        domain_hints.append(f"레짐 변화 {cp_count}건 감지로 이벤트 더미 피처 권장")
    if hetero is True:
        domain_hints.append("이분산 잔차로 시간 적응형 PI 검토")

    # H3·H4·H5·H7 — evaluator 진단
    diag = _eval_diagnostics(state)
    leakage = diag.get("leakage_signals") or []
    fold_diag = diag.get("fold_diag") or {}
    symptom = diag.get("symptom") or {}
    task_hint = diag.get("task_kind_hint")

    # H2 — 0단계 한국어
    variate_ko = VARIATE_KO.get(zero.get("variate")) if zero.get("variate") else None
    forecast_kind_ko = FORECAST_KIND_KO.get(zero.get("forecast_kind")) if zero.get("forecast_kind") else None
    zero_step_phrase = ""
    if variate_ko and forecast_kind_ko:
        zero_step_phrase = f" {variate_ko} {forecast_kind_ko}"
    elif variate_ko:
        zero_step_phrase = f" {variate_ko}"
    elif forecast_kind_ko:
        zero_step_phrase = f" {forecast_kind_ko}"

    # ── F-5 : 동적 문장 조립 (3~7문장) ──
    sentences: list[str] = []

    # 문장 1 — 추세 + slope + (H6) 도메인 가이드
    if slope_text:
        base_sent = f"본 시계열은 {direction_ko} 추세를 보이며{slope_text} 입니다"
    else:
        base_sent = f"본 시계열은 {direction_ko} 추세를 보입니다"
    if domain_hints:
        base_sent = base_sent + f" — {', '.join(domain_hints)}"
    base_sent = base_sent + "."
    sentences.append(base_sent)

    # 문장 2 — 계절성 + period (has_seas True 일 때만)
    if has_seas and period:
        sentences.append(f"{period}{unit_ko} 주기 계절성이 관측됩니다.")

    # 문장 3 — 모델 성능 + improvement (수치 보장)
    if perf_text.endswith("성능"):
        sentences.append(f"{model_name} 모델은 {perf_text}을 보입니다.")
    else:
        sentences.append(f"{model_name} 모델은 {perf_text}입니다.")

    # 문장 3-b (H4) — walk-forward fold 진단
    if fold_diag.get("available"):
        n_folds = fold_diag.get("n_folds")
        fmean = fold_diag.get("mean")
        stability = fold_diag.get("stability")
        if n_folds and fmean is not None:
            sentences.append(f"walk-forward 검증 {n_folds}개 fold 평균 개선율 {fmean:+.3f} ({stability or 'N/A'}).")

    # 문장 4 — horizon + 0단계
    if zero_step_phrase and "예측" in zero_step_phrase:
        sentences.append(f"{horizon_text} 동안{zero_step_phrase}으로 활용 가능합니다.")
    elif zero_step_phrase:
        sentences.append(f"{horizon_text} 동안{zero_step_phrase} 예측에 활용 가능합니다.")
    else:
        sentences.append(f"{horizon_text} 동안 예측에 활용 가능합니다.")

    # 문장 5 (H3) — 누수 의심 한계 인정
    if leakage:
        kinds = ", ".join(s.get("kind", "?") for s in leakage[:3])
        sentences.append(f"단, 검증 신호 ({kinds}) 가 감지되어 운영 적용 전 누수 점검이 필요합니다.")

    # 문장 6 (H5) — 증상 + 롤백 우선순위 (정상 아닐 때)
    sym_code = symptom.get("symptom")
    if sym_code and sym_code not in ("normal",):
        sym_label = symptom.get("label") or SYMPTOM_KO_LABEL.get(sym_code, sym_code)
        rb = symptom.get("rollback_priority") or []
        rb_phrase = f"이며 권장 조치는 {rb[0]} 입니다" if rb else "입니다"
        sentences.append(f"진단 결과 증상은 {sym_code} ({sym_label}){rb_phrase}.")

    # 문장 7 (H7) — task_kind_hint
    if task_hint:
        sentences.append(task_hint)

    # 문장 7-b (OF6, 2026-06-05) — 과적합/과소적합 안내 (severity 가 warn/severe 일 때만)
    fit_q = diag.get("fit_quality") or {}
    fit_kind = fit_q.get("kind")
    fit_sev = fit_q.get("severity")
    if fit_kind in ("overfit", "underfit") and fit_sev in ("warn", "severe"):
        hint = fit_q.get("hint") or ""
        if hint:
            sentences.append(hint)

    # 문장 7-c (G15, 2026-06-05) — 잔차 자기상관 안내 (autocorrelated 일 때만)
    rd = diag.get("residual_diag") or {}
    if rd.get("kind") == "autocorrelated" and rd.get("hint"):
        sentences.append(rd["hint"])

    # 문장 7-d (G13, 2026-06-05) — DM 검정 (naive_wins 일 때만)
    dmt = diag.get("dm_test") or {}
    if dmt.get("verdict") == "naive_wins" and dmt.get("hint"):
        sentences.append(dmt["hint"])

    # 문장 마지막 — 행동 권고
    if not leakage and (not sym_code or sym_code == "normal"):
        sentences.append("운영팀은 주간 단위로 모델 결과를 모니터링할 것을 권장합니다.")

    # 수치 0 최악 케이스 보강
    if not has_seas and improvement is None and slope_pct is None and mase is None:
        insert_at = max(0, len(sentences) - 1)
        sentences.insert(insert_at, f"{horizon_n}{unit_ko} 후 예측을 위해 추가 모니터링이 필요합니다.")

    # P10: 5문장 하드 제한
    if len(sentences) > 5:
        drop_patterns = [
            lambda s: s.startswith("walk-forward"),
            lambda s: "주기 계절성" in s,
            lambda s: "운영팀은" in s and "모니터링" in s,
            lambda s: task_hint and s == task_hint,
        ]
        for pred in drop_patterns:
            if len(sentences) <= 5:
                break
            for i, s in enumerate(sentences):
                if pred(s):
                    sentences.pop(i)
                    break
        if len(sentences) > 5:
            sentences = sentences[:5]

    # 3~5 문장 보장
    while len(sentences) < 3:
        sentences.append("추가 검증이 필요한 시점입니다.")

    return " ".join(sentences)


# ════════════════════════════════════════════════════════════════
# 진입점 (dispatcher 자동 등록, "generate" capability)
# ════════════════════════════════════════════════════════════════
def generate(state: Any) -> str:
    """HANDLER_REGISTRY 등록 진입점 — InsightAgent dispatcher 가 호출.

    LLM 기반 생성은 dispatcher 가 담당하고, 여기서는 규칙 기반 fallback 을 반환한다.
    dispatcher 가 LLM 응답을 받으면 이 결과 대신 LLM 결과를 사용한다.
    """
    return fallback(state)
