"""agents.handlers.tabular.insight — 정형 인사이트 (jh 담당).

Day 11 (jh) — SYSTEM_PROMPT 풀 보강:
    오늘 추가한 모든 메타데이터(model_scores, optimal_threshold, per-class F1,
    id-like/leakage 경고, mutual_info, 잔차, 다중 지표)를 LLM 이 산출물에
    인용할 수 있도록 prompt_payload 와 SYSTEM_PROMPT 를 보강.

    "코드는 만들었는데 사용자 보고서엔 안 나타나는" 갭을 닫는 작업.
"""

from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """당신은 정형 데이터 분석 인사이트 작성자입니다.
아래 메타데이터를 종합해 한국어 4~6문장으로 인사이트를 작성하세요.

필수 규칙 (모두 적용):
  1. 정확한 수치 1개 이상 인용 (val_f1 / val_r2 / val_accuracy 등)
  2. cv_stats.primary_std 가 있으면 "F1 0.83 ± 0.04" 형식으로 신뢰구간 1문장
  3. improvement_over_baseline.primary_lift 가 있으면 "기본값(Dummy 등) 대비 +N 향상" 1문장
     - lift_significant=True → "통계적으로 유의" 추가
     - lift_significant=False → "노이즈 범위 내" 신중 표현
  4. shap_top 또는 mutual_info_top 의 상위 피처 1개 이상 언급
  5. 마지막 1문장은 비즈니스 행동 권고

조건부 규칙 (해당 메타데이터가 있을 때만 인용):
  6. target_leakage_suspects 가 비어있지 않으면 "다만 X 컬럼이 target과 강상관(상관계수)으로 누수 의심"
     경고 1문장 — 모델 신뢰도에 대한 가장 중요한 정직성 표시
  7. id_like_columns 가 비어있지 않으면 "X 컬럼은 식별자 추정 — 학습 제외 권장" 경고 1문장
  8. val_optimal_threshold (분류) 가 있으면 "기본 임계값 0.5 대신 {opt:.2f} 에서 F1 최대" 1문장
  9. val_f1_per_class (multiclass) 가 있으면 가장 낮은 클래스 1개 약점 언급
 10. val_residual_mean (회귀) 가 |0.1| 보다 크면 "예측에 편향 의심" 1문장
 11. class_imbalance_ratio >= 5 면 "클래스 불균형(N:1)" 사실 1문장
 12. archetype.primary 가 'clean_balanced' 가 아니면 그 archetype 특성을 1문장으로 설명
     예: 'extreme_imbalance' → "극단 불균형이라 이상탐지 카테고리도 검토 권합니다"
     예: 'p_gg_n' → "피처가 행보다 많아 정규화 선형 모델 위주로 추천했습니다"
     예: 'multicollinear_heavy' → "수치형 피처 간 강한 상관 — VIF drop 적용"

형식 규칙:
  - 마크다운/리스트/이모지/번호 매김 금지 — 자연스러운 한국어 문장
  - 4~6문장 (필수 규칙 5개 + 적용 가능한 조건부 1~3개)
"""


def _safe_get(obj: Any, *keys: str, default: Any = None) -> Any:
    """중첩 dict 안전 접근 — 키 없거나 None 이면 default."""
    cur = obj
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def prompt_payload(state: Any) -> dict[str, Any]:
    """LLM 이 인용할 모든 메타데이터를 한 dict 에 노출.

    Day 11 (jh) — 오늘 작업으로 추가된 메타데이터:
      - cv_stats / baseline_cv_stats          (CV 통계)
      - improvement_over_baseline + lift_significant + baseline_used  (베이스라인 격차)
      - model_scores                          (selector 신호 점수 매트릭스)
      - data_profile.id_like_columns          (EDA — 식별자 추정)
      - data_profile.target_leakage_suspects  (EDA — 누수 의심)
      - data_profile.mutual_info_top          (EDA — 신호 강도)
      - best_model.metrics.val_optimal_threshold / val_f1_at_optimal_threshold
      - best_model.metrics.val_f1_per_class   (multiclass)
      - best_model.metrics.val_mcc / val_pr_auc / val_brier / val_log_loss
      - best_model.metrics.val_residual_*     (회귀 잔차 통계)
      - leakage_safe_split                    (누수 가드 사용 여부)
    """
    eval_result = state.eval_result or {}
    data_profile = state.data_profile or {}
    cat_key = "tabular" if str(getattr(state, "category", "")).startswith("tabular") else getattr(state, "category", "")
    cat_extras = (getattr(state, "category_extras", None) or {}).get(cat_key, {})

    best_model = state.best_model or {}
    best_metrics = best_model.get("metrics") or {}

    # Day 11++ — SHAP top features. state.explanations (dispatcher 가 채워야 정식)
    # 가 비어있으면 category_extras["tabular"]["shap"] 캐시 fallback (output_extras
    # 가 SHAP 계산해 저장한 결과). 미연결 환경에서도 insight 가 실제 SHAP 인용.
    shap_top = _safe_get(state.explanations, "shap_top_features")
    if not shap_top:
        shap_top = (cat_extras.get("shap") or {}).get("shap_top_features") or []

    return {
        # 기본
        "category": state.category,
        "user_intent": state.user_intent,
        "best_model": best_model,
        "shap_top": shap_top,

        # 평가 결과 + 다중 지표
        "eval_result": eval_result,
        "metrics_full": best_metrics,  # MCC/PR AUC/Brier/log_loss/per-class F1 등 다 포함

        # 베이스라인 격차 + 유의성
        "improvement_over_baseline": eval_result.get("improvement_over_baseline") or {},
        "baseline_used": eval_result.get("baseline_used") or {},

        # CV 통계
        "cv_stats": eval_result.get("cv_stats") or {},
        "baseline_cv_stats": eval_result.get("baseline_cv_stats") or {},

        # selector 신호 점수
        "model_scores": cat_extras.get("g4_visible_top3") or [],  # G4 UI 에 노출된 top3

        # EDA 보강 메타데이터
        "id_like_columns": data_profile.get("id_like_columns") or [],
        "target_leakage_suspects": data_profile.get("target_leakage_suspects") or [],
        "mutual_info_top": data_profile.get("mutual_info_top") or {},

        # 임계값 자동 탐색
        "optimal_threshold": best_metrics.get("val_optimal_threshold"),
        "f1_at_optimal_threshold": best_metrics.get("val_f1_at_optimal_threshold"),

        # 데이터 특성
        "class_imbalance_ratio": data_profile.get("class_imbalance_ratio"),
        "n_rows": data_profile.get("rows"),

        # 누수 가드 사용 여부
        "leakage_safe_split_used": bool(cat_extras.get("leakage_safe_split")),

        # Day 11+ (jh, decision-aware) — archetype 인용
        # selector·proposer 와 동일한 ground truth 를 insight 도 인용 → 일관성 보장.
        "archetype": data_profile.get("archetype") or {},
    }


def _archetype_insight_line(archetype: dict[str, Any]) -> str | None:
    """archetype 매칭 결과를 signals 값 + confidence 톤으로 1 문장 생성.

    confidence < 0.5  → None (너무 약한 매칭, 사용자 혼란 방지)
    confidence 0.5~0.8 → 추정 톤 ("가능성", "의심")
    confidence ≥ 0.8  → 단정 톤

    Day 11++ — 정적 메시지 cliff 제거 + 실제 signals 인용으로 투명성 확보.
    """
    primary = archetype.get("primary")
    if not primary or primary == "clean_balanced":
        return None
    signals = archetype.get("signals") or {}
    conf = float(archetype.get("primary_confidence", 1.0) or 0.0)
    if conf < 0.5:
        return None
    weak = conf < 0.8  # 약한 매칭이면 추정 톤

    if primary == "target_leakage_suspected":
        cols = signals.get("leakage_columns") or []
        col_str = ", ".join(f"'{c}'" for c in cols[:2]) if cols else "일부 컬럼"
        verb = "보일 가능성이 있어" if weak else "보여"
        return (
            f"{col_str} 가 타겟과 매우 강한 상관을 {verb} 누수 의심으로 "
            f"보수적 모델을 우선 추천했습니다."
        )

    if primary == "extreme_imbalance":
        ratio = signals.get("imbalance_ratio")
        ratio_str = f"1:{int(ratio):,}" if ratio else "극단"
        verb = "수준일 가능성" if weak else "수준"
        return (
            f"클래스 비율이 {ratio_str} {verb}이라 정형 분류 부적합 — "
            f"이상탐지 카테고리 검토를 권합니다."
        )

    if primary == "p_gg_n":
        r = signals.get("feature_to_row_ratio")
        r_str = f"{r:.2f}" if r is not None else "≥0.5"
        verb = "근접해" if weak else "넘어"
        return (
            f"피처/행 비율 {r_str} 로 p≫n 영역에 {verb} "
            f"정규화 선형 모델 위주로 추천했습니다."
        )

    if primary == "high_cardinality_heavy":
        n = signals.get("high_cardinality_count")
        n_str = f"{int(n)}개" if n is not None else "다수"
        return (
            f"고차원 범주형 컬럼 {n_str} 감지 — CatBoost·LightGBM 의 native "
            f"범주 처리를 우선했습니다."
        )

    if primary == "multicollinear_heavy":
        clusters = signals.get("corr_clusters")
        cond = signals.get("corr_condition_number")
        if clusters:
            return (
                f"수치형 피처 간 강한 상관 클러스터 {int(clusters)}개 감지 — "
                f"VIF drop 적용을 권합니다."
            )
        if cond:
            return (
                f"상관 행렬 condition number {float(cond):.0f} — "
                f"다중공선성 강해 VIF drop 적용을 권합니다."
            )
        return "수치형 피처 간 강한 다중공선성이 있어 VIF 기반 컬럼 제거가 적용되었습니다."

    if primary == "id_overload":
        r = signals.get("id_like_ratio")
        r_str = f"{float(r):.0%}" if r is not None else "30% 이상"
        return (
            f"전체 컬럼의 {r_str} 가 식별자 추정 — "
            f"학습 피처 구성 재검토를 권합니다."
        )

    if primary == "imbalanced_moderate":
        ratio = signals.get("imbalance_ratio")
        if ratio:
            return (
                f"클래스 비율 1:{int(ratio):,} — class weight 와 "
                f"cost-sensitive 임계치 적용을 권합니다."
            )
        return "클래스 불균형이 중간 수준이라 class weight 와 cost-sensitive 임계치 적용을 권합니다."

    if primary == "low_signal":
        mi = signals.get("max_mutual_info")
        mi_str = f"{float(mi):.3f}" if mi is not None else "< 0.05"
        return (
            f"피처-타겟 mutual information 최댓값 {mi_str} — "
            f"추가 피처 엔지니어링 또는 비지도 접근이 효과적입니다."
        )

    if primary == "regression_heteroscedastic":
        cv = signals.get("max_coefficient_of_variation")
        cv_str = f"(변동계수 {float(cv):.1f})" if cv is not None else ""
        return (
            f"수치형 변동성이 큼 {cv_str} — log 또는 yeo-johnson "
            f"분포 변환을 권합니다."
        ).replace("  ", " ").strip()

    return None


def fallback(state: Any) -> str:
    """LLM 실패 시 결정적 인사이트 텍스트 생성.

    Day 11 (jh) — 신규 메타데이터 조건부 인용:
      - cv_stats : "F1 0.83 ± 0.04" 형식
      - improvement_over_baseline + lift_significant : "Dummy 대비 +0.32 (유의)"
      - target_leakage_suspects : 경고 1문장
      - id_like_columns : 경고 1문장
      - optimal_threshold : 임계값 권장
      - 회귀 잔차 편향 : 1문장
    """
    bm = state.best_model or {}
    metrics = bm.get("metrics", {})
    eval_result = state.eval_result or {}
    data_profile = state.data_profile or {}

    parts: list[str] = [
        f"본 분석은 {bm.get('model_name', '미정')} 모델이 가장 우수한 성능을 보였습니다."
    ]

    # 0) archetype 1 문장 (clean_balanced 면 생략, confidence < 0.5 면 생략)
    #    Day 11++ — 정적 메시지 대신 실제 signals 값을 인용 + confidence 톤 조절.
    archetype_line = _archetype_insight_line(data_profile.get("archetype") or {})
    if archetype_line:
        parts.append(archetype_line)

    # 1) CV 통계 우선, 없으면 단일 수치
    cv_stats = eval_result.get("cv_stats") or {}
    cv_mean = cv_stats.get("primary_mean")
    cv_std = cv_stats.get("primary_std")
    cv_metric = cv_stats.get("primary_metric")
    if cv_mean is not None and cv_std is not None and cv_metric:
        parts.append(
            f"5-fold 교차검증 {cv_metric} 점수는 "
            f"{float(cv_mean):.2f} ± {float(cv_std):.2f} 입니다."
        )
    else:
        f1 = metrics.get("val_f1")
        if f1 is not None:
            parts.append(f"검증 F1 점수는 {float(f1):.2f} 입니다.")
        auc = metrics.get("val_roc_auc")
        if auc is not None:
            parts.append(f"ROC AUC 는 {float(auc):.2f} 입니다.")

    # 2) Baseline 격차 + 유의성
    improvement = eval_result.get("improvement_over_baseline") or {}
    primary_lift = improvement.get("primary_lift")
    primary_metric = improvement.get("primary_metric")
    baseline_name = (eval_result.get("baseline_used") or {}).get("name")
    lift_significant = improvement.get("lift_significant")
    if primary_lift is not None and primary_metric and baseline_name:
        sign = "+" if primary_lift >= 0 else ""
        sig_suffix = ""
        if lift_significant is True:
            sig_suffix = " (통계적으로 유의)"
        elif lift_significant is False:
            sig_suffix = " (노이즈 범위 내)"
        parts.append(
            f"기본값 모델({baseline_name}) 대비 {primary_metric}이 "
            f"{sign}{float(primary_lift):.2f} 향상되었습니다{sig_suffix}."
        )

    # 3) Day 11 신규 — target leakage 경고 (가장 중요)
    leak = data_profile.get("target_leakage_suspects") or []
    if leak:
        first = leak[0]
        parts.append(
            f"다만 '{first.get('column')}' 컬럼이 타겟과 상관 "
            f"{float(first.get('correlation', 0)):.2f} 로 데이터 누수가 의심되니 학습 제외를 검토하세요."
        )

    # 4) Day 11 신규 — id-like 경고
    id_like = data_profile.get("id_like_columns") or []
    if id_like:
        parts.append(
            f"식별자로 추정되는 컬럼({', '.join(id_like[:3])})은 학습에서 제외하는 것이 안전합니다."
        )

    # 5) Day 11 신규 — 분류 임계값 권장
    opt_thr = metrics.get("val_optimal_threshold")
    opt_f1 = metrics.get("val_f1_at_optimal_threshold")
    if opt_thr is not None and opt_f1 is not None:
        parts.append(
            f"기본 임계값 0.5 대신 {float(opt_thr):.2f} 적용 시 F1이 {float(opt_f1):.2f} 까지 향상됩니다."
        )

    # 6) Day 11 신규 — multiclass per-class F1 약점
    per_class = metrics.get("val_f1_per_class")
    if isinstance(per_class, dict) and len(per_class) > 2:
        weak_class, weak_f1 = min(per_class.items(), key=lambda kv: kv[1])
        if weak_f1 < 0.6:
            parts.append(
                f"단 클래스 '{weak_class}' F1이 {float(weak_f1):.2f} 로 약하니 추가 데이터/리샘플링을 고려하세요."
            )

    # 7) Day 11 신규 — 회귀 잔차 편향
    resid_mean = metrics.get("val_residual_mean")
    if resid_mean is not None and abs(float(resid_mean)) > 0.1:
        parts.append(
            f"잔차 평균이 {float(resid_mean):.2f} 로 예측에 체계적 편향이 의심됩니다."
        )

    parts.append("실무에서는 본 모델 예측 결과를 의사결정 보조 자료로 활용 권장합니다.")
    return " ".join(parts)
