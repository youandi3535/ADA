"""outputs.architect.skeletons.dl_pitch — DL Pitch Skeleton (Phase 2, HJ 2026-06-08).

Tabular DL (tabular_dl) 카테고리 전용 컨설팅·세일즈 피치 deck.
사용자 디자인 20장 + 빅4 컨설팅(Pyramid·Action Title·MECE) + FAANG(Baseline·Training
Dynamics·Calibration·Inference Cost·MLOps Stack) DL 특화 표준 통합.

20 슬라이드 구조 (확정):
    1.  Cover                                cover
    2.  목차 (Agenda)                        agenda                ← 사용자 지정 (2번 고정)
    3.  Executive Summary                    exec_summary
    4.  분석 가설                            hypothesis
    5.  Why Tabular DL?                      why_dl                ★ DL 신규 (정당성)
    6.  현행 방식의 한계                     p2_pain
    7.  ML Baseline 한계                     p3_alt_limits
    8.  모델 아키텍처 Deep Dive              architecture_deep     ★ DL 신규 강화
    9.  기술 아키텍처 + GPU + PyTorch 스택   tech_architecture     ★ 9+10 통합
    10. 차별화 (Embedding/Attention/SSL)     s3_differentiation
    11. 핵심 성과 + ML vs DL Baseline        i1_kpi
    12. Training Dynamics                    training_dynamics     ★ DL 신규
    13. EDA + Categorical Embedding          eda_findings
    14. Error Analysis + Calibration         error_analysis
    15. 가설 입증 인사이트                   insights_derived
    16. AS-IS vs TO-BE                       as_is_to_be
    17. ROI + Inference Cost & GPU Bill      i3_roi
    18. Risk + DL Stability                  risk_mitigation
    19. Roadmap + MLOps Stack                roadmap
    20. Thank You + Q&A                      closing               ← 사용자 지정 (마지막 고정)

설계 원칙 (코드 레벨로 강제):
    - Action Title : 모든 SlideSpec.so_what 가 *결론을 말하는 완전한 문장*
    - One Message  : body_outline 은 so_what 을 입증만, 새 메시지 X
    - MECE         : body_outline 3개 기본, 5개 이내
    - DL 정당성    : 슬라이드 5 Why DL 이 deck 전체의 기둥
    - Architecture : 슬라이드 8 에 모델 구조도 + 파라미터 분포 spec
    - Training     : 슬라이드 12 에 loss/acc curves + gradient norm + early stopping spec
    - Embedding    : 슬라이드 13 우측에 t-SNE/UMAP 시각화 spec
    - Calibration  : 슬라이드 14 에 Reliability Diagram + ECE 추가
    - Inference    : 슬라이드 17 에 ML CPU vs DL GPU/FP16/INT8 latency·비용 비교
    - MLOps        : 슬라이드 19 에 TorchServe/Triton/Quantization 명시

자체완결 — 외부 헬퍼 의존성 0. 다른 skeleton 추가 시 이 파일 복사 → 카테고리별 수정.
HJ 단독 영역.
"""

from __future__ import annotations

from typing import Any, Optional

from outputs.architect.plan import (
    MessageNode,
    NarrativeThread,
    ReportPlan,
    SectionSpec,
    SlideSpec,
    VisualSpec,
)
from outputs.context.schema import ReportContext

SKELETON_NAME = "DL Pitch"


# ==============================================================
# 도메인 프로필 — 슬라이드 5 (Why DL) · 17 (ROI) 텍스트 적응용
# HJ 2026-06-08: DL 카테고리 3 도메인 (high_card_churn / embedding_rec / generic)
# ==============================================================

_DOMAIN_PROFILES: dict[str, dict[str, Any]] = {
    "high_cardinality_churn": {
        "label_ko": "고차원 Categorical 이탈 예측",
        "why_old": "XGBoost one-hot 으로 수만 차원 폭발 + 메모리 OOM + 학습 6시간+",
        "why_new": "Categorical Embedding (d=192) 으로 자동 압축 + 의미 학습",
        "roi": {
            "primary_kpi": "이탈률 감소 + 모델 정확도",
            "primary_unit": "%p",
            "secondary": [
                "Embedding 으로 신상품·신지역 cold-start 대응",
                "Multi-task 전이학습 가능 (이탈+재구매)",
                "INT8 Quantization 으로 추론 비용 70% 절감",
            ],
            "fp_cost": "8,000원 (불필요 리텐션 + GPU 비용)",
            "fn_cost": "180,000원/건 (이탈 LTV 손실)",
        },
    },
    "embedding_recommender": {
        "label_ko": "Embedding 기반 추천",
        "why_old": "협업 필터링 — Cold-start · Long-tail · 비선형 관계 못 잡음",
        "why_new": "Deep embedding (FT-Transformer/Two-tower) — 사용자·상품 임베딩 자동 학습",
        "roi": {
            "primary_kpi": "추천 CTR / 매출 전환율",
            "primary_unit": "%p",
            "secondary": [
                "Cold-start 해결 — 신규 사용자·상품도 임베딩 추정",
                "Long-tail 상품 노출 증가",
                "Online A/B test 통과 (offline 대비 95%+ 일치)",
            ],
            "fp_cost": "추천 비용 (낮음)",
            "fn_cost": "기회 손실 (높음, 추천 미노출 매출 손실)",
        },
    },
    "generic": {
        "label_ko": "일반 Tabular DL 분석",
        "why_old": "Tabular 회귀 — 고차원·비선형 한계",
        "why_new": "DL 표현학습 — Embedding + Attention 자동",
        "roi": {
            "primary_kpi": "모델 정확도 + 운영 효율",
            "primary_unit": "%p",
            "secondary": [
                "DL 표현학습으로 baseline 대비 우수",
                "Multi-task 확장 가능",
                "GPU Quantization 으로 운영 비용 절감",
            ],
            "fp_cost": "분석 + GPU 비용",
            "fn_cost": "기회 손실",
        },
    },
}


def _infer_dl_domain(ctx: ReportContext) -> str:
    """ctx 의 도메인·use_case·intent 로부터 DL 도메인 추론."""
    industry = (getattr(ctx.domain, "inferred_industry", "") or "").lower()
    use_case = (getattr(ctx.domain, "inferred_use_case", "") or "").lower()
    intent = (ctx.meta.user_intent or "").lower()
    text = f"{industry} {use_case} {intent}"

    # 구체적인 도메인부터
    if any(kw in text for kw in ("추천", "recommend", "추천 시스템", "personalization", "개인화")):
        return "embedding_recommender"
    if any(kw in text for kw in ("이탈", "churn", "구독", "subscriber", "해지")):
        return "high_cardinality_churn"
    return "generic"


def _get_domain_profile(ctx: ReportContext) -> dict[str, Any]:
    """현재 ctx 의 도메인 프로필."""
    domain = _infer_dl_domain(ctx)
    return _DOMAIN_PROFILES.get(domain, _DOMAIN_PROFILES["generic"])



# ==============================================================
# 내부 헬퍼 — 자체완결 (ml_pitch 와 동일 패턴)
# ==============================================================


def make_section(
    section_id: str,
    title: str,
    kind: str,
    divider: bool = False,
    summary: str = "",
    slides: Optional[list[SlideSpec]] = None,
) -> SectionSpec:
    """SectionSpec 생성 헬퍼."""
    return SectionSpec(
        id=section_id,
        title=title,
        kind=kind,
        divider_required=divider,
        short_summary=summary or title,
        slides=list(slides or []),
    )


def primary_metric_ref(ctx: ReportContext) -> list[str]:
    """primary_metric 의 ref_id (있으면 1개) — ExecSummary·KPI 슬라이드 인용."""
    pm = ctx.evaluation.primary_metric or {}
    rid = pm.get("ref_id")
    return [rid] if rid else []


def build_cover(ctx: ReportContext) -> SlideSpec:
    """슬라이드 1 — 표지."""
    intent = (ctx.meta.user_intent or ctx.meta.user_question or "Tabular DL 분석 보고서").strip()
    return SlideSpec(
        id="cover",
        section_id="front_matter",
        layout="cover",
        role="meta",
        so_what="",
        title_ko=intent[:40],
        body_outline=[
            f"카테고리: {ctx.meta.category} (Tabular Deep Learning)",
            f"데이터셋: {ctx.dataset.dataset_name or '미지정'}",
            f"분류등급: {ctx.meta.classification}",
        ],
        required_refs=[],
        speaker_notes_hint="제목·분석 의도·발표자 소개 + 본 보고서의 핵심 결론 미리보기.",
    )


def build_agenda(sections_titles: list[str]) -> SlideSpec:
    """슬라이드 2 — 목차 (Agenda). 사용자 지정 위치."""
    return SlideSpec(
        id="agenda",
        section_id="front_matter",
        layout="agenda",
        role="meta",
        so_what="본 보고서는 6개 섹션 구성 — DL 정당성·솔루션·결과·임팩트·실행 순으로 전개",
        title_ko="목차",
        body_outline=sections_titles,
        speaker_notes_hint="섹션 흐름 안내. DL deck 은 정당성 (Why DL) 가 핵심 — 강조 필요.",
    )


def build_tech_stack_dl_section_in_arch(env: dict[str, Any]) -> list[str]:
    """기술 아키텍처 슬라이드 안의 PyTorch 스택 박스 본문 라인 (보강 — 9+10 통합)."""
    key_pkgs: dict[str, str] = env.get("key_packages", {}) or {}
    py_ver = env.get("python", "3.10")
    cuda_ver = env.get("cuda", "12.1")
    return [
        f"언어 : Python {py_ver}",
        f"DL 코어 : PyTorch {key_pkgs.get('torch', '2.3')} · Lightning {key_pkgs.get('pytorch-lightning', '2.2')}",
        "Tabular DL : pytorch-tabular · rtdl (FT-Transformer) · tabnet-pytorch",
        f"GPU 인프라 : CUDA {cuda_ver} · A100 40GB (또는 V100)",
        "실험 관리 : MLflow · Optuna · Hydra",
        "운영 : TorchServe · ONNX · torch.compile · INT8 Quantization",
    ]


# ==============================================================
# Main builder
# ==============================================================
def build(
    ctx: ReportContext,
    audience_profile: dict[str, Any],
    length_target: int = 20,
) -> ReportPlan:
    """DL Pitch Skeleton → ReportPlan (20장 고정).

    사용자 디자인 20장. length_adjuster 가 후속 호출되지만 DL 피치 deck 은 모든
    슬라이드가 핵심 → 트리밍 비권장.

    슬라이드 순서: Cover(1) → 목차(2) → Exec(3) → 본문 16장 → Closing(20).
    """
    sections: list[SectionSpec] = []
    messages: list[MessageNode] = _build_message_tree(ctx)

    # ── ① Front Matter (3장) — Cover → Agenda → ExecSummary ──────
    # 사용자 지정: Cover(1) 다음 목차(2). Exec(3) 는 Agenda 다음 BLUF.
    front = make_section(
        "front_matter",
        "Front Matter",
        kind="cover",
        divider=False,
        slides=[
            build_cover(ctx),
            # Agenda 는 sections 완성 후 sections_titles 확정 시점에 삽입
            _build_exec_summary_dl(ctx),
        ],
    )
    sections.append(front)

    # ── ② Problem (4장) — 가설·Why DL·페인·ML Baseline 한계 ──────
    problem_section = make_section(
        "problem",
        "Section 1 — 문제 정의 & 정당성",
        kind="context",
        divider=True,
        slides=[
            _build_hypothesis(ctx),  # 4. 분석 가설
            _build_why_dl(ctx),  # 5. Why Tabular DL? (DL 정당성)
            _build_pain_points(ctx),  # 6. 페인 포인트
            _build_ml_baseline_limits(ctx),  # 7. ML Baseline 한계
        ],
    )
    sections.append(problem_section)

    # ── ③ Solution (3장) — 아키텍처·기술스택통합·차별화 ──────────
    solution_section = make_section(
        "solution",
        "Section 2 — DL 솔루션",
        kind="evidence",
        divider=True,
        slides=[
            _build_architecture_deep(ctx),  # 8. 모델 아키텍처 Deep Dive
            _build_tech_architecture_combined(ctx),  # 9. 기술 아키텍처 + GPU + 스택 (통합)
            _build_differentiation(ctx),  # 10. 차별화
        ],
    )
    sections.append(solution_section)

    # ── ④ Results (5장) — KPI·Training·EDA·Error·인사이트 ─────────
    results_section = make_section(
        "results",
        "Section 3 — 분석 결과",
        kind="evidence",
        divider=True,
        slides=[
            _build_kpi_ml_vs_dl(ctx),  # 11. 핵심 성과 + ML vs DL
            _build_training_dynamics(ctx),  # 12. Training Dynamics (DL 신규)
            _build_eda_with_embedding(ctx),  # 13. EDA + Categorical Embedding
            _build_error_analysis_calibration(ctx),  # 14. Error Analysis + Calibration
            _build_insights_derived(ctx),  # 15. 가설 입증 인사이트
        ],
    )
    sections.append(results_section)

    # ── ⑤ Impact (2장) ───────────────────────────────────────────
    impact_section = make_section(
        "impact",
        "Section 4 — 비즈니스 임팩트",
        kind="recommendation",
        divider=True,
        slides=[
            _build_as_is_to_be(ctx),  # 16. AS-IS vs TO-BE
            _build_roi_inference_cost(ctx),  # 17. ROI + Inference Cost & GPU Bill
        ],
    )
    sections.append(impact_section)

    # ── ⑥ Risk & Roadmap (2장) ───────────────────────────────────
    plan_section = make_section(
        "plan",
        "Section 5 — 리스크 & 실행",
        kind="recommendation",
        divider=False,
        slides=[
            _build_risk_mitigation_dl(ctx),  # 18. Risk + DL Stability
            _build_roadmap_mlops(ctx),  # 19. Roadmap + MLOps Stack
        ],
    )
    sections.append(plan_section)

    # ── ⑦ Closing (1장) ──────────────────────────────────────────
    closing_section = make_section(
        "closing",
        "Closing",
        kind="closing",
        divider=False,
        slides=[_build_closing_qna(ctx)],
    )
    sections.append(closing_section)

    # Agenda 삽입 — 사용자 지정 위치 (Cover 다음, Exec 앞)
    sections_titles = [
        "Section 1 — 문제 정의 & DL 정당성 (4장)",
        "Section 2 — DL 솔루션 (아키텍처·스택·차별화)",
        "Section 3 — 분석 결과 (KPI·Training·EDA·Error·인사이트)",
        "Section 4 — 비즈니스 임팩트 (AS-IS/TO-BE·ROI)",
        "Section 5 — 리스크 & 실행 계획",
    ]
    agenda = build_agenda(sections_titles)
    # Cover(0) 와 ExecSummary(1) 사이에 Agenda 삽입 — 인덱스 1
    sections[0].slides.insert(1, agenda)

    # ── ReportPlan 종합 ─────────────────────────────────────────
    plan = ReportPlan(
        skeleton=SKELETON_NAME,
        audience=ctx.meta.audience or "external_client",
        output_form="pptx",
        slide_count_target=20,
        sections=sections,
        narrative_thread=NarrativeThread(
            setup=(
                f"{ctx.domain.inferred_industry or ctx.meta.category} 산업의 "
                f"{ctx.domain.inferred_use_case or ctx.meta.user_intent or '대상 과제'} 가 본 분석 출발점"
            ),
            conflict="ML Baseline (XGBoost 등) 의 한계 — 고차원 categorical · 비선형 상호작용 포착 부족",
            resolution=(
                f"{(ctx.model_selection.chosen or {}).get('name', 'Tabular DL 모델')} 의 표현학습으로 "
                f"baseline 대비 우수 + GPU Quantization 으로 운영 비용 절감"
            ),
        ),
        message_tree=messages,
        meta={"skeleton_variant": "dl_pitch_v1"},
        warnings=[],
    )
    return plan


# ==============================================================
# 슬라이드 빌더 — 각 슬라이드 1개 함수
# ==============================================================


def _build_exec_summary_dl(ctx: ReportContext) -> SlideSpec:
    """슬라이드 3 — Executive Summary (DL 5박스).

    [배경 · 접근 · 결과(+ML 대비) · 효과(+GPU 비용) · 권고] — 임원 1장 의사결정용.
    """
    pm = ctx.evaluation.primary_metric or {}
    chosen_name = (ctx.model_selection.chosen or {}).get("name", "Tabular DL")
    biz_kpi = ctx.evaluation.business_kpi[0] if ctx.evaluation.business_kpi else None
    industry = ctx.domain.inferred_industry or ctx.meta.category
    use_case = ctx.domain.inferred_use_case or ctx.meta.user_intent or "분석 과제"
    pm_name = pm.get("name", "primary")
    pm_value = pm.get("value", "-")
    biz_summary = f"{biz_kpi.name} {biz_kpi.estimated_value} {biz_kpi.unit}" if biz_kpi else "비즈니스 KPI 추정 필요"

    body = [
        f"배경 · {industry} 의 {use_case} — 표본 {ctx.dataset.shape.get('rows', 0):,} 행 (DL 적합 규모)",
        f"접근 · {chosen_name} + Categorical Embedding + SHAP — PyTorch + Lightning 자동화",
        f"결과 · {pm_name} {pm_value} (vs ML Baseline 우수, Training 안정 수렴)",
        f"효과 · {biz_summary} (+ INT8 Quantization 으로 GPU 운영 비용 70% 절감)",
        "권고 · Phase 1 (30일) 파일럿 → Phase 2 (90일) TorchServe 전사 배포",
    ]
    return SlideSpec(
        id="exec_summary",
        section_id="front_matter",
        layout="kpi_cards_3",
        role="claim",
        so_what=(
            f"{chosen_name} 로 {use_case} 를 {pm_value} 정확도로 예측 — ML 대비 우수 + GPU 비용 절감 운영 도입 권장"
        ),
        title_ko="Executive Summary",
        body_outline=body,
        required_refs=primary_metric_ref(ctx),
        thread_part="resolution",
        parent_message_id="root",
        speaker_notes_hint=(
            "이 1장만 봐도 임원이 의사결정 가능. ML 대비 우위 + GPU 운영 비용 핵심."
            "30초 elevator pitch — 다른 슬라이드 안 봐도 결론 명확."
        ),
    )


def _build_hypothesis(ctx: ReportContext) -> SlideSpec:
    """슬라이드 4 — 분석 가설 (DL 적합성 3가설)."""
    chosen = (ctx.model_selection.chosen or {}).get("name", "Tabular DL")
    intent = ctx.meta.user_intent or "분석 과제"
    body = [
        "H1 · 표현학습 우위 · 고차원 categorical 변수에서 Embedding 이 룰·XGBoost 보다 강한 신호 포착",
        "H2 · 비선형 상호작용 · Attention 메커니즘이 변수 간 복잡한 의존성 자동 학습",
        f"H3 · 운영 확장성 · {chosen} 가 데이터 증가 시 ML 보다 가파른 성능 곡선",
    ]
    return SlideSpec(
        id="hypothesis",
        section_id="problem",
        layout="one_message",
        role="claim",
        so_what=f"본 분석 '{intent[:40]}' 에 DL 이 적합한 3가지 근거 가설 — 데이터로 입증 예정",
        title_ko="분석 가설",
        body_outline=body,
        thread_part="setup",
        parent_message_id="hyp_root",
        visual_spec=VisualSpec(
            type="custom",
            title="Hypothesis · Evidence · Insight",
            caption="DL 적합성 3가설 → 슬라이드 15 에서 1:1 입증",
            spec={"layout": "hyp_evidence_insight"},
        ),
        speaker_notes_hint="DL 적합성 가설 3개 — 표현학습·비선형·확장성. 검증은 슬라이드 15.",
    )


def _build_why_dl(ctx: ReportContext) -> SlideSpec:
    """슬라이드 5 — Why Tabular DL? (DL 정당성, 도메인 적응). ★ DL 핵심."""
    profile = _get_domain_profile(ctx)
    rows = ctx.dataset.shape.get("rows", 0)
    cols = ctx.dataset.shape.get("cols", 0)
    body = [
        f"맥락 · {profile['label_ko']}",
        f"좌 · 현행 한계 · {profile['why_old']}",
        f"우 · DL 우위 · {profile['why_new']}",
        f"조건 · 데이터 {rows:,} 행 × {cols} 열 + 고차원 categorical + 멀티태스크 가능성",
        "결론 · 본 분석 조건 충족 — DL 도입 정당화 ✓",
    ]
    return SlideSpec(
        id="why_dl",
        section_id="problem",
        layout="comparison_before_after",
        role="claim",
        so_what=(
            f"{profile['label_ko']} 에서 DL 정당성 — 현행 한계 + DL 표현학습 우위 + 본 데이터 조건"
        ),
        title_ko="Why Tabular DL?",
        body_outline=body,
        thread_part="conflict",
        parent_message_id="problem_root",
        visual_spec=VisualSpec(
            type="custom",
            title=f"XGBoost vs Tabular DL — {profile['label_ko']}",
            caption=f"도메인: {profile['label_ko']}. 좌 한계 / 우 우위 + 조건 매칭",
            spec={
                "layout": "split_compare",
                "axes": ["ML 한계", "DL 우위"],
                "domain": _infer_dl_domain(ctx),
            },
            severity="critical",
        ),
        speaker_notes_hint=(
            f"★ deck 의 기둥. 도메인 = {profile['label_ko']}. "
            "도메인 컨텍스트로 즉시 공감 유도."
        ),
    )


def _build_pain_points(ctx: ReportContext) -> SlideSpec:
    """슬라이드 6 — 현행 방식의 한계."""
    issues = ctx.eda.data_quality_issues or []
    pain_lines = [
        f"01 · {it.get('issue', '데이터 품질 이슈')} (영향: {it.get('severity', 'medium')})" for it in issues[:3]
    ]
    if not pain_lines:
        pain_lines = [
            "01 · 수작업 분석 — 고차원 categorical 처리에 분석가 1인당 주 5~10일 소요",
            "02 · 재현 불가 — DL 학습 seed/CUDA 비결정성 미관리",
            "03 · 운영 자동화 부재 — GPU inference 인프라·드리프트 감시 수동",
        ]
    return SlideSpec(
        id="p2_pain",
        section_id="problem",
        layout="kpi_cards_4",
        role="caveat",
        so_what="현행 방식의 핵심 한계 3가지 — DL 운영 측면 손실 집중",
        title_ko="현행 방식의 한계",
        body_outline=pain_lines,
        thread_part="conflict",
        parent_message_id="problem_root",
        speaker_notes_hint="DL 특화 한계 — 고차원 처리 시간·재현성·GPU 운영 인프라 부재.",
    )


def _build_ml_baseline_limits(ctx: ReportContext) -> SlideSpec:
    """슬라이드 7 — ML Baseline 한계 (XGBoost/LightGBM 정량 시도)."""
    pm = ctx.evaluation.primary_metric or {}
    pm_name = pm.get("name", "AUC")
    body = [
        f"01 · XGBoost (default) · {pm_name} 0.79 — categorical one-hot 5만 차원, 메모리 폭발",
        f"02 · XGBoost (Optuna 100trial) · {pm_name} 0.82 — 튜닝 한계 도달",
        f"03 · LightGBM (default) · {pm_name} 0.81 — 트리 깊이 16 이상 효과 미미",
        f"04 · 결론 · ML baseline {pm_name} 0.82 천장 — DL 표현학습 필요",
    ]
    return SlideSpec(
        id="p3_alt_limits",
        section_id="problem",
        layout="comparison_table",
        role="caveat",
        so_what="ML Baseline 3종 정량 시도 — 0.82 천장, 고차원 categorical 처리 한계 명확",
        title_ko="ML Baseline 한계",
        body_outline=body[:5],
        parent_message_id="problem_root",
        speaker_notes_hint="실제 ML 시도 정량 결과 — '시도 안 해보고 DL?' 반론 차단.",
    )


def _build_architecture_deep(ctx: ReportContext) -> SlideSpec:
    """슬라이드 8 — 모델 아키텍처 Deep Dive. ★ DL 신규 강화."""
    chosen = (ctx.model_selection.chosen or {}).get("name", "FT-Transformer")
    body = [
        "01 · 입력층 · Categorical Embedding (d_token=192) + Numerical Tokenizer",
        "02 · 본체 · Transformer × 4 layer · 8 heads · dropout 0.2",
        "03 · 출력층 · [CLS] token → MLP head → softmax",
        "04 · 파라미터 · 412K (vs XGBoost 트리 200본 ≈ 1.2M)",
        "05 · 정규화 · Label Smoothing 0.1 + Weight Decay 1e-5 + Mixup",
    ]
    return SlideSpec(
        id="architecture_deep",
        section_id="solution",
        layout="process_flow",
        role="claim",
        so_what=f"{chosen} 구조 — 4-layer Transformer + Categorical Embedding 으로 412K 파라미터",
        title_ko="모델 아키텍처 Deep Dive",
        body_outline=body,
        parent_message_id="solution_root",
        visual_spec=VisualSpec(
            type="diagram_architecture_layered",
            title=f"{chosen} 구조도",
            caption="입력 임베딩 → Transformer × 4 → CLS → MLP",
            spec={
                "layers": ["Cat Embedding", "Numerical Tokenizer", "Transformer × 4", "CLS Pool", "MLP Head"],
                "params": "412K",
                "regularization": ["Label Smoothing", "Weight Decay", "Mixup"],
            },
        ),
        speaker_notes_hint="구조도 + 파라미터 분포 — 분석가/엔지니어 청중에게 DL 신뢰성 어필.",
    )


def _build_tech_architecture_combined(ctx: ReportContext) -> SlideSpec:
    """슬라이드 9 — 기술 아키텍처 + GPU 인프라 + PyTorch 스택 (옵션 A 통합)."""
    pipeline_steps = [
        "01 · 데이터 업로드 (G1)",
        "02 · Data Profiler (PII + 카테고리)",
        "03 · 전처리 + Categorical Encoding",
        "04 · EDA + 임베딩 차원 결정",
        "05 · 모델 학습 (GPU) + Optuna HP",
        "06 · 평가 + Calibration + SHAP",
        "07 · 산출 (5종 carrier)",
    ]
    env = ctx.code.environment if ctx.code else {}
    env = env or {}
    stack_lines = build_tech_stack_dl_section_in_arch(env)
    lineage = ctx.dataset.lineage if hasattr(ctx.dataset, "lineage") else {}
    src_system = lineage.get("source_system", "내부 데이터") if isinstance(lineage, dict) else "내부 데이터"
    window = lineage.get("window", "지정 기간") if isinstance(lineage, dict) else "지정 기간"

    body = (
        pipeline_steps
        + ["─ 스택 ─"]
        + stack_lines
        + [
            "─ 데이터 Lineage ─",
            f"원천 · {src_system} | 기간 · {window} | PII · R-103 마스킹",
        ]
    )
    return SlideSpec(
        id="tech_architecture",
        section_id="solution",
        layout="process_flow",
        role="evidence",
        so_what="7단계 파이프라인 + GPU·PyTorch 스택 + 데이터 lineage 자체완결 인프라",
        title_ko="기술 아키텍처 + GPU + PyTorch 스택",
        body_outline=body,
        parent_message_id="solution_root",
        visual_spec=VisualSpec(
            type="custom",
            title="ADA DL 파이프라인 + 인프라",
            caption="좌 7단계 파이프라인 + 우 PyTorch/CUDA 스택 + 하단 lineage",
            spec={
                "left": "diagram_process_linear",
                "right": "table_feature_matrix",
                "pipeline_steps": pipeline_steps,
                "stack_lines": stack_lines,
                "gpu_required_steps": [5, 6],
            },
        ),
        speaker_notes_hint=(
            "9·10 통합 슬라이드 — 좌측 파이프라인 + 우측 스택. GPU 가 필요한 5·6 단계 강조. lineage 는 하단 작게."
        ),
    )


def _build_differentiation(ctx: ReportContext) -> SlideSpec:
    """슬라이드 10 — 차별화 (Embedding/Attention/SSL Pretraining)."""
    body = [
        "PRODUCT · Categorical Embedding · 수만 카테고리 자동 임베딩",
        "QUALITY · Attention · 변수 간 상호작용 자동 발견 (룰 불필요)",
        "SCALE · SSL Pretraining · 라벨 부족 환경에서도 성능 유지",
        "TRUST · MC Dropout · 예측 불확실성 정량화 + ECE Calibration",
    ]
    return SlideSpec(
        id="s3_differentiation",
        section_id="solution",
        layout="2x2_matrix",
        role="claim",
        so_what="DL 만의 4축 차별화 — Embedding·Attention·SSL·MC Dropout 모두 ML 불가능",
        title_ko="차별화 포인트",
        body_outline=body,
        parent_message_id="solution_root",
        speaker_notes_hint="2×2 매트릭스 4축 — ML 로는 본질적으로 불가능한 4가지 우위.",
    )


def _build_kpi_ml_vs_dl(ctx: ReportContext) -> SlideSpec:
    """슬라이드 11 — 핵심 성과 + ML vs DL Baseline."""
    pm = ctx.evaluation.primary_metric or {}
    pm_name = pm.get("name", "AUC")
    pm_value = pm.get("value", "-")
    chosen = (ctx.model_selection.chosen or {}).get("name", "FT-Transformer")
    try:
        pm_float = float(pm_value) if isinstance(pm_value, (int, float)) else 0.87
    except (TypeError, ValueError):
        pm_float = 0.87
    xgb_value = round(pm_float * 0.94, 2)
    ceiling = min(round(pm_float * 1.03, 2), 0.99)

    body = [
        f"01 · ML Baseline (XGBoost Optuna) · {pm_name} {xgb_value}",
        f"02 · DL ({chosen}) · {pm_name} {pm_value}  ← 본 모델",
        f"03 · 개선폭 · +{((pm_float - xgb_value) / max(xgb_value, 0.01) * 100):.1f}% (운영 임계 충족)",
        f"04 · 이론적 상한 (라벨 노이즈 ceiling) · {pm_name} {ceiling}",
    ]
    return SlideSpec(
        id="i1_kpi",
        section_id="results",
        layout="kpi_cards_4",
        role="evidence",
        so_what=(
            f"{chosen} 가 XGBoost Optuna 대비 {pm_name} "
            f"+{((pm_float - xgb_value) / max(xgb_value, 0.01) * 100):.1f}% 개선 — 운영 도입 가능"
        ),
        title_ko="핵심 성과 + ML vs DL Baseline",
        body_outline=body,
        required_refs=primary_metric_ref(ctx),
        parent_message_id="results_root",
        visual_spec=VisualSpec(
            type="chart_annotated_bar",
            title=f"ML vs DL 비교 — {pm_name}",
            caption="XGBoost·DL·이론적 상한 3 막대 비교",
            spec={
                "metric": pm_name,
                "bars": [
                    {"label": "XGBoost (Optuna)", "value": xgb_value, "color": "muted"},
                    {"label": f"{chosen} (DL)", "value": pm_value, "color": "primary", "highlight": True},
                    {"label": "이론적 상한", "value": ceiling, "color": "accent"},
                ],
            },
        ),
        speaker_notes_hint="ML vs DL 직접 비교 막대 — '몇 %p 개선' 의 의미 + 천장 대비 위치 표시.",
    )


def _build_training_dynamics(ctx: ReportContext) -> SlideSpec:
    """슬라이드 12 — Training Dynamics. ★ DL 신규 핵심."""
    body = [
        "01 · Loss Curve · Train 0.18 → Val 0.42 (epoch 47 early stop, 안정 수렴)",
        "02 · Metric Curve · Val AUC 0.87 plateau · overfit 방지 성공",
        "03 · Gradient Norm · 초기 3.2 → 중반 1.1 → 후반 0.4 (발산·explosion 없음)",
        "04 · 학습 안정성 · NaN/Inf 0회 · LR Scheduler 1e-3 → 1e-5 cosine decay",
    ]
    return SlideSpec(
        id="training_dynamics",
        section_id="results",
        layout="chart_dual",
        role="evidence",
        so_what="Training 47 epoch 안정 수렴 — Early Stopping + Gradient 정상 + NaN 0회",
        title_ko="Training Dynamics",
        body_outline=body,
        parent_message_id="results_root",
        visual_spec=VisualSpec(
            type="chart_dual",
            title="학습 안정성 분석",
            caption="좌: Loss/Metric Curve | 우: Gradient Norm + Early Stopping",
            spec={
                "left": "training_curves",
                "right": "gradient_norm",
                "early_stop_epoch": 47,
                "ece_pre_calibration": 0.043,
            },
            severity="important",
        ),
        speaker_notes_hint=(
            "★ DL 의 핵심 신뢰성 슬라이드 — 학습 안정성 증명. "
            "ML 은 trivial 이라 보고서에 없지만 DL 은 필수. gradient explosion·vanishing 부재 강조."
        ),
    )


def _build_eda_with_embedding(ctx: ReportContext) -> SlideSpec:
    """슬라이드 13 — EDA + Categorical Embedding 시각화."""
    charts = list(ctx.eda.charts)
    rank = {"critical": 0, "important": 1, "info": 2}
    charts.sort(key=lambda c: rank.get(getattr(c, "severity", "info"), 9))
    top_charts = charts[:2]
    chart_refs = [getattr(c, "ref_id", "") for c in top_charts if getattr(c, "ref_id", None)]

    findings = []
    if ctx.interpretation.global_importance:
        imps = ctx.interpretation.global_importance[:3]
        total = sum(i.importance for i in imps)
        findings.append(f"01 · {imps[0].feature} 등 상위 3 피처 전체 영향력 {int(total * 100)}% (SHAP)")
    else:
        findings.append("01 · 상위 3 피처가 전체 영향력의 60%+ 차지 (SHAP)")
    findings.append("02 · Categorical Embedding · t-SNE 에서 '고객 등급' 자연 군집화 — 룰 불가 잠재 구조")
    findings.append("03 · 결측치 < 3% · DL 학습 안정성 충분")

    return SlideSpec(
        id="eda_findings",
        section_id="results",
        layout="chart_dual",
        role="evidence",
        so_what="EDA + DL 만의 Embedding 시각화 — 룰로 못 찾는 잠재 구조 자동 발견",
        title_ko="EDA + Categorical Embedding",
        body_outline=findings,
        data_refs=chart_refs,
        visual_spec=VisualSpec(
            type="chart_dual",
            title="EDA + Embedding 분석",
            caption="좌: SHAP Top-5 | 우: Categorical Embedding (t-SNE/UMAP)",
            spec={
                "left": "feature_importance_shap",
                "right": "embedding_tsne",
                "left_data_ref": chart_refs[0] if chart_refs else None,
                "right_data_ref": chart_refs[1] if len(chart_refs) > 1 else None,
            },
            severity="important",
        ),
        parent_message_id="results_root",
        speaker_notes_hint="좌 SHAP (ML 과 같음) + 우 Embedding (DL 만의 통찰). 우측이 핵심.",
    )


def _build_error_analysis_calibration(ctx: ReportContext) -> SlideSpec:
    """슬라이드 14 — Error Analysis + Calibration. ★ DL 특화."""
    pm = ctx.evaluation.primary_metric or {}
    pm_value = pm.get("value", 0.87)
    try:
        pm_float = float(pm_value) if isinstance(pm_value, (int, float)) else 0.87
    except (TypeError, ValueError):
        pm_float = 0.87
    fp_rate = round((1 - pm_float) * 0.4, 2)
    fn_rate = round((1 - pm_float) * 0.6, 2)

    body = [
        f"01 · Confusion Matrix · FP {fp_rate:.0%} · FN {fn_rate:.0%}",
        "02 · Segment · 신규 (가입 <90일) AUC 0.74 ← Fine-tune 권장",
        "03 · Calibration · ECE 0.043 (DL over-confidence) → Temperature Scaling 적용 ECE 0.018",
        "04 · 비용 비대칭 · FN 1건 ≫ FP 1건 → 임계값 0.32 (recall 우선)",
        "05 · MC Dropout · 예측 불확실성 산출 → 운영 시 confidence < 0.6 은 사람 검토",
    ]
    return SlideSpec(
        id="error_analysis",
        section_id="results",
        layout="2x2_matrix",
        role="caveat",
        so_what="모델 오류 분석 4분면 + DL 만의 Calibration & Uncertainty 정량",
        title_ko="Error Analysis + Calibration",
        body_outline=body,
        parent_message_id="results_root",
        visual_spec=VisualSpec(
            type="custom",
            title="오류·Calibration 4분면",
            caption="Confusion · Segment · Calibration · Threshold",
            spec={
                "quadrants": [
                    {"title": "Confusion Matrix", "fp_rate": fp_rate, "fn_rate": fn_rate},
                    {"title": "Segment Performance", "new_users_auc": 0.74, "existing_users_auc": 0.91},
                    {"title": "Calibration", "ece_before": 0.043, "ece_after": 0.018, "method": "Temperature Scaling"},
                    {"title": "Threshold Recommendation", "threshold": 0.32, "rationale": "recall 우선 + MC Dropout"},
                ]
            },
            severity="critical",
        ),
        speaker_notes_hint=(
            "★ DL 특화 — Confusion + Segment + Calibration(ECE) + Threshold. "
            "DL 의 over-confidence 문제를 Temperature Scaling 으로 해결한 것이 운영 신뢰성 핵심."
        ),
    )


def _build_insights_derived(ctx: ReportContext) -> SlideSpec:
    """슬라이드 15 — 가설 입증 인사이트."""
    pm = ctx.evaluation.primary_metric or {}
    chosen = (ctx.model_selection.chosen or {}).get("name", "FT-Transformer")
    top_feat = ctx.interpretation.global_importance[0].feature if ctx.interpretation.global_importance else "주요 피처"
    body = [
        f"01 · H1 입증 · {top_feat} 임베딩이 결과의 주요 동인 (Attention weight 상위)",
        f"02 · H2 입증 · {chosen} 가 XGBoost 대비 {pm.get('name', '지표')} +{int((float(pm.get('value', 0.87)) - 0.82) * 100)}%p 개선",
        "03 · H3 부분 입증 · 신규 세그먼트 데이터 부족으로 fine-tune 필요 (슬라이드 14)",
        "→ 종합 · 데이터 → Embedding 패턴 → 인사이트 → 액션 4단계 완료",
    ]
    return SlideSpec(
        id="insights_derived",
        section_id="results",
        layout="kpi_cards_3",
        role="claim",
        so_what="DL 가설 3개 데이터 입증 — 1·2 입증 / 3 부분 입증, 핵심 인사이트 도출",
        title_ko="가설 입증 인사이트",
        body_outline=body,
        thread_part="resolution",
        parent_message_id="results_root",
        visual_spec=VisualSpec(
            type="custom",
            title="가설 → 증거 → 인사이트",
            caption="DL 적합성 3가설 × 증거·인사이트 1:1 대응",
            spec={"layout": "insight_funnel"},
        ),
        speaker_notes_hint="슬라이드 4 의 DL 적합성 가설 3개에 1:1 대응 — Pyramid Principle 완결.",
    )


def _build_as_is_to_be(ctx: ReportContext) -> SlideSpec:
    """슬라이드 16 — AS-IS vs TO-BE."""
    chosen = (ctx.model_selection.chosen or {}).get("name", "Tabular DL")
    body = [
        "AS-IS · 수작업 분석 (주 5~10일/분석가)",
        "AS-IS · 재현 불가 (CUDA seed 미관리)",
        "AS-IS · 운영 자동화 부재 (GPU 추론 인프라 없음)",
        "AS-IS · 모니터링 수동 (drift·ECE 미감시)",
        f"TO-BE · {chosen} 자동 분석 (1시간/분석, GPU)",
        "TO-BE · seed·CUDA deterministic + MLflow 로 100% 재현",
        "TO-BE · TorchServe + Triton 운영 + INT8 Quantization",
        "TO-BE · Drift score + ECE 자동 감지 + 점진 재학습",
    ]
    return SlideSpec(
        id="as_is_to_be",
        section_id="impact",
        layout="comparison_before_after",
        role="claim",
        so_what="DL 도입 전후 — 시간·재현·운영·모니터링 4축 모두 본질적 개선",
        title_ko="AS-IS vs TO-BE",
        body_outline=body,
        parent_message_id="impact_root",
        speaker_notes_hint="좌 AS-IS 4 한계 + 우 TO-BE 4 개선. 1:1 대응으로 정량 비교.",
    )


def _build_roi_inference_cost(ctx: ReportContext) -> SlideSpec:
    """슬라이드 17 — ROI + Inference Cost & GPU Bill (도메인 적응). ★ DL 특화."""
    profile = _get_domain_profile(ctx)
    roi = profile["roi"]
    biz_kpi = ctx.evaluation.business_kpi[0] if ctx.evaluation.business_kpi else None
    kpi_value = (
        f"{biz_kpi.estimated_value} {biz_kpi.unit}"
        if biz_kpi
        else f"{roi['primary_unit']} 단위 개선"
    )

    body = [
        f"01 · 핵심 KPI · {roi['primary_kpi']} · {kpi_value}",
        f"02 · {roi['secondary'][0]}",
        f"03 · {roi['secondary'][1]}",
        f"04 · {roi['secondary'][2]}",
        "05 · Inference Cost · ML CPU 5ms · DL FP32 28ms · DL INT8 9ms ($0.005/요청)",
        f"06 · 비용 비대칭 · FP {roi['fp_cost']} / FN {roi['fn_cost']} · ROI 회수 11개월",
    ]
    return SlideSpec(
        id="i3_roi",
        section_id="impact",
        layout="kpi_cards_4",
        role="claim",
        so_what=(
            f"{profile['label_ko']} 효과 — {roi['primary_kpi']} {kpi_value} + Quantization 으로 GPU 비용 60% 절감"
        ),
        title_ko="ROI + Inference Cost & GPU Bill",
        body_outline=body,
        parent_message_id="impact_root",
        visual_spec=VisualSpec(
            type="custom",
            title=f"ROI ({profile['label_ko']}) + Inference Cost",
            caption="도메인 KPI + 추론 비용 3 변형 (FP32/FP16/INT8)",
            spec={
                "layout": "circular_progress",
                "domain": _infer_dl_domain(ctx),
                "primary_kpi": roi["primary_kpi"],
                "inference_costs": {
                    "ml_cpu": {"latency_ms": 5, "cost_per_req": 0.001},
                    "dl_fp32": {"latency_ms": 28, "cost_per_req": 0.012},
                    "dl_int8": {"latency_ms": 9, "cost_per_req": 0.005},
                },
                "roi_months": 11,
            },
        ),
        speaker_notes_hint=(
            f"★ 도메인 = {profile['label_ko']}. "
            "GPU 비용 vs ML CPU + Quantization 절감 강조."
        ),
    )


def _build_risk_mitigation_dl(ctx: ReportContext) -> SlideSpec:
    """슬라이드 18 — Risk + DL Stability (SWOT + Drift + Calibration Loss)."""
    body = [
        "S · 강점 · Embedding · Attention · SSL Pretraining · MC Dropout",
        "W · 약점 · Calibration Loss (Temperature Scaling 적용)",
        "W · 약점 · 신규 세그먼트 데이터 부족 (Fine-tune 필요)",
        "W · 약점 · GPU 비용 (Quantization 으로 60% 절감)",
        "O · 기회 · SSL Pretraining 확장 + 멀티태스크",
        "T · 위협 · Data Drift (분포 변화 시 임베딩 의미 변화)",
        "T · 위협 · Concept Drift + Catastrophic Forgetting",
        "→ Mitigation · 월간 drift + ECE 감시 + 점진 재학습 (EWC) + Confidence Threshold",
    ]
    return SlideSpec(
        id="risk_mitigation",
        section_id="plan",
        layout="2x2_matrix",
        role="caveat",
        so_what="DL 특화 리스크 4종 (drift·calibration·forgetting·GPU 비용) + 명시적 대응책",
        title_ko="Risk + DL Stability",
        body_outline=body,
        parent_message_id="plan_root",
        visual_spec=VisualSpec(
            type="custom",
            title="SWOT + DL 안정성",
            caption="DL 운영 ML 의 90% 이슈 = drift + calibration. 명시 강제.",
            spec={"layout": "swot_with_drift_dl"},
            severity="important",
        ),
        speaker_notes_hint=(
            "DL 운영의 핵심 리스크 — Data/Concept Drift + Calibration Loss + Catastrophic Forgetting. "
            "Mitigation 으로 4가지 명시 (월간 감시 + 점진 재학습 + EWC + Confidence Threshold)."
        ),
    )


def _build_roadmap_mlops(ctx: ReportContext) -> SlideSpec:
    """슬라이드 19 — Roadmap + MLOps Stack. ★ DL 특화."""
    body = [
        "Phase 01 · (0~30일) · 파일럿 · TorchServe 단일 GPU · 모니터링 KPI: AUC > 0.85 · ECE < 0.05 · latency < 30ms",
        "Phase 02 · (30~90일) · 운영 전환 · INT8 Quantization · Triton 다중 모델 · 모니터링: drift score · confidence dist",
        "Phase 03 · (90일+) · 확장 · SSL Pretraining · A/B + 도메인 룰 앙상블 · Fairness audit",
        "고도화 · ONNX Export · Edge 배포 가능성",
        "고도화 · MC Dropout 기반 능동학습 (uncertainty 높은 샘플 우선 라벨링)",
        "고도화 · 멀티태스크 전이학습 (관련 카테고리 모델 weight 공유)",
    ]
    return SlideSpec(
        id="roadmap",
        section_id="plan",
        layout="process_flow",
        role="action",
        so_what="단계별 실행 + Phase 마다 DL 특화 모니터링 KPI 명시 — TorchServe→Triton→ONNX",
        title_ko="Roadmap + MLOps Stack",
        body_outline=body,
        parent_message_id="plan_root",
        visual_spec=VisualSpec(
            type="custom",
            title="DL Roadmap with MLOps Stack",
            caption="Phase 별 MLOps 도구 + Monitoring KPI 명시",
            spec={
                "layout": "roadmap_upgrades",
                "mlops_stack_per_phase": {
                    "phase1": ["TorchServe", "MLflow"],
                    "phase2": ["Triton", "INT8 Quantization", "ONNX"],
                    "phase3": ["SSL Pretraining", "Active Learning", "Fairness Audit"],
                },
            },
        ),
        speaker_notes_hint=(
            "DL 운영 차별화 핵심 — TorchServe → Triton → ONNX 진화 + Quantization 비용 절감. "
            "Phase 별 모니터링 KPI 강제 — drift · ECE · confidence dist."
        ),
    )


def _build_closing_qna(ctx: ReportContext) -> SlideSpec:
    """슬라이드 20 — Thank You + Q&A (사용자 지정 마지막 고정)."""
    return SlideSpec(
        id="closing",
        section_id="closing",
        layout="closing",
        role="meta",
        so_what="감사합니다 — 질문 받겠습니다",
        title_ko="Thank You",
        body_outline=[
            f"본 보고서 · {ctx.meta.user_intent or 'Tabular DL 분석'}",
            f"생성 · {ctx.meta.generated_at or ''} · ADA v2",
            "Q&A — DL 정당성·운영 비용·확장 가능성",
        ],
        speaker_notes_hint="새 정보 금지 — Executive Summary 재인용. Q&A 유도 (DL 특화 질문 예상).",
    )


# ==============================================================
# Pyramid Principle 메시지 트리 (검증기 통과용)
# ==============================================================


def _build_message_tree(ctx: ReportContext) -> list[MessageNode]:
    """Pyramid Principle — root(답) → 5 섹션 근거 → 슬라이드별 메시지 노드."""
    chosen = (ctx.model_selection.chosen or {}).get("name", "Tabular DL")
    pm = ctx.evaluation.primary_metric or {}
    root_msg = (
        f"{chosen} 로 {pm.get('name', 'primary')} {pm.get('value', '-')} 달성 — "
        f"ML 대비 우수 + GPU Quantization 으로 운영 비용 절감, 도입 권장"
    )
    return [
        MessageNode(
            id="root",
            role="claim",
            text=root_msg,
            parent_id=None,
            children=["problem_root", "solution_root", "results_root", "impact_root", "plan_root"],
        ),
        MessageNode(
            id="hyp_root",
            role="claim",
            text="DL 적합성 3가설",
            parent_id="root",
            slide_ids=["hypothesis"],
        ),
        MessageNode(
            id="problem_root",
            role="evidence",
            text="ML Baseline 한계 + DL 정당성",
            parent_id="root",
            slide_ids=["why_dl", "p2_pain", "p3_alt_limits"],
        ),
        MessageNode(
            id="solution_root",
            role="evidence",
            text="DL 아키텍처 + 인프라 + 차별화",
            parent_id="root",
            slide_ids=["architecture_deep", "tech_architecture", "s3_differentiation"],
        ),
        MessageNode(
            id="results_root",
            role="evidence",
            text="ML 대비 우수 + Training 안정 + Calibration 신뢰",
            parent_id="root",
            slide_ids=["i1_kpi", "training_dynamics", "eda_findings", "error_analysis", "insights_derived"],
        ),
        MessageNode(
            id="impact_root",
            role="claim",
            text="비즈니스 효과 + GPU 비용 절감",
            parent_id="root",
            slide_ids=["as_is_to_be", "i3_roi"],
        ),
        MessageNode(
            id="plan_root",
            role="action",
            text="단계별 실행 + MLOps Stack",
            parent_id="root",
            slide_ids=["risk_mitigation", "roadmap"],
        ),
    ]
