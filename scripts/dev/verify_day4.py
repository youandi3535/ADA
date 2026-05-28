"""ADR-008 hj-day4 자체 검증 스크립트.

L1~L4 의 모든 가시적 변경을 한 번에 정적 검증.
실행: PYTHONUTF8=1 python scripts/dev/verify_day4.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

results: list[tuple[str, bool, str]] = []


def check(name: str):
    def wrapper(fn):
        try:
            fn()
            results.append((name, True, ""))
            print(f"  OK  {name}")
        except Exception as e:
            results.append((name, False, str(e)))
            print(f"  FAIL  {name}: {e}")
        return fn

    return wrapper


print("=" * 70)
print("ADR-008 hj-day4 검증 (Maxi: L1+L2+L3+L4)")
print("=" * 70)


# ===== L1 — 기존 6 + Insight hook =====================================
print("\n[L1] 기존 코드 회귀 검증")


@check("L1.1.a — Day 4 pytest 6 케이스 정의")
def _():
    src = (REPO_ROOT / "tests/test_day4_pii_anonymize.py").read_text(encoding="utf-8")
    for t in [
        "test_detect_and_anonymize_df",
        "test_anonymize_text_deterministic",
        "test_reattach_masks_to_stars",
        "test_reattach_blocks_self_generated_pii",
        "test_security_guard_stores_pii_mapping",
        "test_injection_blocked_by_guard",
    ]:
        assert f"def {t}" in src, f"누락: {t}"


@check("L1.2.a — SecurityGuardAgent.__call__ 가 _pii 저장")
def _():
    src = (REPO_ROOT / "agents/security_guard.py").read_text(encoding="utf-8")
    assert 'extras["_pii"]' in src
    assert '"mapping": mapping' in src


@check("L1.2.b — InsightAgent 가 _pii 로 reattach")
def _():
    src = (REPO_ROOT / "agents/insight.py").read_text(encoding="utf-8")
    assert '.get("_pii")' in src
    assert "reattach_for_user" in src


# ===== L2 — Output Carrier reattach ===================================
print("\n[L2] Output Carrier reattach")


@check("L2.1 — outputs/base.py 에 reattach_pii 정의")
def _():
    src = (REPO_ROOT / "outputs/base.py").read_text(encoding="utf-8")
    assert "def reattach_pii(" in src
    assert "PIIAnonymizer" in src


@check("L2.2.a — markdown_insight reattach 호출")
def _():
    src = (REPO_ROOT / "outputs/markdown_insight.py").read_text(encoding="utf-8")
    assert "reattach_pii" in src


@check("L2.2.b — pdf reattach 호출")
def _():
    src = (REPO_ROOT / "outputs/pdf.py").read_text(encoding="utf-8")
    assert "reattach_pii" in src


@check("L2.2.c — ppt reattach 호출")
def _():
    src = (REPO_ROOT / "outputs/ppt.py").read_text(encoding="utf-8")
    assert "reattach_pii" in src


@check("L2.2.d — html_dashboard reattach 호출")
def _():
    src = (REPO_ROOT / "outputs/html_dashboard.py").read_text(encoding="utf-8")
    assert "reattach_pii" in src


@check("L2.2.e — script reattach 호출")
def _():
    src = (REPO_ROOT / "outputs/script.py").read_text(encoding="utf-8")
    assert "reattach_pii" in src


@check("L2.3 — report_composer 가 state 전달")
def _():
    src = (REPO_ROOT / "agents/report_composer.py").read_text(encoding="utf-8")
    assert 'kwargs["state"] = state' in src or "state=state" in src


@check("L2.4 — tests/test_day4_carrier_reattach.py 존재 + 핵심 케이스")
def _():
    p = REPO_ROOT / "tests/test_day4_carrier_reattach.py"
    assert p.exists()
    src = p.read_text(encoding="utf-8")
    for t in [
        "test_reattach_pii_helper_with_empty_state",
        "test_reattach_pii_helper_with_mapping",
        "test_markdown_insight_redacts_pii",
        "test_script_redacts_pii",
        "test_html_dashboard_redacts_pii",
    ]:
        assert f"def {t}" in src


# ===== L3 — 패턴 정리 + df 마스킹 ======================================
print("\n[L3] 패턴 정리 + DataFrame 마스킹")


@check("L3.1.a — redactor docstring 의도 분리")
def _():
    src = (REPO_ROOT / "ada/error_handler/redactor.py").read_text(encoding="utf-8")
    assert "의도 분리" in src or "Intent separation" in src


@check("L3.1.b — guardrails docstring 의도 분리")
def _():
    src = (REPO_ROOT / "ada/security/guardrails.py").read_text(encoding="utf-8")
    assert "의도 분리" in src or "Intent separation" in src


@check("L3.2.a — _pii_patterns.py 신규")
def _():
    p = REPO_ROOT / "ada/security/_pii_patterns.py"
    assert p.exists()
    src = p.read_text(encoding="utf-8")
    for sym in ["EMAIL_RE", "PHONE_KR_RE", "RRN_RE", "CARD_RE", "COMMON_PATTERNS"]:
        assert sym in src


@check("L3.2.b — guardrails 가 _pii_patterns import")
def _():
    src = (REPO_ROOT / "ada/security/guardrails.py").read_text(encoding="utf-8")
    assert "from ada.security._pii_patterns" in src


@check("L3.2.c — redactor 가 _pii_patterns import")
def _():
    src = (REPO_ROOT / "ada/error_handler/redactor.py").read_text(encoding="utf-8")
    assert "from ada.security._pii_patterns" in src


@check("L3.3.a — data_profiler 가 df 마스킹 hook")
def _():
    src = (REPO_ROOT / "agents/data_profiler.py").read_text(encoding="utf-8")
    assert "_anonymize_uploaded_df" in src
    assert "_merge_pii_extras" in src


@check("L3.3.b — pytest df 마스킹 케이스 3건")
def _():
    src = (REPO_ROOT / "tests/test_day4_carrier_reattach.py").read_text(encoding="utf-8")
    for t in [
        "test_data_profiler_anonymizes_df_columns",
        "test_data_profiler_merges_pii_extras",
        "test_data_profiler_anonymize_handles_no_pii",
    ]:
        assert f"def {t}" in src


# ===== L4 — 어드민 PII 위젯 ============================================
print("\n[L4] 어드민 PII 위젯")


@check("L4.1.a — /admin/security/pii 라우트")
def _():
    src = (REPO_ROOT / "api/routes/admin.py").read_text(encoding="utf-8")
    assert "/admin/security/pii" in src
    assert "PIIStatsResponse" in src
    assert "pii_anonymized" in src


@check("L4.1.b — pytest test_admin_pii_stats_*")
def _():
    src = (REPO_ROOT / "tests/test_day4_carrier_reattach.py").read_text(encoding="utf-8")
    assert "test_admin_pii_stats_route_registered" in src
    assert "test_admin_pii_stats_returns_aggregate" in src


@check("L4.2 — frontend admin PII 위젯")
def _():
    src = (REPO_ROOT / "frontend/app.py").read_text(encoding="utf-8")
    assert "/admin/security/pii" in src
    assert "PII 마스킹" in src


# ===== 결과 요약 =======================================================
print("\n" + "=" * 70)
passed = sum(1 for _, ok, _ in results if ok)
failed = sum(1 for _, ok, _ in results if not ok)
print(f"PASSED: {passed} / {len(results)}")
print(f"FAILED: {failed}")
if failed:
    print("\n실패 항목:")
    for name, ok, err in results:
        if not ok:
            print(f"  - {name}: {err}")
    sys.exit(1)
print("✅ 전체 검증 통과 (Maxi: L1+L2+L3+L4)")
sys.exit(0)
