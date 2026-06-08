"""outputs.context.citation_manager — ref_id 발급·색인·검증 (Phase 1.6).

모든 보고서의 수치·인용은 ``ref_id`` 를 통해서만 ``ReportContext`` 의 출처로 역추적된다.
이는 컨설팅 보고서의 신뢰성 핵심: "출처 없는 수치 0건" 강제.

3 가지 책임:
    1. **발급** — ReportContext 의 각 출처(metric/chart/citation/code/etc.) 에 결정론적
       ref_id 부여. 같은 출처는 같은 ref_id (재실행 시 안정).
    2. **색인** — ref_id → {source_path, source_kind, value_snapshot, ...} 단일 색인 구축.
       SlideContentGenerator·QA·CarrierFooter 가 모두 이 색인만 참조.
    3. **검증** — 슬라이드/콘텐츠에 등장한 ref_id 가 색인에 존재하는지 확인.
       미해결 ref_id 가 있으면 carrier 호출 차단 (Phase 1.7 completeness 와 연동).

ref_id 형식:
    ``{kind}::{slug}#{hash8}``  (예: ``metric::auc#a1b2c3d4``)
    - kind: metric | chart | kpi | feature | candidate | citation | code | dataset | step
    - slug: 사람이 읽을 수 있는 짧은 식별자 (snake_case)
    - hash8: source_path + value_snapshot 의 sha256 앞 8자 — 결정론적·충돌 방지

설계:
    - 비파괴: ReportContext 의 ref_id 필드를 직접 채우지 않음. 색인만 생성.
      ``apply_ref_ids(ctx)`` 가 명시 호출 시 dataclass 의 ref_id 필드를 갱신.
    - silent-safe: 잘못된 값/타입은 색인에서 제외, 검증에서는 unresolved 로 보고.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, fields as dc_fields, is_dataclass
from typing import Any, Optional

from outputs.context.schema import (
    CitationIndex,
    ReportContext,
)

# ==============================================================
# 공개 API
# ==============================================================


@dataclass
class CitationEntry:
    """색인 1 행."""

    ref_id: str
    source_path: str  # "evaluation.primary_metric" / "eda.charts[2]" 등
    source_kind: str  # "metric" | "chart" | "kpi" | "feature" | ...
    value_snapshot: Any  # 인용 시점 값 (수치/문자열/dict)
    origin_agent: str = ""  # 추적용 — 알면 채움
    trustworthiness: str = "primary"  # "primary" | "derived" | "external"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "source_kind": self.source_kind,
            "value_snapshot": _safe_snapshot(self.value_snapshot),
            "origin_agent": self.origin_agent,
            "trustworthiness": self.trustworthiness,
        }


@dataclass
class CitationReport:
    """``verify_citations`` 결과 — QA·completeness 가 참조."""

    total_refs: int = 0
    resolved: int = 0
    unresolved: list[str] = field(default_factory=list)
    duplicate_paths: list[str] = field(default_factory=list)

    @property
    def all_resolved(self) -> bool:
        return not self.unresolved


def build_citation_index(ctx: ReportContext) -> CitationIndex:
    """ReportContext 의 모든 출처를 스캔해 ``CitationIndex`` 구축.

    수치·차트·KPI·피처·후보·인용·코드·데이터·step 9 종을 스캔. 같은 source_path 가
    여러 번 등장하면 첫 항목만 등록 + ``duplicate_paths`` 에 기록.
    """
    entries: dict[str, CitationEntry] = {}
    seen_paths: set[str] = set()
    duplicates: list[str] = []

    # ① Dataset
    if ctx.dataset.dataset_name or ctx.dataset.shape.get("rows", 0) > 0:
        _add(
            entries,
            seen_paths,
            duplicates,
            kind="dataset",
            slug=_slug(ctx.dataset.dataset_name or "dataset"),
            source_path="dataset",
            value=ctx.dataset.shape,
            agent="DataProfiler",
        )

    # ② Domain — 인용 (KB / Web 분리 — apply_ref_ids 역추적 일치)
    for i, cit in enumerate(ctx.domain.kb_citations):
        title = getattr(cit, "title", "") or f"kb_{i}"
        _add(
            entries,
            seen_paths,
            duplicates,
            kind="citation",
            slug=_slug(title)[:32],
            source_path=f"domain.kb_citations[{i}]",
            value={"title": title, "url": getattr(cit, "url", None)},
            agent="DomainEnricher",
            trustworthiness="external",
        )
    for i, cit in enumerate(ctx.domain.web_citations):
        title = getattr(cit, "title", "") or f"web_{i}"
        _add(
            entries,
            seen_paths,
            duplicates,
            kind="citation",
            slug=_slug(title)[:32],
            source_path=f"domain.web_citations[{i}]",
            value={"title": title, "url": getattr(cit, "url", None)},
            agent="DomainEnricher",
            trustworthiness="external",
        )

    # ③ Preprocessing steps
    for i, step in enumerate(ctx.preprocessing.applied_steps):
        op = getattr(step, "op", "") or f"step_{i}"
        _add(
            entries,
            seen_paths,
            duplicates,
            kind="step",
            slug=_slug(op),
            source_path=f"preprocessing.applied_steps[{i}]",
            value=op,
            agent="PreprocessingStrategist",
            trustworthiness="derived",
        )

    # ④ Features — created
    for i, feat in enumerate(ctx.features.created):
        name = getattr(feat, "name", "") or f"feat_{i}"
        _add(
            entries,
            seen_paths,
            duplicates,
            kind="feature",
            slug=_slug(name),
            source_path=f"features.created[{i}]",
            value=name,
            agent="FeatureEngineer",
            trustworthiness="derived",
        )

    # ⑤ EDA charts
    for i, ch in enumerate(ctx.eda.charts):
        title = getattr(ch, "title_ko", "") or getattr(ch, "chart_type", "") or f"chart_{i}"
        _add(
            entries,
            seen_paths,
            duplicates,
            kind="chart",
            slug=_slug(title)[:32],
            source_path=f"eda.charts[{i}]",
            value={"path": getattr(ch, "path", ""), "type": getattr(ch, "chart_type", "")},
            agent="EDAAgent",
        )

    # ⑥ Model selection — candidates + chosen
    for i, c in enumerate(ctx.model_selection.candidates):
        name = getattr(c, "name", "") or f"candidate_{i}"
        _add(
            entries,
            seen_paths,
            duplicates,
            kind="candidate",
            slug=_slug(name),
            source_path=f"model_selection.candidates[{i}]",
            value=name,
            agent="ModelSelection",
        )
    if ctx.model_selection.chosen:
        chosen_name = str(ctx.model_selection.chosen.get("name", "chosen"))
        _add(
            entries,
            seen_paths,
            duplicates,
            kind="candidate",
            slug=_slug("chosen_" + chosen_name),
            source_path="model_selection.chosen",
            value=chosen_name,
            agent="ModelSelection",
        )

    # ⑦ Training runs
    for i, run in enumerate(ctx.training.runs):
        rid = getattr(run, "run_id", "") or f"run_{i}"
        _add(
            entries,
            seen_paths,
            duplicates,
            kind="run",
            slug=_slug(rid),
            source_path=f"training.runs[{i}]",
            value={"run_id": rid, "model": getattr(run, "model_name", "")},
            agent="TrainingExecutor",
        )

    # ⑧ Evaluation — primary + metrics + business_kpi + per_segment
    if ctx.evaluation.primary_metric:
        name = str(ctx.evaluation.primary_metric.get("name", "primary"))
        _add(
            entries,
            seen_paths,
            duplicates,
            kind="metric",
            slug=_slug("primary_" + name),
            source_path="evaluation.primary_metric",
            value=ctx.evaluation.primary_metric,
            agent="EvalAgent",
        )
    for mname, m in ctx.evaluation.metrics.items():
        _add(
            entries,
            seen_paths,
            duplicates,
            kind="metric",
            slug=_slug(mname),
            source_path=f"evaluation.metrics.{mname}",
            value=m,
            agent="MetricsAggregator",
        )
    for i, kpi in enumerate(ctx.evaluation.business_kpi):
        kname = getattr(kpi, "name", "") or f"kpi_{i}"
        _add(
            entries,
            seen_paths,
            duplicates,
            kind="kpi",
            slug=_slug(kname)[:32],
            source_path=f"evaluation.business_kpi[{i}]",
            value={"name": kname, "value": getattr(kpi, "estimated_value", 0.0), "unit": getattr(kpi, "unit", "")},
            agent="BusinessImpactQuantifier",
            trustworthiness="derived",
        )

    # ⑨ Interpretation — global_importance
    for i, imp in enumerate(ctx.interpretation.global_importance):
        feat = getattr(imp, "feature", "") or f"imp_{i}"
        _add(
            entries,
            seen_paths,
            duplicates,
            kind="feature",
            slug=_slug("imp_" + feat),
            source_path=f"interpretation.global_importance[{i}]",
            value={"feature": feat, "importance": getattr(imp, "importance", 0.0)},
            agent="Explainability",
            trustworthiness="derived",
        )

    # ⑩ Limitations — data_gaps + generalization_risk
    for i, lim in enumerate(ctx.limitations.data_gaps):
        desc = getattr(lim, "description", "") or f"gap_{i}"
        _add(
            entries,
            seen_paths,
            duplicates,
            kind="limitation",
            slug=_slug(desc)[:32],
            source_path=f"limitations.data_gaps[{i}]",
            value=desc,
            agent="EvalAgent",
        )
    for i, lim in enumerate(ctx.limitations.generalization_risk):
        desc = getattr(lim, "description", "") or f"risk_{i}"
        _add(
            entries,
            seen_paths,
            duplicates,
            kind="limitation",
            slug=_slug("risk_" + desc)[:32],
            source_path=f"limitations.generalization_risk[{i}]",
            value=desc,
            agent="EvalAgent",
        )

    # ⑪ Code files
    for i, cf in enumerate(ctx.code.files):
        path = getattr(cf, "path", "") or f"code_{i}"
        _add(
            entries,
            seen_paths,
            duplicates,
            kind="code",
            slug=_slug(path)[:32],
            source_path=f"code.files[{i}]",
            value=path,
            agent="CodeArtifactExtractor",
        )

    index = CitationIndex(
        index={e.ref_id: e.to_dict() for e in entries.values()},
        unresolved_refs=[],
    )
    if duplicates:
        # Architect 가 참고할 수 있도록 색인 메타에 기록 — schema 외 키지만 dict 이므로 안전.
        index.index["__meta__"] = {
            "duplicate_paths": duplicates,
            "total_entries": len(entries),
        }
    return index


def apply_ref_ids(ctx: ReportContext, index: CitationIndex | None = None) -> ReportContext:
    """``ReportContext`` 의 dataclass 객체들에 ``ref_id`` 필드 할당.

    ``index`` 가 ``None`` 이면 자동 빌드. 같은 ctx 를 in-place 수정 후 반환.
    """
    if index is None:
        index = build_citation_index(ctx)

    # source_path → ref_id 역색인
    path_to_ref: dict[str, str] = {}
    for ref_id, meta in index.index.items():
        if ref_id == "__meta__":
            continue
        sp = meta.get("source_path", "") if isinstance(meta, dict) else ""
        if sp:
            path_to_ref[sp] = ref_id

    # dataset 은 ref_id 필드 없음 — 스킵
    # 인용 — KB / Web 분리
    for i, cit in enumerate(ctx.domain.kb_citations):
        sp = f"domain.kb_citations[{i}]"
        if sp in path_to_ref and hasattr(cit, "ref_id"):
            cit.ref_id = path_to_ref[sp]
    for i, cit in enumerate(ctx.domain.web_citations):
        sp = f"domain.web_citations[{i}]"
        if sp in path_to_ref and hasattr(cit, "ref_id"):
            cit.ref_id = path_to_ref[sp]

    # preprocessing
    for i, step in enumerate(ctx.preprocessing.applied_steps):
        sp = f"preprocessing.applied_steps[{i}]"
        if sp in path_to_ref and hasattr(step, "ref_id"):
            step.ref_id = path_to_ref[sp]

    # features
    for i, feat in enumerate(ctx.features.created):
        sp = f"features.created[{i}]"
        if sp in path_to_ref and hasattr(feat, "ref_id"):
            feat.ref_id = path_to_ref[sp]

    # eda
    for i, ch in enumerate(ctx.eda.charts):
        sp = f"eda.charts[{i}]"
        if sp in path_to_ref and hasattr(ch, "ref_id"):
            ch.ref_id = path_to_ref[sp]

    # model_selection
    for i, c in enumerate(ctx.model_selection.candidates):
        sp = f"model_selection.candidates[{i}]"
        if sp in path_to_ref and hasattr(c, "ref_id"):
            c.ref_id = path_to_ref[sp]
    if isinstance(ctx.model_selection.chosen, dict) and "model_selection.chosen" in path_to_ref:
        ctx.model_selection.chosen.setdefault("ref_id", path_to_ref["model_selection.chosen"])

    # training
    for i, run in enumerate(ctx.training.runs):
        sp = f"training.runs[{i}]"
        if sp in path_to_ref and hasattr(run, "ref_id"):
            run.ref_id = path_to_ref[sp]

    # evaluation primary + metrics + kpi
    if isinstance(ctx.evaluation.primary_metric, dict) and "evaluation.primary_metric" in path_to_ref:
        ctx.evaluation.primary_metric.setdefault("ref_id", path_to_ref["evaluation.primary_metric"])
    for mname, m in ctx.evaluation.metrics.items():
        sp = f"evaluation.metrics.{mname}"
        if sp in path_to_ref and isinstance(m, dict):
            m.setdefault("ref_id", path_to_ref[sp])
    for i, kpi in enumerate(ctx.evaluation.business_kpi):
        sp = f"evaluation.business_kpi[{i}]"
        if sp in path_to_ref and hasattr(kpi, "ref_id"):
            kpi.ref_id = path_to_ref[sp]

    # interpretation
    for i, imp in enumerate(ctx.interpretation.global_importance):
        sp = f"interpretation.global_importance[{i}]"
        if sp in path_to_ref and hasattr(imp, "ref_id"):
            imp.ref_id = path_to_ref[sp]

    # code
    for i, cf in enumerate(ctx.code.files):
        sp = f"code.files[{i}]"
        if sp in path_to_ref and hasattr(cf, "ref_id"):
            cf.ref_id = path_to_ref[sp]

    ctx.citations = index
    return ctx


def verify_citations(ctx: ReportContext, used_ref_ids: list[str]) -> CitationReport:
    """슬라이드/콘텐츠에서 사용된 ref_id 가 색인에 모두 존재하는지 확인.

    Args:
        ctx: 색인 채워진 ReportContext (``apply_ref_ids`` 사후 권장).
        used_ref_ids: SlideSpec.data_refs / 본문 인용 등 슬라이드에서 사용된 ref_id 모음.

    Returns:
        CitationReport — Architect/QA/completeness 가 참조.
    """
    index_keys = set(k for k in ctx.citations.index.keys() if k != "__meta__")
    unresolved = sorted({r for r in used_ref_ids if r not in index_keys})
    return CitationReport(
        total_refs=len(set(used_ref_ids)),
        resolved=len(set(used_ref_ids) - set(unresolved)),
        unresolved=unresolved,
        duplicate_paths=list((ctx.citations.index.get("__meta__") or {}).get("duplicate_paths") or []),
    )


# ==============================================================
# 내부 헬퍼
# ==============================================================


_SLUG_RE = re.compile(r"[^a-z0-9가-힣]+")


def _slug(s: Any) -> str:
    """문자열을 짧은 식별자로 정규화. 한글 보존, 공백/특수문자만 _ 로."""
    txt = str(s).strip().lower()
    txt = _SLUG_RE.sub("_", txt).strip("_")
    return txt or "unnamed"


def _hash8(*parts: Any) -> str:
    """주어진 부분들을 합쳐 sha256 앞 8자 반환. 결정론적."""
    payload = "|".join(_safe_str(p) for p in parts).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()[:8]


def _safe_str(v: Any) -> str:
    try:
        if isinstance(v, (dict, list, tuple)):
            import json

            return json.dumps(v, ensure_ascii=False, sort_keys=True, default=str)
        return str(v)
    except Exception:
        return repr(v)[:200]


def _safe_snapshot(value: Any) -> Any:
    """value_snapshot 직렬화 안전화 — dataclass/너무 큰 객체는 축약."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if is_dataclass(value):
        return {f.name: _safe_snapshot(getattr(value, f.name)) for f in dc_fields(value)}
    if isinstance(value, dict):
        return {str(k): _safe_snapshot(v) for k, v in list(value.items())[:50]}
    if isinstance(value, (list, tuple)):
        return [_safe_snapshot(v) for v in list(value)[:50]]
    return _safe_str(value)[:500]


def _add(
    entries: dict[str, CitationEntry],
    seen_paths: set[str],
    duplicates: list[str],
    *,
    kind: str,
    slug: str,
    source_path: str,
    value: Any,
    agent: str = "",
    trustworthiness: str = "primary",
) -> Optional[str]:
    """색인 항목 1개 추가. 중복 source_path 는 첫 번째만 등록."""
    if source_path in seen_paths:
        duplicates.append(source_path)
        return None
    seen_paths.add(source_path)
    ref_id = f"{kind}::{slug}#{_hash8(source_path, _safe_str(value))}"
    entries[ref_id] = CitationEntry(
        ref_id=ref_id,
        source_path=source_path,
        source_kind=kind,
        value_snapshot=value,
        origin_agent=agent,
        trustworthiness=trustworthiness,
    )
    return ref_id
