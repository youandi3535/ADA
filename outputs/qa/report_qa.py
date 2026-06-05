"""outputs.qa.report_qa — 7축 채점 (Phase 6, Part 15-1).

A. Pyramid                — message_tree 통과 + ExecSummary 결론 선언
B. MECE                   — 섹션 안 So-What 중첩
C. So-What 품질            — 6항목 평균
D. Numerical Consistency  — ref_id 별 값 일관 (hard)
E. Tone                   — 종결어미 일관·길이 (청중별)
F. Citation Coverage      — 미해결 ref_id 0 (hard)
G. Visual Hierarchy       — 텍스트-only 슬라이드 ≤ 30%

각 축 0~100. D, F 미달 시 보고서 차단.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from outputs.architect.mece_validator import validate_mece
from outputs.architect.message_tree import validate_pyramid
from outputs.architect.plan import ReportPlan
from outputs.content.so_what_scorer import score_plan_so_whats
from outputs.context.schema import ReportContext
from outputs.qa.numerical_consistency import check_numerical_consistency


@dataclass
class QAReport:
    axis_scores: dict[str, float] = field(default_factory=dict)
    axis_thresholds: dict[str, float] = field(default_factory=dict)
    blocking_failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.blocking_failures

    def to_dict(self) -> dict:
        return {
            "axis_scores": dict(self.axis_scores),
            "thresholds": dict(self.axis_thresholds),
            "blocking_failures": list(self.blocking_failures),
            "warnings": list(self.warnings),
            "passed": self.passed,
        }


class ReportQA:
    """7축 자가 채점기."""

    AXIS_THRESHOLDS = {
        "A_pyramid": 80,
        "B_mece": 75,
        "C_so_what": 85,
        "D_numerical": 100,  # hard
        "E_tone": 80,
        "F_citation": 100,  # hard
        "G_visual_hierarchy": 80,
    }

    HARD_AXES = {"D_numerical", "F_citation"}

    def score(self, plan: ReportPlan, ctx: ReportContext) -> QAReport:
        report = QAReport(axis_thresholds=dict(self.AXIS_THRESHOLDS))

        # A. Pyramid
        py = validate_pyramid(plan)
        py_score = 100.0 * (
            1.0 - min(1.0, (len(py.orphan_slides) + len(py.unreachable_nodes)) / max(1, py.total_slides))
        )
        py_score = max(0, py_score)
        report.axis_scores["A_pyramid"] = round(py_score, 1)
        report.details["pyramid"] = py.to_dict()

        # B. MECE
        me = validate_mece(plan)
        me_score = 100.0 - min(100.0, me.total_issues() * 12)
        report.axis_scores["B_mece"] = round(max(0, me_score), 1)
        report.details["mece"] = me.to_dict()

        # C. So-What
        sw = score_plan_so_whats(plan)
        sw_score = (sw["passed"] / max(1, sw["total"])) * 100
        report.axis_scores["C_so_what"] = round(sw_score, 1)
        report.details["so_what"] = {"total": sw["total"], "passed": sw["passed"], "fail_rate": sw["fail_rate"]}

        # D. Numerical Consistency
        nc = check_numerical_consistency(plan, ctx)
        nc_score = 100.0 if not nc["mismatches"] else 0.0
        report.axis_scores["D_numerical"] = nc_score
        report.details["numerical"] = nc

        # E. Tone
        tone_score = self._score_tone(plan)
        report.axis_scores["E_tone"] = round(tone_score, 1)

        # F. Citation Coverage
        used = plan.used_ref_ids()
        index_keys = set(k for k in (ctx.citations.index or {}) if k != "__meta__")
        missing = [r for r in used if r and r not in index_keys]
        report.axis_scores["F_citation"] = 100.0 if not missing else 0.0
        report.details["citation_missing"] = missing

        # G. Visual Hierarchy
        all_slides = [s for s in plan.all_slides() if s.role != "meta"]
        text_only = [s for s in all_slides if not s.visual_spec or s.visual_spec.type in ("", "text_only")]
        ratio = len(text_only) / max(1, len(all_slides))
        g_score = 100.0 * (1 - ratio) if ratio <= 0.5 else 50.0 * (1 - ratio)
        report.axis_scores["G_visual_hierarchy"] = round(max(0, g_score), 1)
        report.details["visual"] = {"total": len(all_slides), "text_only": len(text_only), "ratio": round(ratio, 3)}

        # 차단 사유 / 경고 분류
        for axis, score in report.axis_scores.items():
            threshold = self.AXIS_THRESHOLDS[axis]
            if score < threshold:
                if axis in self.HARD_AXES:
                    report.blocking_failures.append(f"{axis}: {score} < {threshold}")
                else:
                    report.warnings.append(f"{axis}: {score} < {threshold}")

        return report

    def _score_tone(self, plan: ReportPlan) -> float:
        """종결어미 일관 + 본문 길이 적정성."""
        from outputs.localization.korean import detect_ending_style

        all_slides = [s for s in plan.all_slides() if s.role != "meta"]
        endings = []
        for s in all_slides:
            text = " ".join(s.body_outline) + " " + (s.so_what or "")
            e = detect_ending_style(text)
            if e:
                endings.append(e)
        if not endings:
            return 80.0
        # 가장 흔한 종결 비율
        common = max(set(endings), key=endings.count)
        consistency = endings.count(common) / len(endings)
        return consistency * 100
