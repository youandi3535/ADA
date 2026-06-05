"""outputs.architect.domain_enricher — KB·웹 인용 보강 (Phase 2).

ReportContext.domain 의 kb_citations / web_citations / domain_benchmarks 를 보강.

정책 (K-2 확정):
    - DomainEnricher 가 KB 외부(웹)도 인용 가능.
    - 모든 인용은 ``Citation`` 으로 정규화 + R-501 인용 강제 (출처 없는 정보 금지).

설계:
    - 실제 KB·웹 검색은 별도 tools (KBRAG / Web search) 가 담당.
    - 본 모듈은 *오케스트레이션* — 입력으로 받은 인용 후보를 정규화·중복 제거·신뢰도 부여.
    - 외부 의존성 (httpx 등) 직접 호출 안 함 — 호출자가 raw_results 주입.
"""

from __future__ import annotations

from typing import Any

from outputs.context.schema import Citation, ReportContext

# ==============================================================
# 공개 API
# ==============================================================


def enrich_domain(
    ctx: ReportContext,
    *,
    kb_results: list[dict[str, Any]] | None = None,
    web_results: list[dict[str, Any]] | None = None,
    benchmarks: list[dict[str, Any]] | None = None,
) -> ReportContext:
    """ReportContext.domain 을 인용·벤치마크로 보강.

    Args:
        ctx: 보강 대상.
        kb_results: KB 검색 결과 dict 리스트 (각 {title, snippet, source_id, ...}).
        web_results: 웹 검색 결과 dict 리스트 (각 {title, url, snippet, ...}).
        benchmarks: 도메인 벤치마크 dict 리스트 (각 {metric, value, source}).

    Returns:
        in-place 보강된 ReportContext (체이닝 가능).
    """
    if kb_results:
        for r in kb_results[:10]:
            ctx.domain.kb_citations.append(
                Citation(
                    source_kind="kb",
                    title=str(r.get("title") or r.get("source_id") or "KB 항목"),
                    snippet=str(r.get("snippet") or "")[:400],
                    url=str(r.get("url")) if r.get("url") else None,
                    accessed_at=str(r.get("accessed_at")) if r.get("accessed_at") else None,
                )
            )
    if web_results:
        for r in web_results[:10]:
            ctx.domain.web_citations.append(
                Citation(
                    source_kind="web",
                    title=str(r.get("title") or "웹 인용"),
                    snippet=str(r.get("snippet") or "")[:400],
                    url=str(r.get("url")) if r.get("url") else None,
                    accessed_at=str(r.get("accessed_at")) if r.get("accessed_at") else None,
                )
            )
    if benchmarks:
        for b in benchmarks[:10]:
            ctx.domain.domain_benchmarks.append(
                {
                    "metric": str(b.get("metric") or ""),
                    "value": b.get("value"),
                    "source": str(b.get("source") or ""),
                }
            )

    # 중복 제거 (title 기준)
    ctx.domain.kb_citations = _dedup_citations(ctx.domain.kb_citations)
    ctx.domain.web_citations = _dedup_citations(ctx.domain.web_citations)
    return ctx


def _dedup_citations(citations: list[Citation]) -> list[Citation]:
    seen: set[str] = set()
    out: list[Citation] = []
    for c in citations:
        key = (c.title or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out
