"""outputs.context.builder — PipelineState ↔ ReportContext 정규화 (Phase 1.5).

목적:
    1. 분산 적립된 ``state.report_context`` (dict) 를 ``ReportContext`` dataclass 로 정규화.
    2. 누락된 묶음을 ``state`` 의 기존 필드 (best_model, eval_result, eda_charts, insights 등)
       에서 best-effort 보강 — 컨트리뷰트 hook 호출이 안 됐어도 carrier 가 작동하도록.
    3. ``Meta`` 묶음을 항상 ``state`` 의 식별자/의도 필드로부터 자동 충전.

핵심 API:
    ``build_report_context(state) -> ReportContext`` — Architect 입력용 표준 진입점.

설계:
    - 비파괴: state 를 수정하지 않음. ReportContext 만 반환.
    - silent-safe: 모든 추출은 try/except 로 감싸 부분 실패 시에도 다른 묶음 살림.
    - 우선순위: ``state.report_context[stage]`` (적립값) > ``state`` 의 기존 필드 (legacy).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from ada.core.state import PipelineState
from outputs.context.schema import (
    REPORT_CONTEXT_VERSION,
    AudienceInference,
    BaselineSet,
    CitationIndex,
    DatasetProfile,
    DomainContext,
    EDAChart,
    EDAFindings,
    Evaluation,
    FeatureEngineering,
    Interpretation,
    Limitations,
    Meta,
    ModelCandidate,
    ModelSelection,
    PreprocessingStep,
    PreprocessingTrace,
    ReportContext,
    Training,
)

# ==============================================================
# Public API
# ==============================================================


def build_report_context(state: PipelineState) -> ReportContext:
    """``state`` 로부터 정규화된 ``ReportContext`` 빌드.

    적립값과 legacy state 필드를 모두 활용. 어떤 입력이든 ``ReportContext`` 반환.
    """
    # 1) 적립된 dict 를 우선 hydrate
    ctx_dict = state.report_context or {}
    ctx = ReportContext.from_dict(ctx_dict)

    # 2) version 통일
    ctx.version = REPORT_CONTEXT_VERSION

    # 3) legacy 필드 보강 — 적립이 비어있는 묶음만 채움
    _augment_dataset(ctx, state)
    _augment_domain(ctx, state)
    _augment_preprocessing(ctx, state)
    _augment_features(ctx, state)
    _augment_eda(ctx, state)
    _augment_model_selection(ctx, state)
    _augment_training(ctx, state)
    _augment_evaluation(ctx, state)
    _augment_interpretation(ctx, state)
    _augment_limitations(ctx, state)
    _augment_from_assets(ctx, state)
    # ⑪ code 는 CodeArtifactExtractor (Phase 1.9) 가 직접 적립. 빈 상태 유지가 정상.

    # 4) meta 는 항상 state 의 최신값으로 덮어씀 (단일 진실원).
    ctx.meta = _build_meta(state, ctx.meta)

    # 5) citations 는 CitationManager (Phase 1.6) 가 채움. 빈 상태가 정상.
    if not isinstance(ctx.citations, CitationIndex):
        ctx.citations = CitationIndex()

    return ctx


def to_state_dict(ctx: ReportContext) -> dict[str, Any]:
    """ReportContext → state.report_context 에 저장 가능한 dict."""
    return ctx.to_dict()


# ==============================================================
# 묶음별 보강 함수 (silent-safe)
# ==============================================================


def _augment_dataset(ctx: ReportContext, state: PipelineState) -> None:
    """state.data_profile / data_card 로부터 DatasetProfile 보강."""
    try:
        if not _is_empty_dataset(ctx.dataset):
            return  # 이미 적립됨
        profile = state.data_profile or {}
        card = getattr(state, "data_card", None) or {}

        identity = card.get("identity") or {}
        schema = card.get("schema") or {}
        dictionary = card.get("dictionary") or {}
        temporal = card.get("temporal_drift") or {}
        granularity = card.get("granularity") or {}
        repro = card.get("reproducibility") or {}

        # shape
        rows = int(identity.get("row_count") or profile.get("rows") or 0)
        cols = int(identity.get("col_count") or profile.get("columns_count") or 0)

        # dtypes
        dtypes_raw = schema.get("dtypes") or profile.get("dtypes") or {}
        dtypes = {str(k): str(v) for k, v in dtypes_raw.items()} if isinstance(dtypes_raw, dict) else {}

        # missing / cardinality / numeric_stats — dictionary 우선
        missing: dict[str, float] = {}
        cardinality: dict[str, int] = {}
        numeric_stats: dict[str, dict[str, float]] = {}
        if isinstance(dictionary, dict):
            for col, info in dictionary.items():
                if not isinstance(info, dict):
                    continue
                mp = info.get("missing_pct")
                if isinstance(mp, (int, float)):
                    missing[str(col)] = round(float(mp) / 100.0, 4)
                nu = info.get("nunique")
                if isinstance(nu, int):
                    cardinality[str(col)] = nu
                if any(k in info for k in ("min", "max", "mean")):
                    numeric_stats[str(col)] = {
                        k: float(info[k]) for k in ("min", "max", "mean") if isinstance(info.get(k), (int, float))
                    }

        # 사람이 읽을 데이터셋명 우선 — 없으면 file_id(UUID) 폴백 (carrier/skeleton 가 추가 방어)
        human_name = (
            identity.get("dataset_name")
            or identity.get("name")
            or identity.get("filename")
            or identity.get("title")
            or (profile.get("dataset_name") if isinstance(profile, dict) else None)
            or identity.get("source_hint")
            or state.file_id
            or ""
        )

        ctx.dataset = DatasetProfile(
            dataset_name=str(human_name),
            dataset_hash=str(repro.get("data_hash_sample", "")),
            shape={"rows": rows, "cols": cols},
            dtypes=dtypes,
            missing_rate=missing,
            cardinality=cardinality,
            numeric_stats=numeric_stats,
            detected_target=state.target_column,
            detected_time_col=(list(temporal.get("time_columns") or [None]) or [None])[0],
            detected_id_cols=list(granularity.get("pk_candidates") or [])[:5],
            file_meta={
                "size_mb": round(int(schema.get("memory_bytes") or 0) / (1024 * 1024), 3),
                "encoding": "utf-8",
                "source": str(identity.get("source_hint") or "user_upload"),
            },
        )
    except Exception:
        pass


def _augment_domain(ctx: ReportContext, state: PipelineState) -> None:
    """data_card.category_target / domain_analysis 보강."""
    try:
        if ctx.domain.inferred_use_case or ctx.domain.glossary:
            return
        card = getattr(state, "data_card", None) or {}
        domain_card = (state.data_profile or {}).get("domain_analysis") or {}
        category_target = card.get("category_target") or {}
        column_meanings = domain_card.get("column_meanings") or {}
        ctx.domain = DomainContext(
            inferred_industry=domain_card.get("domain") or None,
            inferred_use_case=domain_card.get("dataset_summary") or category_target.get("reason") or None,
            glossary={str(k): str(v) for k, v in column_meanings.items() if isinstance(v, str)},
            audience_inference=ctx.domain.audience_inference or AudienceInference(),
        )
    except Exception:
        pass


def _augment_preprocessing(ctx: ReportContext, state: PipelineState) -> None:
    """state.preprocessing_plan 으로부터 PreprocessingTrace 보강."""
    try:
        if ctx.preprocessing.applied_steps:
            return
        plan = state.preprocessing_plan or []
        steps = [
            PreprocessingStep(
                op=str(s.get("name") or s.get("op") or ""),
                scope=list(s.get("columns") or s.get("scope") or []),
                params={k: v for k, v in s.items() if k not in ("name", "op", "columns", "scope")},
                rationale=str(s.get("rationale") or ""),
            )
            for s in plan
            if isinstance(s, dict)
        ]
        if steps:
            ctx.preprocessing = PreprocessingTrace(applied_steps=steps)
    except Exception:
        pass


def _augment_features(ctx: ReportContext, state: PipelineState) -> None:
    """data_card.schema.col_count 로 final_feature_count 보강."""
    try:
        if ctx.features.final_feature_count > 0 or ctx.features.created:
            return
        card = getattr(state, "data_card", None) or {}
        schema = card.get("schema") or {}
        columns = schema.get("columns") or []
        if columns:
            ctx.features = FeatureEngineering(final_feature_count=len(columns))
    except Exception:
        pass


def _augment_eda(ctx: ReportContext, state: PipelineState) -> None:
    """state.eda_charts (MinIO 경로 리스트) → EDAFindings.charts."""
    try:
        if ctx.eda.charts:
            return
        eda_charts = state.eda_charts or []
        if not eda_charts:
            return
        ctx.eda = EDAFindings(charts=[EDAChart(path=str(p), chart_type="unknown", severity="info") for p in eda_charts])
    except Exception:
        pass


def _augment_model_selection(ctx: ReportContext, state: PipelineState) -> None:
    """state.model_candidates + best_model 로 ModelSelection 보강."""
    try:
        if ctx.model_selection.candidates or ctx.model_selection.chosen:
            return
        candidates = state.model_candidates or []
        cand_objs = [ModelCandidate(name=str(m), family="", why_tried="") for m in candidates]
        chosen: dict[str, Any] = {}
        bm = state.best_model or {}
        if bm.get("model_name"):
            chosen = {
                "name": str(bm.get("model_name")),
                "family": str(bm.get("framework", "")),
                "justification": "",
            }
        if cand_objs or chosen:
            ctx.model_selection = ModelSelection(
                candidates=cand_objs,
                chosen=chosen,
                baselines=BaselineSet(),
            )
    except Exception:
        pass


def _augment_training(ctx: ReportContext, state: PipelineState) -> None:
    """state.trained_models 으로부터 Training 보강."""
    try:
        if ctx.training.runs:
            return
        runs_raw = state.trained_models or []
        if not runs_raw:
            return
        ctx.training = Training(
            runs=[],  # TrainingRun hydrate 는 별도 작업 — 간단히 비워둠
            chosen_run_id="",
            tuning_summary={"trials": len(runs_raw)},
        )
    except Exception:
        pass


def _augment_evaluation(ctx: ReportContext, state: PipelineState) -> None:
    """state.best_model.metrics + eval_result 로 Evaluation 보강."""
    try:
        if ctx.evaluation.metrics or ctx.evaluation.primary_metric:
            _ensure_verdict(ctx, state)
            return
        bm = state.best_model or {}
        metrics_raw = bm.get("metrics") or {}
        metrics_norm: dict[str, dict[str, Any]] = {}
        for k, v in metrics_raw.items():
            if isinstance(v, (int, float)):
                metrics_norm[str(k)] = {"value": float(v)}
            elif isinstance(v, dict):
                metrics_norm[str(k)] = {**v}
            else:
                metrics_norm[str(k)] = {"value": v}

        # primary 추정
        category = state.category or ""
        preferred = {
            "tabular_ml": ["auc", "roc_auc", "f1", "accuracy", "rmse", "mae"],
            "tabular_dl": ["auc", "f1", "accuracy", "rmse"],
            "timeseries": ["smape", "mape", "rmse", "mae"],
            "anomaly_detection": ["pr_auc", "f1", "precision", "recall"],
        }.get(category, [])
        primary_name = next((p for p in preferred if p in metrics_norm), None)
        if not primary_name and metrics_norm:
            primary_name = next(iter(metrics_norm))
        primary: dict[str, Any] = {}
        if primary_name:
            primary = {
                "name": primary_name,
                "value": metrics_norm[primary_name].get("value"),
                "direction": "lower_better"
                if any(t in primary_name.lower() for t in ("rmse", "mae", "mape", "smape", "loss"))
                else "higher_better",
            }

        eval_res = state.eval_result or {}
        ctx.evaluation = Evaluation(
            primary_metric=primary,
            metrics=metrics_norm,
            gate_passed=bool(eval_res.get("passed", False)),
            gate_rationale=str(eval_res.get("rationale", "")),
        )
        _ensure_verdict(ctx, state)
    except Exception:
        pass


def _ensure_verdict(ctx: ReportContext, state: PipelineState) -> None:
    """Evaluation.verdict 도출 — 스키마 필드만 있고 생산자가 없던 배관 연결.

    (jh 2026-06-11, HJ 구두 협의 — verdict-aware skeleton 분기가 '미정' 으로
    방치되던 원인. eval_result 의 명시 verdict > gate 휴리스틱 순.)

    규칙:
        - eval_result["verdict"] ∈ {adopt, iterate, reject} 명시 시 그대로
        - gate 통과 → adopt / 메트릭 있으나 미통과 → iterate / 평가 전 → "" 유지
    """
    try:
        if ctx.evaluation.verdict:
            return
        eval_res = state.eval_result or {}
        explicit = str(eval_res.get("verdict", "") or "").strip().lower()
        if explicit in ("adopt", "iterate", "reject"):
            ctx.evaluation.verdict = explicit
            ctx.evaluation.verdict_rationale = str(eval_res.get("rationale", ""))
            return
        if not (ctx.evaluation.metrics or ctx.evaluation.primary_metric):
            return  # 평가 전 — 미정 유지가 정직함
        ctx.evaluation.verdict = "adopt" if ctx.evaluation.gate_passed else "iterate"
        ctx.evaluation.verdict_rationale = ctx.evaluation.gate_rationale or ""
    except Exception:
        pass


def _augment_interpretation(ctx: ReportContext, state: PipelineState) -> None:
    """state.explanations 로부터 Interpretation 보강.

    eval_result['feature_importance'] 도 fallback 으로 확인.
    """
    try:
        if ctx.interpretation.global_importance or ctx.interpretation.per_feature_story:
            return
        from outputs.context.schema import GlobalImportance

        sources = (state.explanations, state.eval_result)
        for src in sources:
            if not isinstance(src, dict):
                continue
            # jh 2026-06-12 — ExplainabilityAgent 의 실제 저장 키 "shap_top_features" 추가.
            # (키 불일치로 SHAP 이 계산되고도 ctx 에 못 들어와 S13 이 '미적립' 으로 나가던 결함)
            fi = (
                src.get("feature_importance")
                or src.get("top_features")
                or src.get("importances")
                or src.get("shap_top_features")
            )
            # shap_top_features 는 (name, importance) 쌍 리스트 형식
            if isinstance(fi, list) and fi and isinstance(fi[0], (list, tuple)) and len(fi[0]) == 2:
                fi = [{"name": str(a), "importance": b} for a, b in fi]
            items: list[GlobalImportance] = []
            if isinstance(fi, dict):
                for k, v in sorted(fi.items(), key=lambda kv: float(kv[1] or 0), reverse=True)[:10]:
                    try:
                        items.append(GlobalImportance(feature=str(k), importance=float(v or 0), method="shap"))
                    except Exception:
                        continue
            elif isinstance(fi, list):
                for x in fi[:10]:
                    if isinstance(x, dict):
                        try:
                            # jh 2026-06-12 — ExplainabilityAgent 는 "feature" 키로 저장
                            # ("name" 만 읽어 S13 이 빈 이름으로 미적립 처리되던 결함).
                            _fname = str(x.get("name") or x.get("feature") or "")
                            if not _fname:
                                continue
                            items.append(
                                GlobalImportance(
                                    feature=_fname,
                                    importance=float(x.get("importance") or 0),
                                    method="shap",
                                )
                            )
                        except Exception:
                            continue
            if items:
                ctx.interpretation = Interpretation(global_importance=items)
                return
    except Exception:
        pass


def _augment_from_assets(ctx: ReportContext, state: PipelineState) -> None:
    """category_extras 의 assets 차트 (CM 히트맵 등) 를 ctx 로 배달.

    jh 2026-06-12 — 핸들러 output_extras 가 CM·calibration 차트를 MinIO 에
    저장하고 있었으나 ctx 까지 배달이 안 돼 S15 가 빈 화면이던 결함.
    경로의 kind 문자열 (tabular/confusion_matrix 등) 로 매핑.
    """
    try:
        cat = state.category or ""
        extras = (state.category_extras or {}).get(cat) or {}
        charts = extras.get("charts") or extras.get("extra_charts") or []
        for p in charts:
            sp = str(p)
            if "confusion_matrix" in sp:
                cm = dict(ctx.evaluation.confusion_matrix or {})
                cm.setdefault("chart_path", sp)
                ctx.evaluation.confusion_matrix = cm
            elif "calibration" in sp or "reliability" in sp:
                cal = dict(ctx.evaluation.calibration or {})
                cal.setdefault("chart_path", sp)
                ctx.evaluation.calibration = cal

        # jh 2026-06-12 — 분석 수치 (CM tn/fp/fn/tp · per_segment · local_examples)
        analysis = extras.get("analysis") or {}
        if isinstance(analysis, dict):
            cm_nums = analysis.get("confusion_matrix")
            if isinstance(cm_nums, dict):
                cm = dict(ctx.evaluation.confusion_matrix or {})
                for k, v in cm_nums.items():
                    cm.setdefault(k, v)
                ctx.evaluation.confusion_matrix = cm
            if not ctx.evaluation.per_segment and isinstance(analysis.get("per_segment"), list):
                ctx.evaluation.per_segment = list(analysis["per_segment"])
            if not ctx.interpretation.local_examples and isinstance(analysis.get("local_examples"), list):
                ctx.interpretation.local_examples = list(analysis["local_examples"])
            # jh 2026-06-12 — 전역 SHAP 2중 안전망 (ExplainabilityAgent 실패 시 S13 백업)
            gi = analysis.get("global_importance")
            if not ctx.interpretation.global_importance and isinstance(gi, list) and gi:
                from outputs.context.schema import GlobalImportance

                items = []
                for x in gi[:10]:
                    if isinstance(x, dict) and x.get("name"):
                        try:
                            items.append(
                                GlobalImportance(
                                    feature=str(x["name"]),
                                    importance=float(x.get("importance") or 0),
                                    method="shap",
                                )
                            )
                        except Exception:
                            continue
                if items:
                    ctx.interpretation.global_importance = items
    except Exception:
        pass


def _augment_limitations(ctx: ReportContext, state: PipelineState) -> None:
    """state.training_warnings + eval_result.threshold_violations 보강."""
    try:
        if ctx.limitations.model_caveats or ctx.limitations.data_gaps:
            return
        caveats: list[str] = list(state.training_warnings or [])
        ev = state.eval_result or {}
        for v in ev.get("threshold_violations") or []:
            caveats.append(str(v))
        if caveats:
            ctx.limitations = Limitations(model_caveats=[c for c in caveats if c])
    except Exception:
        pass


def _build_meta(state: PipelineState, current: Optional[Meta]) -> Meta:
    """state 의 최신 식별자/의도/카테고리/요청산출물로 Meta 갱신."""
    base = current or Meta()
    base.job_id = state.job_id or base.job_id
    base.user_intent = state.user_intent or base.user_intent
    base.user_question = state.user_question or base.user_question
    base.category = state.category or base.category
    base.languages = base.languages or ["ko"]
    # 산출물 — state.requested_outputs 가 있으면 매핑
    if state.requested_outputs:
        mapped: list[str] = []
        codemap = {"OUT-01": "pptx", "OUT-02": "pdf", "OUT-03": "txt", "OUT-04": "html", "OUT-07": "md"}
        for code in state.requested_outputs:
            form = codemap.get(code)
            if form and form not in mapped:
                mapped.append(form)
        if mapped:
            base.output_forms = mapped
    if not base.generated_at:
        base.generated_at = datetime.now(timezone.utc).isoformat()
    return base


# ==============================================================
# 내부 유틸
# ==============================================================


def _is_empty_dataset(ds: DatasetProfile) -> bool:
    return ds.shape.get("rows", 0) == 0 and not ds.dtypes and not ds.dataset_name
