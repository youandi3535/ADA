"""ADR-006 Phase 2-E — Patch sandbox 단위 테스트.

순수 함수 (extract_modified_files / check_scope_violations / check_forbidden_files)
+ PatchValidator.static_check() 중심. 실제 git worktree 통합 테스트는 별도.
"""

from __future__ import annotations

# =============================================================================
# 1. diff parsing — extract_modified_files
# =============================================================================


def test_extract_single_file():
    from ada.error_handler.sandbox import extract_modified_files

    diff = """diff --git a/ada/core/state.py b/ada/core/state.py
--- a/ada/core/state.py
+++ b/ada/core/state.py
@@ -1,3 +1,4 @@
 line1
+new line
 line2
"""
    assert extract_modified_files(diff) == ["ada/core/state.py"]


def test_extract_multiple_files():
    from ada.error_handler.sandbox import extract_modified_files

    diff = """--- a/ada/core/state.py
+++ b/ada/core/state.py
@@ ... @@
--- a/agents/base.py
+++ b/agents/base.py
@@ ... @@
"""
    files = extract_modified_files(diff)
    assert "ada/core/state.py" in files
    assert "agents/base.py" in files
    assert len(files) == 2


def test_extract_new_file():
    from ada.error_handler.sandbox import extract_modified_files

    diff = """--- /dev/null
+++ b/ada/new_module.py
@@ ... @@
+def foo(): pass
"""
    assert "ada/new_module.py" in extract_modified_files(diff)


def test_extract_deleted_file():
    from ada.error_handler.sandbox import extract_modified_files

    diff = """--- a/old/legacy.py
+++ /dev/null
@@ ... @@
-removed
"""
    assert "old/legacy.py" in extract_modified_files(diff)


def test_extract_empty_diff():
    from ada.error_handler.sandbox import extract_modified_files

    assert extract_modified_files("") == []
    assert extract_modified_files(None) == []


# =============================================================================
# 2. check_scope_violations — R-403 영역 검증
# =============================================================================


def test_hj_allowed_ada_core():
    from ada.error_handler.sandbox import check_scope_violations

    assert check_scope_violations(["ada/core/state.py"]) == []


def test_hj_allowed_orchestrator():
    from ada.error_handler.sandbox import check_scope_violations

    assert check_scope_violations(["orchestrator/graph.py"]) == []


def test_hj_allowed_dispatcher():
    from ada.error_handler.sandbox import check_scope_violations

    assert check_scope_violations(["agents/data_profiler.py"]) == []


def test_hj_allowed_outputs():
    from ada.error_handler.sandbox import check_scope_violations

    assert check_scope_violations(["outputs/pdf.py"]) == []


def test_violation_timeseries_handler():
    """CS 영역 — HJ 가 건드리면 영역 위반."""
    from ada.error_handler.sandbox import check_scope_violations

    violations = check_scope_violations(["agents/handlers/timeseries/profiler.py"])
    assert "agents/handlers/timeseries/profiler.py" in violations


def test_violation_anomaly_handler():
    """NY 영역."""
    from ada.error_handler.sandbox import check_scope_violations

    violations = check_scope_violations(["agents/handlers/anomaly/profiler.py"])
    assert "agents/handlers/anomaly/profiler.py" in violations


def test_violation_tabular_handler():
    """jh 영역."""
    from ada.error_handler.sandbox import check_scope_violations

    violations = check_scope_violations(["agents/handlers/tabular/preprocessor.py"])
    assert "agents/handlers/tabular/preprocessor.py" in violations


def test_violation_pipeline_timeseries():
    from ada.error_handler.sandbox import check_scope_violations

    violations = check_scope_violations(["pipelines/timeseries/pipeline.py"])
    assert "pipelines/timeseries/pipeline.py" in violations


def test_mixed_allowed_and_violations():
    from ada.error_handler.sandbox import check_scope_violations

    files = [
        "ada/core/state.py",  # OK
        "agents/handlers/timeseries/profiler.py",  # 위반 (CS)
        "orchestrator/graph.py",  # OK
        "agents/handlers/tabular/insight.py",  # 위반 (jh)
    ]
    violations = check_scope_violations(files)
    assert "agents/handlers/timeseries/profiler.py" in violations
    assert "agents/handlers/tabular/insight.py" in violations
    assert "ada/core/state.py" not in violations
    assert "orchestrator/graph.py" not in violations
    assert len(violations) == 2


# =============================================================================
# 3. check_forbidden_files — 절대 금지 파일
# =============================================================================


def test_forbidden_env_file():
    from ada.error_handler.sandbox import check_forbidden_files

    assert ".env" in check_forbidden_files([".env"])
    assert ".env.local" in check_forbidden_files([".env.local"])


def test_forbidden_alembic_migration():
    from ada.error_handler.sandbox import check_forbidden_files

    assert "migrations/versions/004_foo.py" in check_forbidden_files(["migrations/versions/004_foo.py"])


def test_forbidden_requirements():
    from ada.error_handler.sandbox import check_forbidden_files

    assert "requirements/test.txt" in check_forbidden_files(["requirements/test.txt"])


def test_forbidden_pyproject():
    from ada.error_handler.sandbox import check_forbidden_files

    assert "pyproject.toml" in check_forbidden_files(["pyproject.toml"])


def test_forbidden_ci_workflow():
    from ada.error_handler.sandbox import check_forbidden_files

    assert ".github/workflows/ci.yml" in check_forbidden_files([".github/workflows/ci.yml"])


def test_forbidden_pem_key():
    from ada.error_handler.sandbox import check_forbidden_files

    assert "secrets/private.pem" in check_forbidden_files(["secrets/private.pem"])


def test_normal_file_not_forbidden():
    from ada.error_handler.sandbox import check_forbidden_files

    assert check_forbidden_files(["ada/core/state.py"]) == []
    assert check_forbidden_files(["docs/README.md"]) == []


# =============================================================================
# 4. PatchValidator.static_check()
# =============================================================================


def test_static_check_passes_for_hj_area_diff():
    from ada.error_handler.sandbox import PatchValidator

    diff = """--- a/ada/core/state.py
+++ b/ada/core/state.py
@@ -1 +1 @@
-old
+new
"""
    result = PatchValidator(repo_root="/tmp").static_check(diff)
    assert result.passed is True
    assert result.reason == "static_check_ok"


def test_static_check_rejects_scope_violation():
    from ada.error_handler.sandbox import PatchValidator

    diff = """--- a/agents/handlers/timeseries/profiler.py
+++ b/agents/handlers/timeseries/profiler.py
@@ -1 +1 @@
-old
+evil patch
"""
    result = PatchValidator(repo_root="/tmp").static_check(diff)
    assert result.passed is False
    assert "scope_violation" in result.reason
    assert "agents/handlers/timeseries/profiler.py" in result.scope_violations


def test_static_check_rejects_forbidden_file():
    from ada.error_handler.sandbox import PatchValidator

    diff = """--- a/.env
+++ b/.env
@@ -1 +1 @@
-OLD_KEY=x
+NEW_KEY=stolen
"""
    result = PatchValidator(repo_root="/tmp").static_check(diff)
    assert result.passed is False
    assert "forbidden" in result.reason


def test_static_check_rejects_alembic_migration():
    from ada.error_handler.sandbox import PatchValidator

    diff = """--- a/migrations/versions/005_evil.py
+++ b/migrations/versions/005_evil.py
@@ -1 +1 @@
+drop table users
"""
    result = PatchValidator(repo_root="/tmp").static_check(diff)
    assert result.passed is False
    assert "forbidden" in result.reason


def test_static_check_empty_diff_fails():
    from ada.error_handler.sandbox import PatchValidator

    result = PatchValidator(repo_root="/tmp").static_check("")
    assert result.passed is False
    assert result.reason == "diff_no_files"


def test_static_check_mixed_diff_caught():
    """OK 파일 + 위반 파일 섞여있어도 reject."""
    from ada.error_handler.sandbox import PatchValidator

    diff = """--- a/ada/core/state.py
+++ b/ada/core/state.py
@@ -1 +1 @@
-x
+y
--- a/agents/handlers/anomaly/profiler.py
+++ b/agents/handlers/anomaly/profiler.py
@@ -1 +1 @@
-a
+b
"""
    result = PatchValidator(repo_root="/tmp").static_check(diff)
    assert result.passed is False
    assert "agents/handlers/anomaly/profiler.py" in result.scope_violations


# =============================================================================
# 5. HJ_ALLOWED_PREFIXES / FORBIDDEN_PATTERNS sanity
# =============================================================================


def test_hj_allowed_prefixes_includes_critical_paths():
    from ada.error_handler.sandbox import HJ_ALLOWED_PREFIXES

    required = ("ada/", "orchestrator/", "outputs/", "scripts/")
    for p in required:
        assert p in HJ_ALLOWED_PREFIXES


def test_forbidden_patterns_block_env():
    from ada.error_handler.sandbox import FORBIDDEN_PATTERNS

    assert any(p.search(".env") for p in FORBIDDEN_PATTERNS)
    assert any(p.search(".env.example") for p in FORBIDDEN_PATTERNS)


def test_forbidden_patterns_block_migration():
    from ada.error_handler.sandbox import FORBIDDEN_PATTERNS

    assert any(p.search("migrations/versions/001.py") for p in FORBIDDEN_PATTERNS)


def test_forbidden_patterns_block_requirements():
    from ada.error_handler.sandbox import FORBIDDEN_PATTERNS

    assert any(p.search("requirements/test.txt") for p in FORBIDDEN_PATTERNS)


# =============================================================================
# 6. ValidationResult 직렬화
# =============================================================================


def test_validation_result_to_dict():
    from ada.error_handler.sandbox import ValidationResult

    r = ValidationResult(passed=True, tests_run=10, tests_passed=10, duration_ms=1500)
    d = r.to_dict()
    assert d["passed"] is True
    assert d["tests_run"] == 10
    assert d["duration_ms"] == 1500
