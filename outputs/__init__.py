"""ADA v2 — 5종 산출물 생성기.

OUT-01 PPT  (.pptx)   PresentationGenerator
OUT-02 PDF  (.pdf)    PDFReportGenerator
OUT-03 TXT  (.txt)    ScriptGenerator
OUT-04 HTML (.html)   DashboardArtifactGenerator
OUT-07 MD   (.md)     InsightSummaryGenerator
"""

from outputs.ppt import PresentationGenerator  # noqa: F401
from outputs.pdf import PDFReportGenerator  # noqa: F401
from outputs.script import ScriptGenerator  # noqa: F401
from outputs.html_dashboard import DashboardArtifactGenerator  # noqa: F401
from outputs.markdown_insight import InsightSummaryGenerator  # noqa: F401

GENERATORS = {
    "OUT-01": PresentationGenerator,
    "OUT-02": PDFReportGenerator,
    "OUT-03": ScriptGenerator,
    "OUT-04": DashboardArtifactGenerator,
    "OUT-07": InsightSummaryGenerator,
}

# 카테고리별 PPT 테마 색상 (v2 4색)
CATEGORY_COLORS = {
    "tabular_ml":         "#2563eb",  # 파랑
    "tabular_dl":         "#0891b2",  # 청록
    "timeseries":         "#16a34a",  # 초록
    "anomaly_detection":  "#dc2626",  # 빨강
}
