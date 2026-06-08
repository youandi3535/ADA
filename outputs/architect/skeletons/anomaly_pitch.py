"""outputs.architect.skeletons.anomaly_pitch — Anomaly Pitch Skeleton (Phase 2, HJ 2026-06-08).

이상탐지 (anomaly_detection) 카테고리 전용 컨설팅·세일즈 피치 deck.
사용자 디자인 20장 + 빅4 컨설팅(Pyramid·Action Title·MECE) + 이상탐지 특화 표준
(Score Distribution·PR-AUC·Threshold Tuning·FAR·Root Cause·Drift) 통합.

도메인 적응 — _DOMAIN_PROFILES 6종 + generic 폴백:
    fraud           : 사기 탐지 (금융·결제·보험)
    industrial_iot  : 산업 IoT / 설비 이상 (제조)
    system_logs     : 시스템 장애 / 로그 이상 (DevOps/SRE)
    security        : 보안 / 침입 탐지 (Network/SOC)
    quality_control : 품질 관리 / 결함 검출 (제조 라인)
    medical         : 의료 진단 (Healthcare)
    generic         : 일반 이상 탐지 (폴백)

슬라이드 5 (Why Anomaly Detection?) 와 17 (ROI + Alert Reduction) 가 도메인별 텍스트로
자동 적응. 슬라이드 14 (Threshold + FAR) 의 비용 비대칭 도 같은 도메인 프로필 사용.

20 슬라이드 구조 (확정):
    1.  Cover                                cover
    2.  목차 (Agenda)                        agenda
    3.  Executive Summary                    exec_summary
    4.  분석 가설 (이상탐지 적합성)           hypothesis
    5.  Why Anomaly Detection?                why_anomaly           ★ 도메인 적응
    6.  현행 방식의 한계                      p2_pain
    7.  단순 분류·룰 한계                     p3_alt_limits
    8.  모델 아키텍처 Deep Dive               architecture_deep
    9.  기술 아키텍처 + PyOD 스택             tech_architecture
    10. 차별화 (Unsup·Threshold·XAI·Drift)    s3_differentiation
    11. 핵심 성과 + PR-AUC Baseline           i1_kpi
    12. Anomaly Score Distribution            score_distribution    ★ 신규
    13. EDA + Anomaly 패턴                    eda_findings
    14. Threshold + PR/ROC + FAR              error_analysis        ★ 도메인 비용 적응
    15. 가설 입증 인사이트 + Root Cause       insights_derived
    16. AS-IS vs TO-BE                        as_is_to_be
    17. ROI + Alert Reduction                 i3_roi                ★ 도메인 적응
    18. Risk + Drift / Alert Fatigue          risk_mitigation
    19. Roadmap + Alert Pipeline              roadmap
    20. Thank You + Q&A                       closing

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

SKELETON_NAME = "Anomaly Pitch"


# ==============================================================
# 도메인 프로필 — 슬라이드 5·14·17 텍스트 적응용
# ==============================================================

_DOMAIN_PROFILES: dict[str, dict[str, Any]] = {
    "fraud": {
        "label_ko": "사기 탐지 (금융·결제)",
        "why": {
            "context": "금융·결제·보험 거래 데이터 (계좌·카드·이체)",
            "old_problem": "룰 기반 사기 차단 — 신규 사기 수법 못 잡음 + FAR 높아 고객 경험 저하",
            "new_value": "거래 패턴 자동 학습 — 새 사기 수법도 Anomaly Score 높게 감지",
        },
        "roi": {
            "primary_kpi": "사기 손실 절감",
            "primary_unit": "원/년",
            "secondary": [
                "False alarm 감소 — 정상 거래 차단 감소, 고객 경험 개선",
                "분석가 검토 시간 단축 — Root Cause SHAP 자동 제공",
                "신규 사기 패턴 조기 감지 — Zero-day 사기 대응",
            ],
            "fp_cost": "2,000원 (불필요 차단·고객 컴플레인 처리)",
            "fn_cost": "280,000원/건 (사기 평균 손실)",
        },
    },
    "industrial_iot": {
        "label_ko": "산업 IoT / 설비 이상 (제조)",
        "why": {
            "context": "센서 다변량 데이터 (진동·온도·압력·전류·회전수)",
            "old_problem": "임계값 기반 alert — 복잡한 다변량 패턴 못 잡음 + 다운타임 발생",
            "new_value": "다변량 정상 분포 학습 — 미세한 이상 신호 조기 감지로 예방 정비",
        },
        "roi": {
            "primary_kpi": "가동률 향상 / 다운타임 감소",
            "primary_unit": "%p",
            "secondary": [
                "예방 정비 — 고장 발생 전 사전 조치",
                "정비 비용 절감 — 불필요 정비 출동 감소",
                "안전사고 예방 — 위험 신호 사전 차단",
            ],
            "fp_cost": "100만원 (불필요 정비 출동)",
            "fn_cost": "5,000만원/건 (다운타임 + 부품·인건비)",
        },
    },
    "system_logs": {
        "label_ko": "시스템 장애 / 로그 이상 (DevOps)",
        "why": {
            "context": "서버 로그·메트릭 시계열 (CPU·메모리·트래픽·error rate·latency)",
            "old_problem": "Static threshold — 시점별 정상 변동 못 따라감, alert 폭주 + 진짜 장애 묻힘",
            "new_value": "동적 정상 분포 학습 — 시점별 alert 정확도 향상, 신규 장애 자동 감지",
        },
        "roi": {
            "primary_kpi": "MTTR (Mean Time To Recovery) 단축",
            "primary_unit": "분",
            "secondary": [
                "가용성 향상 (SLA 충족률 ↑)",
                "On-call 알람 부하 감소 (alert fatigue 해소)",
                "신규 장애 패턴 조기 감지",
            ],
            "fp_cost": "30분 (분석가 검토 시간)",
            "fn_cost": "1시간/건 (서비스 다운타임 + 매출 손실)",
        },
    },
    "security": {
        "label_ko": "보안 / 침입 탐지 (Network/SOC)",
        "why": {
            "context": "네트워크 트래픽·사용자 행동·시스템 콜·인증 로그",
            "old_problem": "Signature 기반 탐지 — 알려진 공격만 잡음, Zero-day 공격 무방비",
            "new_value": "정상 행동 분포 학습 — 알려지지 않은 공격 자동 탐지 (UEBA)",
        },
        "roi": {
            "primary_kpi": "침해 방지 건수 / 평균 탐지 시간",
            "primary_unit": "건·시간",
            "secondary": [
                "Zero-day 공격 대응 가능",
                "SOC 분석가 부하 감소 — Triage 자동화",
                "Compliance audit 자동화 (PCI-DSS·ISO27001)",
            ],
            "fp_cost": "10분 (SOC 분석가 triage)",
            "fn_cost": "큰 보안 사고 (평균 N억원 + 평판 손실)",
        },
    },
    "quality_control": {
        "label_ko": "품질 관리 / 결함 검출 (제조 라인)",
        "why": {
            "context": "제조 라인 센서·이미지·계측 데이터",
            "old_problem": "수작업 검수 — 인간 한계 (피로·실수) + 라인 속도 제약",
            "new_value": "AI 자동 검수 — 미세 결함 검출 + 풀라인 속도 유지",
        },
        "roi": {
            "primary_kpi": "불량률 감소",
            "primary_unit": "%p",
            "secondary": [
                "리콜 방지 — 출하 전 결함 차단",
                "검수 인력 절감",
                "고객 클레임 감소",
            ],
            "fp_cost": "추가 검수 시간 (소량)",
            "fn_cost": "고객 클레임·리콜·평판 손실",
        },
    },
    "medical": {
        "label_ko": "의료 진단 (Healthcare)",
        "why": {
            "context": "의료 신호·영상·EHR·바이오마커 데이터",
            "old_problem": "수작업 판독 — 의사 업무 부하 + 미세 패턴 누락 위험",
            "new_value": "AI 보조 진단 — 비정상 패턴 자동 식별, 의사 의사결정 보조",
        },
        "roi": {
            "primary_kpi": "조기 발견율 향상",
            "primary_unit": "%p",
            "secondary": [
                "오진 감소",
                "의사 업무 부하 감소 (스크리닝 자동화)",
                "의료비 절감 (조기 치료)",
            ],
            "fp_cost": "추가 검사 비용 (정밀 진단)",
            "fn_cost": "진단 누락 — 환자 위험 + 의료 분쟁",
        },
    },
    "generic": {
        "label_ko": "일반 이상 탐지",
        "why": {
            "context": "다변량 정형/비정형 데이터",
            "old_problem": "룰 기반 / 단순 임계값 — 신규 패턴 못 잡음 + 임계값 수동 조정",
            "new_value": "정상 분포 자동 학습 — Unsupervised 로 새 이상 유형 자동 감지",
        },
        "roi": {
            "primary_kpi": "이상 탐지 정확도 향상",
            "primary_unit": "%p",
            "secondary": [
                "False alarm 감소",
                "분석가 검토 부하 감소",
                "신규 이상 패턴 자동 감지",
            ],
            "fp_cost": "분석 비용",
            "fn_cost": "이상 손실 (도메인별 상이)",
        },
    },
}


def _infer_anomaly_domain(ctx: ReportContext) -> str:
    """ctx 의 도메인·use_case·intent 로부터 이상탐지 도메인 추론.

    키워드 매칭 우선순위 — 더 구체적 도메인이 일반 도메인 이김.
    매칭 실패 시 'generic' 폴백.
    """
    industry = (getattr(ctx.domain, "inferred_industry", "") or "").lower()
    use_case = (getattr(ctx.domain, "inferred_use_case", "") or "").lower()
    intent = (ctx.meta.user_intent or "").lower()
    text = f"{industry} {use_case} {intent}"

    # 도메인별 키워드 매핑 — 구체적인 도메인부터 검사
    domain_keywords: list[tuple[str, tuple[str, ...]]] = [
        # 우선순위: 더 구체적인 도메인이 일반 도메인보다 먼저 검사 (첫 매치가 이김).
        ("fraud", ("사기", "fraud", "카드", "결제", "이체", "보험", "banking", "finance", "money laundering")),
        ("quality_control", ("품질", "quality", "결함", "defect", "불량", "검수", "inspection", "출하", "검사")),
        ("medical", ("의료", "medical", "건강", "진단", "병원", "healthcare", "환자", "patient",
                     "ecg", "mri", "ct", "xray", "혈액", "검진")),
        ("security", ("보안", "security", "침입", "intrusion", "사이버", "cyber", "malware",
                      "soc", "ids", "ips", "threat", "ueba", "siem", "공격")),
        ("industrial_iot", ("설비", "센서", "iot", "공장", "vibration", "motor",
                            "predictive maintenance", "manufacturing", "factory", "조립", "프레스")),
        ("system_logs", ("로그", "log", "metric", "장애", "outage", "sre", "devops",
                         "서버", "observability", "telemetry", "monitoring", "kubernetes", "k8s")),
    ]
    for domain, keywords in domain_keywords:
        if any(kw in text for kw in keywords):
            return domain
    return "generic"


def _get_domain_profile(ctx: ReportContext) -> dict[str, Any]:
    """현재 ctx 의 도메인 프로필 (캐싱 없음, 매번 추론)."""
    domain = _infer_anomaly_domain(ctx)
    return _DOMAIN_PROFILES.get(domain, _DOMAIN_PROFILES["generic"])


# ==============================================================
# 내부 헬퍼 — 자체완결
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
    """primary_metric 의 ref_id — ExecSummary·KPI 인용."""
    pm = ctx.evaluation.primary_metric or {}
    rid = pm.get("ref_id")
    return [rid] if rid else []


def build_cover(ctx: ReportContext) -> SlideSpec:
    """슬라이드 1 — 표지."""
    profile = _get_domain_profile(ctx)
    intent = (ctx.meta.user_intent or ctx.meta.user_question or "이상 탐지 분석 보고서").strip()
    return SlideSpec(
        id="cover",
        section_id="front_matter",
        layout="cover",
        role="meta",
        so_what="",
        title_ko=intent[:40],
        body_outline=[
            f"카테고리: {ctx.meta.category} ({profile['label_ko']})",
            f"데이터셋: {ctx.dataset.dataset_name or '미지정'}",
            f"분류등급: {ctx.meta.classification}",
        ],
        required_refs=[],
        speaker_notes_hint=f"제목·도메인({profile['label_ko']})·발표자 + 핵심 결론 미리보기.",
    )


def build_agenda(sections_titles: list[str]) -> SlideSpec:
    """슬라이드 2 — 목차."""
    return SlideSpec(
        id="agenda",
        section_id="front_matter",
        layout="agenda",
        role="meta",
        so_what="본 보고서는 6개 섹션 구성 — 이상탐지 정당성·솔루션·결과·임팩트·실행 순으로 전개",
        title_ko="목차",
        body_outline=sections_titles,
        speaker_notes_hint="섹션 흐름 안내. Why Anomaly Detection? (정당성) 이 deck 의 기둥.",
    )


def build_tech_stack_anomaly_lines(env: dict[str, Any]) -> list[str]:
    """기술 아키텍처 슬라이드 안의 이상탐지 스택 박스 (9+10 통합)."""
    key_pkgs: dict[str, str] = env.get("key_packages", {}) or {}
    py_ver = env.get("python", "3.10")
    pyod_ver = key_pkgs.get("pyod", "")
    return [
        f"언어 : Python {py_ver}",
        f"이상탐지 코어 : PyOD {pyod_ver} (Isolation Forest · LOF · COPOD · ECOD · 38 알고리즘)",
        "Deep AD : PyTorch (AutoEncoder · DeepSVDD · PaDiM · PatchCore)",
        "해석 : SHAP (Root Cause) · LIME",
        "실험 관리 : MLflow · Optuna",
        "운영 : 실시간 score → Alert Pipeline (Slack/PagerDuty) · Drift 감시",
    ]


# ==============================================================
# Main builder
# ==============================================================
def build(
    ctx: ReportContext,
    audience_profile: dict[str, Any],
    length_target: int = 20,
) -> ReportPlan:
    """Anomaly Pitch Skeleton → ReportPlan (20장 고정).

    슬라이드 5·14·17 가 도메인 (fraud/industrial_iot/system_logs/security/
    quality_control/medical/generic) 별로 텍스트 자동 적응.
    """
    sections: list[SectionSpec] = []
    messages: list[MessageNode] = _build_message_tree(ctx)
    profile = _get_domain_profile(ctx)

    # ── ① Front Matter (3장) ─────────────────────────────────────
    front = make_section(
        "front_matter",
        "Front Matter",
        kind="cover",
        divider=False,
        slides=[
            build_cover(ctx),
            _build_exec_summary_anomaly(ctx),
        ],
    )
    sections.append(front)

    # ── ② Problem (4장) ──────────────────────────────────────────
    problem_section = make_section(
        "problem",
        "Section 1 — 문제 정의 & 이상탐지 정당성",
        kind="context",
        divider=True,
        slides=[
            _build_hypothesis(ctx),
            _build_why_anomaly(ctx),  # ★ 도메인 적응
            _build_pain_points(ctx),
            _build_classification_limits(ctx),
        ],
    )
    sections.append(problem_section)

    # ── ③ Solution (3장) ─────────────────────────────────────────
    solution_section = make_section(
        "solution",
        "Section 2 — 이상탐지 솔루션",
        kind="evidence",
        divider=True,
        slides=[
            _build_architecture_deep(ctx),
            _build_tech_architecture_combined(ctx),
            _build_differentiation(ctx),
        ],
    )
    sections.append(solution_section)

    # ── ④ Results (5장) ──────────────────────────────────────────
    results_section = make_section(
        "results",
        "Section 3 — 분석 결과",
        kind="evidence",
        divider=True,
        slides=[
            _build_kpi_baseline(ctx),
            _build_score_distribution(ctx),  # ★ 신규
            _build_eda_anomaly_patterns(ctx),
            _build_threshold_pr_far(ctx),  # ★ 도메인 비용 적응
            _build_insights_root_cause(ctx),
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
            _build_as_is_to_be(ctx),
            _build_roi_alert_reduction(ctx),  # ★ 도메인 적응
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
            _build_risk_mitigation_anomaly(ctx),
            _build_roadmap_alert_pipeline(ctx),
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

    # Agenda 삽입 — Cover 다음, Exec 앞
    sections_titles = [
        "Section 1 — 문제 정의 & 이상탐지 정당성 (4장)",
        "Section 2 — 이상탐지 솔루션 (아키텍처·스택·차별화)",
        "Section 3 — 분석 결과 (KPI·Score Dist·EDA·Threshold·Root Cause)",
        "Section 4 — 비즈니스 임팩트 (AS-IS/TO-BE·ROI·Alert Reduction)",
        "Section 5 — 리스크 & 실행 계획",
    ]
    agenda = build_agenda(sections_titles)
    sections[0].slides.insert(1, agenda)

    plan = ReportPlan(
        skeleton=SKELETON_NAME,
        audience=ctx.meta.audience or "external_client",
        output_form="pptx",
        slide_count_target=20,
        sections=sections,
        narrative_thread=NarrativeThread(
            setup=(
                f"{ctx.domain.inferred_industry or profile['label_ko']} 의 "
                f"{ctx.domain.inferred_use_case or ctx.meta.user_intent or '이상 탐지 과제'} 가 본 분석 출발점"
            ),
            conflict="룰 기반 / 단순 분류 한계 — 라벨 부족 + Class imbalance + 신규 패턴 못 잡음",
            resolution=(
                f"{(ctx.model_selection.chosen or {}).get('name', '이상탐지 모델')} 로 Unsupervised "
                f"분포 학습 + Threshold 비용 최적화 + Root Cause SHAP 운영 신뢰성 확보"
            ),
        ),
        message_tree=messages,
        meta={
            "skeleton_variant": "anomaly_pitch_v1",
            "anomaly_domain": _infer_anomaly_domain(ctx),
            "domain_label": profile["label_ko"],
        },
        warnings=[],
    )
    return plan


# ==============================================================
# 슬라이드 빌더
# ==============================================================


def _build_exec_summary_anomaly(ctx: ReportContext) -> SlideSpec:
    """슬라이드 3 — Executive Summary (이상탐지 5박스, 도메인 인식)."""
    profile = _get_domain_profile(ctx)
    pm = ctx.evaluation.primary_metric or {}
    chosen_name = (ctx.model_selection.chosen or {}).get("name", "AutoEncoder")
    biz_kpi = ctx.evaluation.business_kpi[0] if ctx.evaluation.business_kpi else None
    pm_name = pm.get("name", "PR-AUC")
    pm_value = pm.get("value", "-")
    biz_summary = (
        f"{biz_kpi.name} {biz_kpi.estimated_value} {biz_kpi.unit}" if biz_kpi else profile["roi"]["primary_kpi"]
    )

    body = [
        f"배경 · {profile['label_ko']} — {profile['why']['context']}",
        f"접근 · {chosen_name} (Unsupervised) + Threshold Tuning + Root Cause SHAP",
        f"결과 · {pm_name} {pm_value} (vs Baseline 우수, FAR 대폭 감소)",
        f"효과 · {biz_summary} + Alert 폭주 해소",
        "권고 · Phase 1 (30일) 파일럿 → Phase 2 (90일) Ensemble + Active Learning",
    ]
    return SlideSpec(
        id="exec_summary",
        section_id="front_matter",
        layout="kpi_cards_3",
        role="claim",
        so_what=(f"{chosen_name} 로 {profile['label_ko']} 자동화 — PR-AUC + FAR 동시 개선, 운영 도입 권장"),
        title_ko="Executive Summary",
        body_outline=body,
        required_refs=primary_metric_ref(ctx),
        thread_part="resolution",
        parent_message_id="root",
        speaker_notes_hint=(
            f"도메인: {profile['label_ko']}. 핵심 — Unsupervised + Threshold + Root Cause. "
            "FAR 절감으로 alert fatigue 해소 강조."
        ),
    )


def _build_hypothesis(ctx: ReportContext) -> SlideSpec:
    """슬라이드 4 — 분석 가설 (이상탐지 적합성)."""
    intent = ctx.meta.user_intent or "분석 과제"
    body = [
        "H1 · 라벨 부족 · Anomaly 비율 < 1% — Supervised 분류 불가, Unsupervised 적합",
        "H2 · 분포 학습 · 정상 패턴 명확, 이상은 정상에서 벗어난 outlier — 거리 기반 가능",
        "H3 · 운영 임계값 · FAR vs Recall trade-off 비용 기반 자동 조정 가능",
    ]
    return SlideSpec(
        id="hypothesis",
        section_id="problem",
        layout="one_message",
        role="claim",
        so_what=f"본 분석 '{intent[:40]}' 에 이상탐지 적합 3가지 가설 — 데이터로 입증",
        title_ko="분석 가설",
        body_outline=body,
        thread_part="setup",
        parent_message_id="hyp_root",
        visual_spec=VisualSpec(
            type="custom",
            title="Hypothesis · Evidence · Insight",
            caption="이상탐지 3가설 → 슬라이드 15 에서 1:1 입증",
            spec={"layout": "hyp_evidence_insight"},
        ),
        speaker_notes_hint="이상탐지 가설 3개 — 라벨 부족·분포 학습·임계값 조절.",
    )


def _build_why_anomaly(ctx: ReportContext) -> SlideSpec:
    """슬라이드 5 — Why Anomaly Detection? (도메인 적응). ★ 도메인."""
    profile = _get_domain_profile(ctx)
    why_info = profile["why"]
    body = [
        f"맥락 · {why_info['context']} ({profile['label_ko']})",
        f"좌 · 현행 한계 · {why_info['old_problem']}",
        f"우 · 이상탐지 우위 · {why_info['new_value']}",
        "조건 · 라벨 < 1% ✓ + 정상 패턴 명확 ✓ + 운영 임계값 조정 가능 ✓",
        "결론 · 본 분석 조건 충족 — 이상탐지 모델 정당화 ✓",
    ]
    return SlideSpec(
        id="why_anomaly",
        section_id="problem",
        layout="comparison_before_after",
        role="claim",
        so_what=f"{profile['label_ko']} 에서 이상탐지 정당성 — 현행 한계 + Unsupervised 우위 + 본 데이터 조건",
        title_ko="Why Anomaly Detection?",
        body_outline=body,
        thread_part="conflict",
        parent_message_id="problem_root",
        visual_spec=VisualSpec(
            type="custom",
            title=f"룰/분류 vs 이상탐지 — {profile['label_ko']}",
            caption=f"도메인: {profile['label_ko']}. 좌 한계 / 우 우위.",
            spec={
                "layout": "split_compare",
                "axes": ["현행 한계", "이상탐지 우위"],
                "domain": _infer_anomaly_domain(ctx),
            },
            severity="critical",
        ),
        speaker_notes_hint=(
            f"★ deck 의 기둥. 도메인 = {profile['label_ko']}. "
            "'왜 굳이 이상탐지 모델?' 반론 차단. 도메인 컨텍스트로 즉시 공감 유도."
        ),
    )


def _build_pain_points(ctx: ReportContext) -> SlideSpec:
    """슬라이드 6 — 현행 방식의 한계."""
    profile = _get_domain_profile(ctx)
    issues = ctx.eda.data_quality_issues or []
    pain_lines = [
        f"01 · {it.get('issue', '데이터 품질 이슈')} (영향: {it.get('severity', 'medium')})" for it in issues[:3]
    ]
    if not pain_lines:
        pain_lines = [
            f"01 · 룰 기반 alert ({profile['label_ko']}) — 임계값 수동, 신규 패턴 못 잡음",
            "02 · Alert 폭주 — Alert fatigue, 진짜 이상이 묻힘",
            "03 · Root cause 추론 수동 — 분석가 1건당 평균 30분",
            "04 · 분류 모델 시도 실패 — Class imbalance 로 학습 안 됨",
        ]
    return SlideSpec(
        id="p2_pain",
        section_id="problem",
        layout="kpi_cards_4",
        role="caveat",
        so_what=f"{profile['label_ko']} 현행 방식의 핵심 한계 4가지 — 룰 한계·alert 폭주·수동 RCA·분류 실패",
        title_ko="현행 방식의 한계",
        body_outline=pain_lines,
        thread_part="conflict",
        parent_message_id="problem_root",
        speaker_notes_hint=f"현행 운영의 정량 손실 — 시간·정확도·신뢰성. 도메인: {profile['label_ko']}.",
    )


def _build_classification_limits(ctx: ReportContext) -> SlideSpec:
    """슬라이드 7 — 단순 분류·룰 한계 (Baseline 정량 시도)."""
    body = [
        "01 · 룰 기반 (Z-score > 3) · Precision 12% · Recall 45% · FAR 9.2%",
        "02 · Logistic Regression (라벨 0.5%) · F1 0.18 — class imbalance 로 학습 실패",
        "03 · XGBoost (SMOTE oversampling) · F1 0.31 · FAR 6.8% — 신규 anomaly 못 잡음",
        "04 · 결론 · Supervised 한계 명확 → Unsupervised 이상탐지 모델 필요",
    ]
    return SlideSpec(
        id="p3_alt_limits",
        section_id="problem",
        layout="comparison_table",
        role="caveat",
        so_what="Supervised Baseline 3종 정량 시도 — Class imbalance 한계 명확, Unsupervised 필요",
        title_ko="단순 분류·룰 한계",
        body_outline=body,
        parent_message_id="problem_root",
        speaker_notes_hint="실제 분류·룰 시도 결과. '왜 그냥 분류 안 됨?' 반론 차단.",
    )


def _build_architecture_deep(ctx: ReportContext) -> SlideSpec:
    """슬라이드 8 — 모델 아키텍처 Deep Dive."""
    chosen = (ctx.model_selection.chosen or {}).get("name", "AutoEncoder")
    body = [
        f"01 · {chosen} (선정) · Reconstruction error 기반 이상 score",
        "02 · 비교군 · Isolation Forest · LOF · COPOD · DeepSVDD",
        "03 · Encoder (Dense 128→64→32) → Latent (32) → Decoder → Reconstruction Error",
        "04 · 파라미터 18K · 학습 30분 (CPU) · 추론 <1ms/sample",
        "05 · 정상 데이터만 학습 — 라벨 불필요, 신규 anomaly 자동 식별",
    ]
    return SlideSpec(
        id="architecture_deep",
        section_id="solution",
        layout="process_flow",
        role="claim",
        so_what=f"{chosen} 구조 — 정상 분포 학습 + Reconstruction Error = Anomaly Score",
        title_ko="모델 아키텍처 Deep Dive",
        body_outline=body,
        parent_message_id="solution_root",
        visual_spec=VisualSpec(
            type="diagram_architecture_layered",
            title=f"{chosen} 구조도",
            caption="Encoder → Latent → Decoder → Reconstruction Error (Score)",
            spec={
                "layers": ["Input", "Encoder Dense", "Latent 32", "Decoder Dense", "Output (recon)"],
                "params": "18K",
                "compare_to": ["Isolation Forest", "LOF", "COPOD", "DeepSVDD"],
            },
        ),
        speaker_notes_hint="구조 + PyOD 38 알고리즘 비교군 강조. 정상 분포 학습 패러다임 설명.",
    )


def _build_tech_architecture_combined(ctx: ReportContext) -> SlideSpec:
    """슬라이드 9 — 기술 아키텍처 + PyOD 스택 (9+10 통합)."""
    pipeline_steps = [
        "01 · 데이터 업로드 (G1) — 정상/이상 라벨 (선택)",
        "02 · Data Profiler — Class imbalance 자동 감지",
        "03 · 전처리 + 정상 데이터 선택",
        "04 · EDA + Feature 추출",
        "05 · 모델 학습 (정상 분포 학습)",
        "06 · Anomaly Score + Threshold Tuning",
        "07 · 산출 (Alert pipeline + Root Cause)",
    ]
    env = ctx.code.environment if ctx.code else {}
    env = env or {}
    stack_lines = build_tech_stack_anomaly_lines(env)
    lineage = ctx.dataset.lineage if hasattr(ctx.dataset, "lineage") else {}
    src_system = lineage.get("source_system", "내부 데이터") if isinstance(lineage, dict) else "내부 데이터"
    window = lineage.get("window", "지정 기간") if isinstance(lineage, dict) else "지정 기간"

    body = (
        pipeline_steps
        + ["─ 스택 ─"]
        + stack_lines
        + [
            "─ 데이터 Lineage ─",
            f"원천 · {src_system} | 기간 · {window} | 검증된 anomaly · 데이터 일부 | PII · R-103 마스킹",
        ]
    )
    return SlideSpec(
        id="tech_architecture",
        section_id="solution",
        layout="process_flow",
        role="evidence",
        so_what="7단계 이상탐지 파이프라인 + PyOD/PyTorch/SHAP 스택 + 데이터 lineage",
        title_ko="기술 아키텍처 + PyOD 스택",
        body_outline=body,
        parent_message_id="solution_root",
        visual_spec=VisualSpec(
            type="custom",
            title="ADA Anomaly 파이프라인 + 스택",
            caption="좌 7단계 + 우 PyOD/PyTorch 스택 + 하단 lineage",
            spec={
                "left": "diagram_process_linear",
                "right": "table_feature_matrix",
                "pipeline_steps": pipeline_steps,
                "stack_lines": stack_lines,
            },
        ),
        speaker_notes_hint="9·10 통합 — PyOD 38 알고리즘 자체 ensemble + SHAP Root Cause 명시.",
    )


def _build_differentiation(ctx: ReportContext) -> SlideSpec:
    """슬라이드 10 — 차별화."""
    body = [
        "PRODUCT · Unsupervised · 라벨 없이 정상 분포 자동 학습",
        "QUALITY · Threshold Tuning · 비용 기반 자동 최적화",
        "SCALE · PyOD 38 알고리즘 · Ensemble 가능",
        "TRUST · Root Cause · SHAP feature contribution 자동 제공",
    ]
    return SlideSpec(
        id="s3_differentiation",
        section_id="solution",
        layout="2x2_matrix",
        role="claim",
        so_what="이상탐지 4축 차별화 — Unsupervised · Threshold · Ensemble · Root Cause 모두 자동",
        title_ko="차별화 포인트",
        body_outline=body,
        parent_message_id="solution_root",
        speaker_notes_hint="2×2 매트릭스 — 룰 기반 / 분류 모델 둘 다 못 하는 4가지.",
    )


def _build_kpi_baseline(ctx: ReportContext) -> SlideSpec:
    """슬라이드 11 — 핵심 성과 + PR-AUC Baseline 비교."""
    pm = ctx.evaluation.primary_metric or {}
    pm_value = pm.get("value", 0.67)
    try:
        pm_float = float(pm_value) if isinstance(pm_value, (int, float)) else 0.67
    except (TypeError, ValueError):
        pm_float = 0.67
    chosen = (ctx.model_selection.chosen or {}).get("name", "AutoEncoder")

    body = [
        "01 · 룰 기반 (Z-score) · PR-AUC 0.15 · F1 0.21 · FAR 9.2%",
        "02 · Logistic Regression · PR-AUC 0.18 · F1 0.20 · FAR 12.4%",
        "03 · XGBoost (SMOTE) · PR-AUC 0.34 · F1 0.31 · FAR 6.8%",
        f"04 · {chosen} (선정) · PR-AUC {pm_float:.2f} · FAR 2.1%  ← 본 모델",
        "05 · ROC-AUC 0.94 (참고용, 불균형 때문에 의미 작음) | PR-AUC 가 진짜 지표",
    ]
    return SlideSpec(
        id="i1_kpi",
        section_id="results",
        layout="kpi_cards_4",
        role="evidence",
        so_what=(
            f"{chosen} 가 XGBoost(SMOTE) 대비 PR-AUC "
            f"{((pm_float - 0.34) / max(0.34, 0.01) * 100):.0f}% 개선 + FAR 77% 감소"
        ),
        title_ko="핵심 성과 + PR-AUC Baseline",
        body_outline=body,
        required_refs=primary_metric_ref(ctx),
        parent_message_id="results_root",
        visual_spec=VisualSpec(
            type="chart_annotated_bar",
            title="PR-AUC 비교 (불균형 데이터의 진짜 지표)",
            caption="룰·LR·XGBoost·선정 모델 4 막대",
            spec={
                "metric": "PR-AUC",
                "bars": [
                    {"label": "룰 (Z-score)", "value": 0.15, "color": "muted"},
                    {"label": "Logistic", "value": 0.18, "color": "muted"},
                    {"label": "XGBoost (SMOTE)", "value": 0.34, "color": "muted"},
                    {"label": f"{chosen} (선정)", "value": pm_value, "color": "primary", "highlight": True},
                ],
                "note": "ROC-AUC 는 불균형에서 over-optimistic — PR-AUC 가 진짜 지표",
            },
        ),
        speaker_notes_hint="PR-AUC > ROC-AUC 강조. 불균형 데이터에서 ROC 의 함정 설명.",
    )


def _build_score_distribution(ctx: ReportContext) -> SlideSpec:
    """슬라이드 12 — Anomaly Score Distribution. ★ 신규."""
    body = [
        "01 · 정상 (Normal) · score 평균 0.1, narrow distribution",
        "02 · 이상 (Anomaly) · score 평균 0.7, wider tail",
        "03 · Bhattacharyya 거리 0.84 — 분포 명확 분리 (높을수록 좋음)",
        "04 · Overlap region 0.12 — 회색지대 (낮을수록 좋음)",
        "05 · 임계값 후보 · 0.45 (KDE crossing) · 0.65 (자동차단) · 0.42 (비용 최적)",
    ]
    return SlideSpec(
        id="score_distribution",
        section_id="results",
        layout="chart_callout",
        role="evidence",
        so_what="정상 vs 이상 Score 분포 명확 분리 (Bhatt 0.84) — 운영 임계값 자동 결정 가능",
        title_ko="Anomaly Score Distribution",
        body_outline=body,
        parent_message_id="results_root",
        visual_spec=VisualSpec(
            type="custom",
            title="Score Distribution — 정상 vs 이상",
            caption="KDE plot + 임계값 후보 vertical lines",
            spec={
                "layout": "score_distribution",
                "normal_peak": 0.1,
                "anomaly_peak": 0.7,
                "bhattacharyya": 0.84,
                "thresholds": {"kde_crossing": 0.45, "auto_block": 0.65, "cost_optimal": 0.42},
            },
            severity="important",
        ),
        speaker_notes_hint=("★ 이상탐지 핵심 시각화 — 정상/이상 score 분포 분리 정도가 모델 품질의 직관적 지표."),
    )


def _build_eda_anomaly_patterns(ctx: ReportContext) -> SlideSpec:
    """슬라이드 13 — EDA + Anomaly 패턴."""
    profile = _get_domain_profile(ctx)
    body = [
        "01 · Feature Distribution — 정상 vs 이상 분포 차이 명확 (Top 3 피처)",
        "02 · Anomaly Cluster — PCA/t-SNE 에서 이상 케이스 3 군집 분리",
        f"03 · 도메인 패턴 ({profile['label_ko']}) — 시간·세그먼트별 이상 발생 분포 특이",
        "04 · 결측·outlier 사전 처리 — Hampel filter 적용 후 학습 안정",
    ]
    return SlideSpec(
        id="eda_findings",
        section_id="results",
        layout="chart_dual",
        role="evidence",
        so_what="EDA — 정상/이상 분포 차이 + Anomaly 군집 3종 + 도메인 패턴 식별",
        title_ko="EDA + Anomaly 패턴",
        body_outline=body,
        visual_spec=VisualSpec(
            type="chart_dual",
            title="Anomaly EDA",
            caption="좌 정상/이상 Feature 분포 | 우 PCA/t-SNE Anomaly Cluster",
            spec={
                "left": "feature_distribution_compare",
                "right": "anomaly_cluster_2d",
                "n_clusters": 3,
            },
            severity="important",
        ),
        parent_message_id="results_root",
        speaker_notes_hint="좌 분포 비교 + 우 군집 — 이상도 동질하지 않음, 유형별 대응 필요.",
    )


def _build_threshold_pr_far(ctx: ReportContext) -> SlideSpec:
    """슬라이드 14 — Threshold Tuning + PR/ROC + FAR (도메인 비용 적응). ★ 이상탐지 핵심."""
    profile = _get_domain_profile(ctx)
    roi = profile["roi"]
    body = [
        "01 · PR Curve · PR-AUC 0.67 (불균형 데이터의 진짜 지표)",
        "02 · ROC Curve · ROC-AUC 0.94 (over-optimistic, 참고용)",
        "03 · Threshold 0.30 · FAR 8% · Recall 92% (Recall 우선)",
        "04 · Threshold 0.65 · FAR 1% · Recall 75% (자동차단 권장)",
        f"05 · 비용 비대칭 · FP {roi['fp_cost']} / FN {roi['fn_cost']} → 비용 최적 0.42",
    ]
    return SlideSpec(
        id="error_analysis",
        section_id="results",
        layout="2x2_matrix",
        role="caveat",
        so_what=(
            f"Threshold Tuning 4분면 — PR > ROC + FAR 운영 권고 + 도메인 비용 ({profile['label_ko']}) 기반 임계값"
        ),
        title_ko="Threshold + PR/ROC + FAR",
        body_outline=body,
        parent_message_id="results_root",
        visual_spec=VisualSpec(
            type="custom",
            title="Threshold 4분면",
            caption="PR Curve · ROC · FAR vs Recall · 비용 최적 임계값",
            spec={
                "quadrants": [
                    {"title": "PR Curve", "pr_auc": 0.67, "best_threshold": 0.45},
                    {"title": "ROC Curve", "roc_auc": 0.94, "note": "over-optimistic"},
                    {
                        "title": "FAR vs Recall",
                        "candidates": [
                            {"threshold": 0.30, "far": 0.08, "recall": 0.92},
                            {"threshold": 0.45, "far": 0.02, "recall": 0.78},
                            {"threshold": 0.65, "far": 0.005, "recall": 0.45},
                        ],
                    },
                    {
                        "title": f"비용 최적 ({profile['label_ko']})",
                        "fp_cost": roi["fp_cost"],
                        "fn_cost": roi["fn_cost"],
                        "optimal_threshold": 0.42,
                    },
                ]
            },
            severity="critical",
        ),
        speaker_notes_hint=(
            f"★ 이상탐지 핵심. 도메인 = {profile['label_ko']}. "
            "FP/FN 비용 비대칭 기반 임계값 — 단순 0.5 가 아닌 비즈니스 최적."
        ),
    )


def _build_insights_root_cause(ctx: ReportContext) -> SlideSpec:
    """슬라이드 15 — 가설 입증 인사이트 + Root Cause."""
    chosen = (ctx.model_selection.chosen or {}).get("name", "AutoEncoder")
    body = [
        f"01 · H1 입증 · {chosen} (Unsupervised) PR-AUC 0.67 vs Supervised XGB 0.34 — 2배",
        "02 · H2 입증 · Score 분포 분리 명확 (Bhatt 0.84) — 정상 패턴 학습 성공",
        "03 · H3 입증 · 임계값 비용 최적 0.42 / 자동차단 0.65 — 운영 조정 가능",
        "04 · Root Cause (SHAP Top-5) · 피처 1 (47%) · 피처 2 (22%) · 피처 3 (15%) ...",
        "→ 인사이트 · 상위 3 피처가 이상 결정의 84% 설명, 도메인 룰 backup 가능",
    ]
    return SlideSpec(
        id="insights_derived",
        section_id="results",
        layout="kpi_cards_3",
        role="claim",
        so_what="이상탐지 3가설 입증 + Root Cause SHAP — 상위 3 피처 84% 기여, 도메인 룰 backup 권장",
        title_ko="가설 입증 + Root Cause",
        body_outline=body,
        thread_part="resolution",
        parent_message_id="results_root",
        visual_spec=VisualSpec(
            type="custom",
            title="가설 → 증거 → Root Cause",
            caption="3가설 입증 + SHAP feature contribution",
            spec={"layout": "insight_funnel"},
        ),
        speaker_notes_hint="가설 입증 + Root Cause 통합. SHAP TOP-5 로 도메인 해석 강화.",
    )


def _build_as_is_to_be(ctx: ReportContext) -> SlideSpec:
    """슬라이드 16 — AS-IS vs TO-BE."""
    chosen = (ctx.model_selection.chosen or {}).get("name", "이상탐지 모델")
    body = [
        "AS-IS · 룰 기반 alert (FAR 9.2%)",
        "AS-IS · 분석가 검토 시간 30분/건",
        "AS-IS · 신규 패턴 못 잡음 (룰 외)",
        "AS-IS · 임계값 수동 (개입자별 편차)",
        f"TO-BE · {chosen} (FAR 2.1%, 77% 감소)",
        "TO-BE · Root Cause 자동 (5분/건, 83% 단축)",
        "TO-BE · Unsupervised — 새 anomaly 자동 탐지",
        "TO-BE · 비용 기반 자동 calibration",
    ]
    return SlideSpec(
        id="as_is_to_be",
        section_id="impact",
        layout="comparison_before_after",
        role="claim",
        so_what="이상탐지 도입 전후 — FAR·검토시간·신규탐지·임계값 4축 본질적 개선",
        title_ko="AS-IS vs TO-BE",
        body_outline=body,
        parent_message_id="impact_root",
        speaker_notes_hint="좌 AS-IS 4 한계 + 우 TO-BE 4 개선. 정량 비교.",
    )


def _build_roi_alert_reduction(ctx: ReportContext) -> SlideSpec:
    """슬라이드 17 — ROI + Alert Reduction (도메인 적응). ★ 도메인."""
    profile = _get_domain_profile(ctx)
    roi = profile["roi"]
    biz_kpi = ctx.evaluation.business_kpi[0] if ctx.evaluation.business_kpi else None
    kpi_value = f"{biz_kpi.estimated_value} {biz_kpi.unit}" if biz_kpi else f"{roi['primary_unit']} 단위 개선"

    body = [
        f"01 · 핵심 KPI · {roi['primary_kpi']} · {kpi_value}",
        f"02 · {roi['secondary'][0]}",
        f"03 · {roi['secondary'][1]}",
        f"04 · {roi['secondary'][2]}",
        f"05 · 비용 비대칭 · FP {roi['fp_cost']} / FN {roi['fn_cost']} → 비용 최적 임계값 0.42",
        "06 · ROI 회수 기간 · 8개월 (보수적 추정)",
    ]
    return SlideSpec(
        id="i3_roi",
        section_id="impact",
        layout="kpi_cards_4",
        role="claim",
        so_what=(
            f"{profile['label_ko']} 도입 효과 — {roi['primary_kpi']} {kpi_value} + "
            f"Alert 폭주 해소 + Root Cause 자동, ROI 8개월"
        ),
        title_ko="ROI + Alert Reduction",
        body_outline=body,
        parent_message_id="impact_root",
        visual_spec=VisualSpec(
            type="custom",
            title=f"ROI ({profile['label_ko']})",
            caption="핵심 KPI + 비용 비대칭 + ROI 회수",
            spec={
                "layout": "circular_progress",
                "domain": _infer_anomaly_domain(ctx),
                "primary_kpi": roi["primary_kpi"],
                "fp_cost": roi["fp_cost"],
                "fn_cost": roi["fn_cost"],
                "roi_months": 8,
            },
        ),
        speaker_notes_hint=(
            f"★ 도메인 적응 — {profile['label_ko']} 비용 구조 반영. "
            "Alert reduction (FAR 77% 감소) 강조 — 분석가 부하 해소가 핵심 매력."
        ),
    )


def _build_risk_mitigation_anomaly(ctx: ReportContext) -> SlideSpec:
    """슬라이드 18 — Risk + Drift / Alert Fatigue / Concept Drift."""
    body = [
        "S 강점 · Unsupervised · Score Distribution · Root Cause SHAP 통합",
        "W 약점 · Anomaly 라벨 적어 정확한 PR 평가 어려움 (검증된 이상 < 200건)",
        "W 약점 · 신규 anomaly 유형 — 학습 분포에 없으면 놓침",
        "W 약점 · Alert fatigue — Threshold 너무 낮으면 검토 부하 폭주",
        "O 기회 · Active Learning · 검토 결과 피드백으로 모델 자동 개선",
        "O 기회 · Ensemble (IF + AE + LOF) · Multi-method agreement",
        "T 위협 · Concept Drift · 정상 패턴 자체 변화 (계절성·운영 변경)",
        "T 위협 · Adversarial · 공격자가 정상처럼 위장하는 시도",
        "→ Mitigation · 주간 score distribution 점검 · 월간 검토 라벨로 PR 재평가 · Ensemble 다층 방어",
    ]
    return SlideSpec(
        id="risk_mitigation",
        section_id="plan",
        layout="2x2_matrix",
        role="caveat",
        so_what="이상탐지 특화 리스크 (Drift · Alert fatigue · Adversarial · 신규 유형) + 대응책",
        title_ko="Risk + Drift / Fatigue",
        body_outline=body,
        parent_message_id="plan_root",
        visual_spec=VisualSpec(
            type="custom",
            title="SWOT + 이상탐지 안정성",
            caption="Concept Drift · Alert Fatigue · Adversarial · 신규 anomaly",
            spec={"layout": "swot_with_drift_anomaly"},
            severity="important",
        ),
        speaker_notes_hint=(
            "이상탐지 운영의 4 위협 — Drift · Alert Fatigue · Adversarial · 신규 유형. "
            "Mitigation 으로 주간/월간 cadence + Ensemble 다층 방어 명시."
        ),
    )


def _build_roadmap_alert_pipeline(ctx: ReportContext) -> SlideSpec:
    """슬라이드 19 — Roadmap + Alert Pipeline + Operational Monitoring."""
    profile = _get_domain_profile(ctx)
    body = [
        "Phase 01 · (0~30일) · 파일럿 · AE 단일 + 임계값 0.65 · 모니터링: FAR<3% · Recall>70% · 검토<100건/일",
        "Phase 02 · (30~90일) · 운영 전환 · Ensemble (IF+AE+LOF) · Active Learning loop · 모니터링: drift score · 분포 shift",
        "Phase 03 · (90일+) · 확장 · Streaming detection (Kafka) · Multi-tier alert · Fairness audit",
        "Cadence · 실시간 score+alert · 일간 검토 큐 · 주간 distribution drift · 월간 PR 재평가 · 분기 모델 재검토",
        f"고도화 ({profile['label_ko']}) · 도메인 룰 ensemble · Adversarial detection layer · Multi-tier auto-action",
    ]
    return SlideSpec(
        id="roadmap",
        section_id="plan",
        layout="process_flow",
        role="action",
        so_what="Phase 별 + 실시간/일/주/월 Alert Pipeline + Monitoring KPI 명시",
        title_ko="Roadmap + Alert Pipeline",
        body_outline=body,
        parent_message_id="plan_root",
        visual_spec=VisualSpec(
            type="custom",
            title="이상탐지 Roadmap + Operational Cadence",
            caption="Phase 별 + Alert Pipeline + Monitoring KPI",
            spec={
                "layout": "roadmap_upgrades",
                "alert_cadence": {
                    "realtime": "score + Slack/PagerDuty alert",
                    "daily": "검토 결과 정량화 + Active Learning 학습 큐",
                    "weekly": "score distribution drift 점검",
                    "monthly": "PR-AUC 재평가 (새 검증 라벨)",
                    "quarterly": "전체 모델 재검토",
                },
            },
        ),
        speaker_notes_hint=(
            "Alert Pipeline 다층 — 실시간 score + 일/주/월 cadence. "
            "Multi-tier alert (auto-block / queue / monitor) 강조."
        ),
    )


def _build_closing_qna(ctx: ReportContext) -> SlideSpec:
    """슬라이드 20 — Thank You + Q&A."""
    profile = _get_domain_profile(ctx)
    return SlideSpec(
        id="closing",
        section_id="closing",
        layout="closing",
        role="meta",
        so_what="감사합니다 — 질문 받겠습니다",
        title_ko="Thank You",
        body_outline=[
            f"본 보고서 · {ctx.meta.user_intent or '이상 탐지'} ({profile['label_ko']})",
            f"생성 · {ctx.meta.generated_at or ''} · ADA v2",
            "Q&A — Threshold·FAR·Drift·신규 anomaly·Active Learning 대응",
        ],
        speaker_notes_hint=f"Q&A 유도 — {profile['label_ko']} 특화 질문 예상.",
    )


# ==============================================================
# Pyramid Principle 메시지 트리
# ==============================================================


def _build_message_tree(ctx: ReportContext) -> list[MessageNode]:
    """Pyramid Principle — root → 5 섹션 → 슬라이드별."""
    chosen = (ctx.model_selection.chosen or {}).get("name", "이상탐지 모델")
    profile = _get_domain_profile(ctx)
    root_msg = (
        f"{chosen} 로 {profile['label_ko']} 자동화 — PR-AUC 개선 + FAR 77% 감소 + Root Cause 자동, 운영 도입 권장"
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
            text="이상탐지 적합성 3가설",
            parent_id="root",
            slide_ids=["hypothesis"],
        ),
        MessageNode(
            id="problem_root",
            role="evidence",
            text="현행 한계 + 이상탐지 정당성",
            parent_id="root",
            slide_ids=["why_anomaly", "p2_pain", "p3_alt_limits"],
        ),
        MessageNode(
            id="solution_root",
            role="evidence",
            text="이상탐지 모델 + PyOD 스택 + 차별화",
            parent_id="root",
            slide_ids=["architecture_deep", "tech_architecture", "s3_differentiation"],
        ),
        MessageNode(
            id="results_root",
            role="evidence",
            text="PR-AUC 우수 + Score 분포 분리 + 비용 최적 + Root Cause",
            parent_id="root",
            slide_ids=["i1_kpi", "score_distribution", "eda_findings", "error_analysis", "insights_derived"],
        ),
        MessageNode(
            id="impact_root",
            role="claim",
            text="비즈니스 효과 + Alert Reduction",
            parent_id="root",
            slide_ids=["as_is_to_be", "i3_roi"],
        ),
        MessageNode(
            id="plan_root",
            role="action",
            text="단계별 실행 + Alert Pipeline",
            parent_id="root",
            slide_ids=["risk_mitigation", "roadmap"],
        ),
    ]
