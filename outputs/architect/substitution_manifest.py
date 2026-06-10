"""outputs.architect.substitution_manifest — 산출 PPT 카테고리별 슬라이드 대체 매니페스트.

20슬라이드 골격은 4 카테고리 (tabular_ml / tabular_dl / timeseries / anomaly) 공통.
의미 없는 슬라이드는 skip 하지 않고 *비슷한 다른 변형* 으로 대체.
본 모듈은 그 대체 매핑을 *코드화* — 슬라이드 role 별로 카테고리에 맞는 spec 반환.

설계 원칙은 docs/slide_substitution_manifest.md 참조.

사용 흐름:
    >>> from outputs.architect.substitution_manifest import resolve_slide, resolve_tech_stack
    >>> variant = resolve_slide("shap_global", "timeseries")
    >>> # → SlideVariant(title="시점별 영향도", ...)
    >>> stack = resolve_tech_stack("anomaly")
    >>> # → ["scikit-learn", "IsolationForest / LOF / AutoEncoder", ...]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# ==============================================================
# 1) 카테고리 상수 — 매니페스트가 다루는 카테고리 4종
# ==============================================================

CATEGORY_TABULAR_ML = "tabular_ml"
CATEGORY_TABULAR_DL = "tabular_dl"
CATEGORY_TIMESERIES = "timeseries"
CATEGORY_ANOMALY = "anomaly_detection"

SUPPORTED_CATEGORIES: tuple[str, ...] = (
    CATEGORY_TABULAR_ML,
    CATEGORY_TABULAR_DL,
    CATEGORY_TIMESERIES,
    CATEGORY_ANOMALY,
)


def _normalize_category(category: Optional[str]) -> str:
    """카테고리 문자열 정규화 — 별칭·짧은 이름을 표준 키로 매핑.

    ml_pitch 의 사용자 입력은 ``tabular_ml`` 외에 ``ml`` / ``tabular`` 등 변종 가능.
    매니페스트 lookup 실패 시 ``tabular_ml`` 폴백.
    """
    if not category:
        return CATEGORY_TABULAR_ML
    c = category.strip().lower()
    aliases = {
        "ml": CATEGORY_TABULAR_ML,
        "tabular": CATEGORY_TABULAR_ML,
        "tabular_ml": CATEGORY_TABULAR_ML,
        "dl": CATEGORY_TABULAR_DL,
        "tabular_dl": CATEGORY_TABULAR_DL,
        "ts": CATEGORY_TIMESERIES,
        "timeseries": CATEGORY_TIMESERIES,
        "time_series": CATEGORY_TIMESERIES,
        "anomaly": CATEGORY_ANOMALY,
        "anomaly_detection": CATEGORY_ANOMALY,
    }
    return aliases.get(c, CATEGORY_TABULAR_ML)


# ==============================================================
# 2) Tech Stack 프리셋 (S6 슬라이드)
# ==============================================================


@dataclass(frozen=True)
class TechStackItem:
    """Tech Stack 한 항목 — 도구 이름 + 역할 1줄.

    S6 슬라이드의 2단 위계 (소제목 + 설명) 의 입력.
    """

    name: str
    role: str  # 한국어 1줄 — "전처리·결측·인코딩 일괄" 등


TECH_STACK_BY_CATEGORY: dict[str, list[TechStackItem]] = {
    CATEGORY_TABULAR_ML: [
        TechStackItem("scikit-learn", "전처리 · 결측 · 인코딩 · 스케일링 일괄"),
        TechStackItem("CatBoost / LightGBM", "GBM 모델 — 범주형 자동 인코딩"),
        TechStackItem("SHAP", "전역 · 지역 변수 기여도 해석"),
        TechStackItem("MLflow", "실험 추적 · 메트릭 · 모델 레지스트리"),
    ],
    CATEGORY_TABULAR_DL: [
        TechStackItem("PyTorch", "딥러닝 학습 · 분산 · GPU 가속"),
        TechStackItem("TabNet / FT-Transformer", "정형 데이터 전용 DL 아키텍처"),
        TechStackItem("Integrated Gradients", "DL 모델 변수 기여도 해석"),
        TechStackItem("Weights & Biases", "실험 추적 · 하이퍼파라미터 스윕"),
    ],
    CATEGORY_TIMESERIES: [
        TechStackItem("statsmodels", "ARIMA · 분해 · 잔차 진단"),
        TechStackItem("Prophet / N-BEATS", "추세 · 계절성 · 외생변수 예측"),
        TechStackItem("Lag · Calendar features", "시간 기반 피처 엔지니어링"),
        TechStackItem("MLflow", "실험 추적 · 메트릭 · 모델 레지스트리"),
    ],
    CATEGORY_ANOMALY: [
        TechStackItem("scikit-learn", "전처리 · 기본 이상탐지 알고리즘"),
        TechStackItem("IsolationForest / LOF", "비지도 이상 점수 산출"),
        TechStackItem("AutoEncoder", "재구성 오차 기반 이상 탐지"),
        TechStackItem("ThresholdTuner", "임계값 · 알람 budget 최적화"),
    ],
}


# ==============================================================
# 3) 슬라이드 변형 (역할별 카테고리 매핑)
# ==============================================================


@dataclass(frozen=True)
class SlideVariant:
    """슬라이드 한 카테고리 변형 — title / layout / 시각 spec.

    Carrier 가 본 spec 을 기반으로 슬라이드 렌더. 실제 데이터는 ``ctx`` 에서 채움.
    """

    title_ko: str
    layout: str = "one_message"  # "chart_callout" / "method_flow" / "tech_stack" 등
    visual_type: Optional[str] = None
    visual_spec: dict[str, Any] = field(default_factory=dict)
    # 슬라이드별 필수 ctx 필드 — 미충족 시 fallback 변형 트리거
    required_ctx_fields: tuple[str, ...] = ()
    # 자동 추론 도메인 해석을 노출할지 (True 이면 [auto-inferred] 라벨 부착)
    accepts_auto_domain: bool = True


# 슬라이드 역할(role) — 골격 슬라이드 ID 가 아니라 *의미 단위* 기준.
# 동일 role 은 카테고리별로 다른 SlideVariant 를 가짐.
SLIDE_SUBSTITUTIONS: dict[str, dict[str, SlideVariant]] = {
    # === EDA 4종 (S8 ~ S11) ===
    "eda_main_1": {
        CATEGORY_TABULAR_ML: SlideVariant(
            title_ko="EDA · 주요 변수 1",
            layout="chart_callout",
            visual_type="chart_annotated_bar",
            required_ctx_fields=("eda.charts",),
        ),
        CATEGORY_TABULAR_DL: SlideVariant(
            title_ko="EDA · 주요 변수 1 / 임베딩 분포",
            layout="chart_callout",
            visual_type="chart_annotated_bar",
            required_ctx_fields=("eda.charts",),
        ),
        CATEGORY_TIMESERIES: SlideVariant(
            title_ko="시간축 · 트렌드",
            layout="chart_callout",
            visual_type="chart_line",
            required_ctx_fields=("eda.charts",),
        ),
        CATEGORY_ANOMALY: SlideVariant(
            title_ko="정상 vs 이상 분포 비교",
            layout="chart_callout",
            visual_type="chart_grouped_bar",
            required_ctx_fields=("eda.charts",),
        ),
    },
    "eda_main_2": {
        CATEGORY_TABULAR_ML: SlideVariant(
            title_ko="EDA · 주요 변수 2",
            layout="chart_callout",
            visual_type="chart_annotated_bar",
        ),
        CATEGORY_TABULAR_DL: SlideVariant(
            title_ko="EDA · 주요 변수 2",
            layout="chart_callout",
            visual_type="chart_annotated_bar",
        ),
        CATEGORY_TIMESERIES: SlideVariant(
            title_ko="계절 분해 · Trend / Seasonal / Residual",
            layout="chart_callout",
            visual_type="chart_decomposition",
        ),
        CATEGORY_ANOMALY: SlideVariant(
            title_ko="변수 상관 · 정상 vs 이상 패턴 차이",
            layout="chart_callout",
            visual_type="chart_corr_heatmap",
        ),
    },
    "eda_main_3": {
        CATEGORY_TABULAR_ML: SlideVariant(
            title_ko="EDA · 주요 변수 3",
            layout="chart_callout",
            visual_type="chart_annotated_bar",
        ),
        CATEGORY_TABULAR_DL: SlideVariant(
            title_ko="EDA · 주요 변수 3",
            layout="chart_callout",
            visual_type="chart_annotated_bar",
        ),
        CATEGORY_TIMESERIES: SlideVariant(
            title_ko="자기상관 · ACF / PACF",
            layout="chart_callout",
            visual_type="chart_acf_pacf",
        ),
        CATEGORY_ANOMALY: SlideVariant(
            title_ko="시간 · 위치 차원 이상 분포",
            layout="chart_callout",
            visual_type="chart_scatter_anomaly",
        ),
    },
    "eda_extra": {
        CATEGORY_TABULAR_ML: SlideVariant(
            title_ko="변수 간 상관 · 데이터 품질",
            layout="chart_callout",
            visual_type="chart_corr_heatmap",
        ),
        CATEGORY_TABULAR_DL: SlideVariant(
            title_ko="Latent Space 클러스터",
            layout="chart_callout",
            visual_type="chart_scatter",
        ),
        CATEGORY_TIMESERIES: SlideVariant(
            title_ko="결측 · 이상치 구간 패턴",
            layout="chart_callout",
            visual_type="chart_missing_pattern",
        ),
        CATEGORY_ANOMALY: SlideVariant(
            title_ko="Feature 별 이상 기여도",
            layout="chart_callout",
            visual_type="chart_annotated_bar",
        ),
    },
    # === Model Performance (S12) ===
    "model_perf": {
        CATEGORY_TABULAR_ML: SlideVariant(
            title_ko="모델 성능 · 4-Metric 균형",
            layout="chart_callout",
            visual_type="chart_grouped_baseline",
            required_ctx_fields=("evaluation.primary_metric", "evaluation.metrics"),
        ),
        CATEGORY_TABULAR_DL: SlideVariant(
            title_ko="모델 성능 · 4-Metric 균형",
            layout="chart_callout",
            visual_type="chart_grouped_baseline",
            required_ctx_fields=("evaluation.primary_metric",),
        ),
        CATEGORY_TIMESERIES: SlideVariant(
            title_ko="예측 성능 · MAE / MAPE / RMSE + 예측 구간",
            layout="chart_callout",
            visual_type="chart_forecast_interval",
            required_ctx_fields=("evaluation.primary_metric",),
        ),
        CATEGORY_ANOMALY: SlideVariant(
            title_ko="탐지 성능 · precision@k / recall@k / PR-AUC",
            layout="chart_callout",
            visual_type="chart_pr_curve",
            required_ctx_fields=("evaluation.primary_metric",),
        ),
    },
    # === SHAP Global (S13) ===
    "shap_global": {
        CATEGORY_TABULAR_ML: SlideVariant(
            title_ko="SHAP Global Importance · Top 5",
            layout="chart_callout",
            visual_type="chart_annotated_bar",
            required_ctx_fields=("interpretation.global_importance",),
        ),
        CATEGORY_TABULAR_DL: SlideVariant(
            title_ko="Integrated Gradients · Top 5",
            layout="chart_callout",
            visual_type="chart_annotated_bar",
            required_ctx_fields=("interpretation.global_importance",),
        ),
        CATEGORY_TIMESERIES: SlideVariant(
            title_ko="시점별 영향도 · Lag / 외생변수 기여",
            layout="chart_callout",
            visual_type="chart_annotated_bar",
            required_ctx_fields=("interpretation.global_importance",),
        ),
        CATEGORY_ANOMALY: SlideVariant(
            title_ko="Reason Code · 상위 5 Feature",
            layout="chart_callout",
            visual_type="chart_annotated_bar",
            required_ctx_fields=("interpretation.global_importance",),
        ),
    },
    # === SHAP Cases (S14) ===
    "shap_cases": {
        CATEGORY_TABULAR_ML: SlideVariant(
            title_ko="개별 예측 사례 · 3건",
            layout="one_message",
            required_ctx_fields=("interpretation.local_examples",),
        ),
        CATEGORY_TABULAR_DL: SlideVariant(
            title_ko="Attention Map · 사례 3건",
            layout="one_message",
        ),
        CATEGORY_TIMESERIES: SlideVariant(
            title_ko="계절 분해 효과 · 잔차 패턴",
            layout="one_message",
        ),
        CATEGORY_ANOMALY: SlideVariant(
            title_ko="이상 사례 3건 · Reason Code 별",
            layout="one_message",
        ),
    },
    # === Error CM (S15) ===
    "error_cm": {
        CATEGORY_TABULAR_ML: SlideVariant(
            title_ko="Confusion Matrix · 오류 분석",
            layout="chart_callout",
            visual_type="diagram_confusion_matrix",
            required_ctx_fields=("evaluation.confusion_matrix",),
        ),
        CATEGORY_TABULAR_DL: SlideVariant(
            title_ko="Confusion Matrix · 오류 분석",
            layout="chart_callout",
            visual_type="diagram_confusion_matrix",
            required_ctx_fields=("evaluation.confusion_matrix",),
        ),
        CATEGORY_TIMESERIES: SlideVariant(
            title_ko="잔차 진단 · ACF Residual / Q-Q Plot",
            layout="chart_callout",
            visual_type="chart_residual_diag",
        ),
        CATEGORY_ANOMALY: SlideVariant(
            title_ko="precision@k 곡선 · 알람 Budget 곡선",
            layout="chart_callout",
            visual_type="chart_pk_alarm_budget",
        ),
    },
    # === Segment (S16) ===
    "segment": {
        CATEGORY_TABULAR_ML: SlideVariant(
            title_ko="세그먼트별 성능 비교",
            layout="one_message",
        ),
        CATEGORY_TABULAR_DL: SlideVariant(
            title_ko="세그먼트별 성능 비교",
            layout="one_message",
        ),
        CATEGORY_TIMESERIES: SlideVariant(
            title_ko="계절 · 시간대 · 요일별 성능 차이",
            layout="one_message",
        ),
        CATEGORY_ANOMALY: SlideVariant(
            title_ko="정상 / 이상 클러스터 비교",
            layout="one_message",
        ),
    },
    # === Policy Insight (S17) ===
    "policy_insight": {
        CATEGORY_TABULAR_ML: SlideVariant(
            title_ko="도입 정책 · 운영 룰",
            layout="one_message",
        ),
        CATEGORY_TABULAR_DL: SlideVariant(
            title_ko="도입 정책 · 운영 룰",
            layout="one_message",
        ),
        CATEGORY_TIMESERIES: SlideVariant(
            title_ko="예측 구간 기반 운영 · 안전재고 · 임계 정책",
            layout="one_message",
        ),
        CATEGORY_ANOMALY: SlideVariant(
            title_ko="임계값 · 알람 Budget · 운영 시나리오",
            layout="one_message",
        ),
    },
}


# ==============================================================
# 4) verdict 별 어조 템플릿 (S2 · S17 · S19 분기)
# ==============================================================


@dataclass(frozen=True)
class VerdictTone:
    """verdict 별 슬라이드 어조 — title prefix · so_what 골격 · 색조."""

    s2_so_what_template: str  # {chosen} {metric_value} 등 format 변수
    s17_section_label: str
    s19_phase_pattern: str  # Phase 의 명명 패턴
    accent: str  # primary | warning | danger — 색조 힌트


VERDICT_TONES: dict[str, VerdictTone] = {
    "adopt": VerdictTone(
        s2_so_what_template=(
            "{chosen} 모델로 {use_case} 를 {metric_value} {metric_name} 으로 예측 — "
            "{horizon} 내 도입 권장"
        ),
        s17_section_label="도입 정책 · 운영 룰",
        s19_phase_pattern="Phase 1 (30일) 파일럿 → Phase 2 (90일) 전사 확장",
        accent="primary",
    ),
    "iterate": VerdictTone(
        s2_so_what_template=(
            "{chosen} 모델 성능 {metric_value} {metric_name} — 부족 영역 보강 후 재학습 권장"
        ),
        s17_section_label="보강 우선순위 · 재시도 조건",
        s19_phase_pattern="Phase 1 데이터 보강 → Phase 2 재학습 → Phase 3 재평가",
        accent="warning",
    ),
    "reject": VerdictTone(
        s2_so_what_template=(
            "{chosen} 모델 성능 {metric_value} {metric_name} — 현 모델 도입 불가, 대안 모색 필요"
        ),
        s17_section_label="폐기 사유 · 대안 권고",
        s19_phase_pattern="Phase 1 문제 재정의 → Phase 2 대안 모델 탐색 → Phase 3 검증",
        accent="danger",
    ),
}


# ==============================================================
# 5) 카테고리별 primary metric 타입 (typed schema assert 에 사용)
# ==============================================================

# 카테고리 → 허용 metric family 목록.
# evaluation.primary_metric.name 이 여기 속하지 않으면 fallback 슬라이드 변형 트리거.
METRIC_FAMILY_BY_CATEGORY: dict[str, frozenset[str]] = {
    CATEGORY_TABULAR_ML: frozenset({
        "accuracy", "f1", "precision", "recall", "roc_auc", "pr_auc", "log_loss",
        "mae", "mse", "rmse", "r2", "mape",  # regression 도 허용
    }),
    CATEGORY_TABULAR_DL: frozenset({
        "accuracy", "f1", "precision", "recall", "roc_auc", "pr_auc", "log_loss",
        "mae", "mse", "rmse", "r2", "mape",
    }),
    CATEGORY_TIMESERIES: frozenset({
        "mae", "mse", "rmse", "mape", "smape", "wape", "r2", "coverage",
    }),
    CATEGORY_ANOMALY: frozenset({
        "precision_at_k", "recall_at_k", "pr_auc", "roc_auc", "f1",
        "alarm_budget", "detection_rate",
    }),
}


# ==============================================================
# 6) 공개 API
# ==============================================================


def resolve_tech_stack(category: Optional[str]) -> list[TechStackItem]:
    """카테고리 → Tech Stack 아이템 리스트.

    매니페스트 미정의 카테고리는 ``tabular_ml`` 폴백.
    실제 ctx 의 ``model_selection.chosen`` 등이 있으면 호출 측에서 override 가능.
    """
    cat = _normalize_category(category)
    return list(TECH_STACK_BY_CATEGORY.get(cat, TECH_STACK_BY_CATEGORY[CATEGORY_TABULAR_ML]))


def resolve_slide(slide_role: str, category: Optional[str]) -> Optional[SlideVariant]:
    """슬라이드 역할 + 카테고리 → SlideVariant.

    ``slide_role`` 은 골격 슬라이드 ID 가 아니라 *의미 단위* (예: ``shap_global``).
    매니페스트 미정의 역할은 ``None`` 반환 — 호출 측이 골격 디폴트 사용.
    """
    cat = _normalize_category(category)
    role_map = SLIDE_SUBSTITUTIONS.get(slide_role)
    if not role_map:
        return None
    return role_map.get(cat) or role_map.get(CATEGORY_TABULAR_ML)


def resolve_verdict_tone(verdict: Optional[str]) -> VerdictTone:
    """verdict 문자열 → 어조 템플릿. 미정/미지원 verdict 는 ``adopt`` 폴백."""
    v = (verdict or "").strip().lower()
    return VERDICT_TONES.get(v, VERDICT_TONES["adopt"])


def is_metric_compatible(category: Optional[str], metric_name: str) -> bool:
    """카테고리 ↔ metric 호환성 체크 (typed schema assert).

    호환 X 시 호출 측이 fallback 변형 슬라이드로 스왑하도록 신호.
    """
    cat = _normalize_category(category)
    name = (metric_name or "").strip().lower()
    allowed = METRIC_FAMILY_BY_CATEGORY.get(cat, METRIC_FAMILY_BY_CATEGORY[CATEGORY_TABULAR_ML])
    return name in allowed


def check_required_ctx_fields(variant: SlideVariant, ctx: Any) -> list[str]:
    """SlideVariant 의 필수 ctx 필드 충족 여부 — 미충족 필드 리스트 반환.

    빈 리스트면 모두 충족. 비어있지 않으면 호출 측이 fallback 변형 트리거.

    ``ctx`` 는 ReportContext 인스턴스. 필드 경로는 점 표기 (``eda.charts``).
    """
    missing: list[str] = []
    for path in variant.required_ctx_fields:
        cur: Any = ctx
        ok = True
        for part in path.split("."):
            cur = getattr(cur, part, None)
            if cur is None:
                ok = False
                break
        if not ok:
            missing.append(path)
            continue
        # 리스트·dict 의 비어있음 도 미충족으로 간주
        if isinstance(cur, (list, dict)) and len(cur) == 0:
            missing.append(path)
    return missing


__all__ = [
    "CATEGORY_TABULAR_ML",
    "CATEGORY_TABULAR_DL",
    "CATEGORY_TIMESERIES",
    "CATEGORY_ANOMALY",
    "SUPPORTED_CATEGORIES",
    "TechStackItem",
    "SlideVariant",
    "VerdictTone",
    "TECH_STACK_BY_CATEGORY",
    "SLIDE_SUBSTITUTIONS",
    "VERDICT_TONES",
    "METRIC_FAMILY_BY_CATEGORY",
    "resolve_tech_stack",
    "resolve_slide",
    "resolve_verdict_tone",
    "is_metric_compatible",
    "check_required_ctx_fields",
]
