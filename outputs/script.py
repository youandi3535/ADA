"""outputs.script — OUT-03 발표 대본 (.txt). ADR-008 L2 reattach 통합."""

from __future__ import annotations

from typing import Any

from outputs.base import OutputGenerator, reattach_pii


class ScriptGenerator(OutputGenerator):
    output_code = "OUT-03"
    extension = "txt"

    def generate(
        self,
        *,
        insights: str,
        best_model: dict[str, Any],
        eda_charts: list[str],
        category: str,
        user_intent: str,
        eval_result: dict[str, Any] | None,
        state: Any = None,
    ) -> str:
        # ADR-008 L2 — PII 마스킹
        insights = reattach_pii(state, insights)
        user_intent = reattach_pii(state, user_intent)

        bm = best_model or {}
        ev = eval_result or {}
        body = f"""[ADA 발표 대본]

여러분 안녕하세요. 오늘은 '{user_intent or "자동 분석"}' 주제로
{category} 분석 결과를 공유드리겠습니다.

먼저, 최적 모델로 {bm.get("model_name", "-")} 를 선정했습니다.
주요 평가 지표는 다음과 같습니다:
{chr(10).join(f"  - {k}: {v}" for k, v in (bm.get("metrics") or {}).items())}

핵심 인사이트는 다음과 같습니다.

{insights}

평가 결과는 {"통과" if ev.get("passed") else "보완 필요"} 입니다.
이상으로 발표를 마치겠습니다. 감사합니다.
"""
        local = self._tmp()
        with open(local, "w", encoding="utf-8") as f:
            f.write(body)
        return self._upload(local)
