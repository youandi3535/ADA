"""outputs.carriers.template_registry - Extensible template selection engine.

Adding a new template:
    @register("my_template", fit=my_fit_fn)
    def draw_my_template(slide, sl, ctx, primary, accent, ink, muted, light_bg):
        ...

The fit function returns a score 0..100 indicating how well this template
suits the slide+context. The engine picks the highest scoring template.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# Type aliases
FitFn = Callable[["Any", "Any"], float]  # (slide, ctx) -> score 0..100
DrawFn = Callable[..., None]  # signature varies by template


@dataclass
class TemplateSpec:
    name: str
    draw: DrawFn
    fit: FitFn
    tags: list[str] = field(default_factory=list)
    min_score: float = 10.0  # below this score, template won't be chosen


class TemplateRegistry:
    """Global registry of available slide templates."""

    def __init__(self) -> None:
        self._specs: dict[str, TemplateSpec] = {}

    def register(
        self, name: str, draw: DrawFn, fit: FitFn, tags: Optional[list[str]] = None, min_score: float = 10.0
    ) -> None:
        self._specs[name] = TemplateSpec(
            name=name,
            draw=draw,
            fit=fit,
            tags=list(tags or []),
            min_score=min_score,
        )

    def all(self) -> list[TemplateSpec]:
        return list(self._specs.values())

    def get(self, name: str) -> Optional[TemplateSpec]:
        return self._specs.get(name)

    def best_for(self, slide, ctx) -> Optional[TemplateSpec]:
        """Pick the highest scoring template for a given slide+context.

        Honors slide.meta override if present (slide.preferred_template).
        """
        # Manual override via slide attribute
        override = getattr(slide, "preferred_template", None)
        if override and override in self._specs:
            return self._specs[override]
        # Score all templates
        best: Optional[TemplateSpec] = None
        best_score = -1.0
        for spec in self._specs.values():
            try:
                score = float(spec.fit(slide, ctx))
            except Exception:
                continue
            if score < spec.min_score:
                continue
            if score > best_score:
                best = spec
                best_score = score
        return best

    def all_scored(self, slide, ctx) -> list[tuple[str, float]]:
        """Debug: return all templates with their scores, sorted descending."""
        out = []
        for spec in self._specs.values():
            try:
                out.append((spec.name, float(spec.fit(slide, ctx))))
            except Exception:
                out.append((spec.name, 0.0))
        out.sort(key=lambda x: -x[1])
        return out


# Global default registry
REGISTRY = TemplateRegistry()


def register(
    name: str, *, fit: FitFn, tags: Optional[list[str]] = None, min_score: float = 10.0
) -> Callable[[DrawFn], DrawFn]:
    """Decorator to register a draw function as a template."""

    def deco(draw: DrawFn) -> DrawFn:
        REGISTRY.register(name, draw, fit, tags, min_score)
        return draw

    return deco


# ==============================================================
# Common fit predicates - reusable building blocks
# ==============================================================


def has_metrics(min_n: int = 1) -> FitFn:
    return lambda sl, c: 60.0 if len(c.evaluation.metrics) >= min_n else 0.0


def has_id(*ids: str) -> FitFn:
    s = set(ids)
    return lambda sl, c: 90.0 if sl.id in s else 0.0


def has_layout(*layouts: str) -> FitFn:
    s = set(layouts)
    return lambda sl, c: 70.0 if sl.layout in s else 0.0


def has_role(*roles: str) -> FitFn:
    s = set(roles)
    return lambda sl, c: 55.0 if sl.role in s else 0.0


def has_body_min(n: int) -> FitFn:
    return lambda sl, c: 50.0 if len(sl.body_outline) >= n else 0.0


def has_category(*cats: str) -> FitFn:
    s = set(cats)
    return lambda sl, c: 50.0 if c.meta.category in s else 0.0


def matches_keywords(*kws: str) -> FitFn:
    s = [k.lower() for k in kws]

    def f(sl, c):
        text = (sl.id + " " + (sl.title_ko or "") + " " + (sl.so_what or "")).lower()
        return 40.0 if any(k in text for k in s) else 0.0

    return f


def combine(*fns: FitFn, mode: str = "max") -> FitFn:
    """Combine multiple fit functions: max, sum, or mul."""

    def f(sl, c):
        vals = [fn(sl, c) for fn in fns]
        if mode == "sum":
            return sum(vals)
        if mode == "mul":
            r = 1.0
            for v in vals:
                r *= v / 100.0
            return r * 100.0
        return max(vals) if vals else 0.0

    return f
