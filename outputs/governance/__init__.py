"""outputs.governance — 메타데이터·서명·승인 (Phase 6, Part 16).

모듈:
    metadata.py            — 표지·마지막 페이지 메타 블록 생성
    classification_marker.py — 등급별 워터마크·헤더 띠 적용
    signature.py           — SHA256 봉인 (파일 + ReportContext 해시)
    approval_workflow.py   — draft/approved 상태 hook
"""

from outputs.governance.classification_marker import apply_classification  # noqa: F401
from outputs.governance.metadata import build_report_metadata  # noqa: F401
from outputs.governance.signature import sign_report, verify_signature  # noqa: F401
