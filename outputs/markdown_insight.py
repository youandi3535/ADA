"""outputs.markdown_insight — OUT-07 인사이트 정리 (.md)."""
from __future__ import annotations

from typing import Any

from outputs.base import OutputGenerator


class InsightSummaryGenerator(OutputGenerator):
    output_code = "OUT-07"
    extension = "md"

    def generate(self, *, insights: str, best_model: dict[str, Any],
                 eda_charts: list[str], category: str, user_intent: str,
                 eval_result: dict[str, Any] | None) -> str:
        bm = best_model or {}
        metrics = bm.get("metrics") or {}
        metric_lines = "\n".join(
            f"- **{k}**: {v if isinstance(v, str) else (f'{v:.4f}' if isinstance(v, float) else v)}"
            for k, v in metrics.items()
        )

        md = f"""# ADA 분석 인사이트 — {self.job_id}

> 카테고리: **{category}** · 사용자 의도: {user_intent or '미지정'}

## 핵심 인사이트
{insights or '_(생성된 인사이트가 없습니다.)_'}

## Best Model
- **모델명**: `{bm.get('model_name', '-')}`
- **프레임워크**: {bm.get('framework', '-')}

### 지표
{metric_lines}

## 평가
- passed: **{(eval_result or {}).get('passed', '-')}**
- 근거: {(eval_result or {}).get('rationale', '-')}

## EDA Charts (MinIO 경로)
{chr(10).join(f"- {c}" for c in eda_charts) if eda_charts else '_(차트 없음)_'}
"""
        local = self._tmp()
        with open(local, "w", encoding="utf-8") as f:
            f.write(md)
        return self._upload(local)
