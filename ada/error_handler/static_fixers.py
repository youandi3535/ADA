"""ada.error_handler.static_fixers — 6종 결정론적 Python 오류 Fixer (LLM 비용 0).

패턴이 명확한 오류를 regex/AST 분석으로 즉시 수정 diff 생성.
LLM 호출 없이 < 100ms 처리 → auto_handler Tier 0 으로 사용.

지원 Fixer:
    1. relative_import    ModuleNotFoundError: No module named 'X'
    2. none_slicing       TypeError: 'NoneType' object is not subscriptable
    3. name_typo          NameError: name 'X' is not defined
    4. none_attribute     AttributeError: 'NoneType' object has no attribute 'X'
    5. import_name        ImportError: cannot import name 'X' from 'Y'
    6. unpack_mismatch    ValueError: too many/not enough values to unpack
"""

from __future__ import annotations

import ast
import difflib
import re
from pathlib import Path
from typing import Any

# =============================================================================
# 공통 유틸
# =============================================================================

# Docker 컨테이너는 /app, 로컬 개발 환경은 프로젝트 루트(이 파일 기준 3단계 상위)
_PROJECT_ROOT: Path = (
    Path("/app")
    if Path("/app").exists()
    else Path(__file__).resolve().parents[2]  # ada/error_handler/static_fixers.py → repo root
)


def _parse_last_file_and_line(stack_trace: str) -> tuple[Path | None, int]:
    """스택 트레이스에서 마지막 파일 경로 + 라인 번호 추출.

    예: 'File "/app/ada/agents/foo.py", line 42, in bar'
    """
    pattern = re.compile(r'File "([^"]+)", line (\d+)')
    matches = pattern.findall(stack_trace)
    if not matches:
        return None, -1
    # /app/ 프로젝트 파일만 선택 (stdlib / site-packages 제외)
    for fpath, lineno in reversed(matches):
        p = Path(fpath)
        if str(p).startswith(str(_PROJECT_ROOT)) and p.suffix == ".py":
            return p, int(lineno)
    return None, -1


def _read_source(path: Path) -> list[str] | None:
    """소스 파일 라인 목록 반환. 실패 시 None."""
    try:
        return path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError:
        return None


def _make_diff(original: list[str], modified: list[str], path: Path) -> str:
    """unified diff 문자열 생성."""
    rel = str(path).replace(str(_PROJECT_ROOT), "").lstrip("/\\")
    return "".join(
        difflib.unified_diff(
            original,
            modified,
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
            lineterm="",
        )
    )


def _result(diff: str, test_plan: str, confidence: float, fixer: str) -> dict[str, Any]:
    return {
        "diff": diff,
        "test_plan": test_plan,
        "confidence": confidence,
        "fixer": fixer,
        "tier": "static",
    }


# =============================================================================
# Fixer 1: relative_import
# ModuleNotFoundError: No module named 'X'
# =============================================================================


def _fix_relative_import(error_message: str, stack_trace: str) -> dict[str, Any] | None:
    """ModuleNotFoundError → 상대/절대 import 경로 수정."""
    m = re.search(
        r"ModuleNotFoundError: No module named '([^']+)'",
        error_message,
    )
    if not m:
        return None

    missing_module = m.group(1)  # e.g. "utils" or "config"

    fpath, lineno = _parse_last_file_and_line(stack_trace)
    if not fpath or lineno < 1:
        return None

    lines = _read_source(fpath)
    if not lines:
        return None

    # 오류 발생 라인 찾기 (0-indexed)
    idx = lineno - 1
    if idx >= len(lines):
        return None
    line = lines[idx]

    # 프로젝트 내에서 동일한 이름의 모듈 검색 (최대 5개)
    candidates = sorted(_PROJECT_ROOT.rglob(f"{missing_module}.py"))[:5]

    if not candidates:
        return None

    # 가장 가까운 후보 선택
    best = candidates[0]
    rel = best.relative_to(_PROJECT_ROOT)
    pkg_path = ".".join(rel.with_suffix("").parts)  # e.g. "ada.core.utils"

    # import 패턴 수정
    modified = lines.copy()
    new_line = re.sub(
        r"\bimport\s+" + re.escape(missing_module),
        f"import {pkg_path}",
        line,
    )
    new_line = re.sub(
        r"\bfrom\s+" + re.escape(missing_module) + r"\b",
        f"from {pkg_path}",
        new_line,
    )

    if new_line == line:
        return None

    modified[idx] = new_line
    diff = _make_diff(lines, modified, fpath)
    if not diff:
        return None

    return _result(
        diff=diff,
        test_plan=f"import {pkg_path} 로 수정 후 재실행",
        confidence=0.75,
        fixer="relative_import",
    )


# =============================================================================
# Fixer 2: none_slicing
# TypeError: 'NoneType' object is not subscriptable
# =============================================================================


def _fix_none_slicing(error_message: str, stack_trace: str) -> dict[str, Any] | None:
    """NoneType subscriptable TypeError → (x or '') / (x or []) 가드 추가."""
    if "NoneType" not in error_message or "subscriptable" not in error_message:
        return None

    fpath, lineno = _parse_last_file_and_line(stack_trace)
    if not fpath or lineno < 1:
        return None

    lines = _read_source(fpath)
    if not lines:
        return None

    idx = lineno - 1
    if idx >= len(lines):
        return None

    line = lines[idx]

    # 할당 좌변 패턴(var["key"] = ...) 은 건너뜀 — 변환하면 SyntaxError 발생
    # e.g.  data["key"] = value  → (data or {}).get("key", "") = value  ← 불법
    if re.match(r"^\s*\w+\[", line) and re.search(r"\]\s*=\s*(?!=)", line):
        return None

    # 패턴 1: var["key"] 또는 var[0] → (var or {})["key"] / (var or [])[0]
    # 패턴 2: var["key"][:N] → (var or {}).get("key", "")[:N]
    # 단순 대응: .get() 체인 없이 가드 표현식만 삽입
    modified = lines.copy()

    # var["..."] → (var or {}).get("...")  (dict 접근 추정)
    dict_access = re.sub(
        r'(\b\w+)\["([^"]+)"\]',
        r'(\1 or {}).get("\2", "")',
        line,
    )
    # var[N] → (var or [])[N]  (list 접근 추정)
    list_access = re.sub(
        r"(\b\w+)\[(\d+)\]",
        r"(\1 or [])[\2]",
        dict_access,
    )

    if list_access == line:
        return None

    modified[idx] = list_access
    diff = _make_diff(lines, modified, fpath)
    if not diff:
        return None

    return _result(
        diff=diff,
        test_plan="None 가드 추가 후 동일 입력으로 재실행",
        confidence=0.70,
        fixer="none_slicing",
    )


# =============================================================================
# Fixer 3: name_typo
# NameError: name 'X' is not defined
# =============================================================================


def _fix_name_typo(error_message: str, stack_trace: str) -> dict[str, Any] | None:
    """NameError → 가장 유사한 정의된 이름으로 교체 (difflib 0.70 이상)."""
    m = re.search(r"NameError: name '([^']+)' is not defined", error_message)
    if not m:
        return None

    wrong_name = m.group(1)

    fpath, lineno = _parse_last_file_and_line(stack_trace)
    if not fpath or lineno < 1:
        return None

    lines = _read_source(fpath)
    if not lines:
        return None

    # 소스 전체에서 정의된 이름 수집 (AST)
    try:
        tree = ast.parse("".join(lines))
    except SyntaxError:
        return None

    defined: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    defined.add(t.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                defined.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                defined.add(alias.asname or alias.name)

    if not defined:
        return None

    matches = difflib.get_close_matches(wrong_name, defined, n=1, cutoff=0.70)
    if not matches:
        return None

    correct_name = matches[0]
    idx = lineno - 1
    if idx >= len(lines):
        return None

    modified = lines.copy()
    modified[idx] = re.sub(r"\b" + re.escape(wrong_name) + r"\b", correct_name, lines[idx])

    if modified[idx] == lines[idx]:
        return None

    diff = _make_diff(lines, modified, fpath)
    return _result(
        diff=diff,
        test_plan=f"'{wrong_name}' → '{correct_name}' 교체 후 재실행",
        confidence=0.80,
        fixer="name_typo",
    )


# =============================================================================
# Fixer 4: none_attribute
# AttributeError: 'NoneType' object has no attribute 'X'
# =============================================================================


def _fix_none_attribute(error_message: str, stack_trace: str) -> dict[str, Any] | None:
    """NoneType AttributeError → None 체크 가드 삽입."""
    m = re.search(
        r"AttributeError: 'NoneType' object has no attribute '([^']+)'",
        error_message,
    )
    if not m:
        return None

    attr_name = m.group(1)

    fpath, lineno = _parse_last_file_and_line(stack_trace)
    if not fpath or lineno < 1:
        return None

    lines = _read_source(fpath)
    if not lines:
        return None

    idx = lineno - 1
    if idx >= len(lines):
        return None

    line = lines[idx]
    indent = len(line) - len(line.lstrip())
    ws = " " * indent

    # var.attr 패턴 찾기
    dot_pattern = re.search(r"(\b\w+)\." + re.escape(attr_name), line)
    if not dot_pattern:
        return None

    var_name = dot_pattern.group(1)

    # self/cls 는 제외
    if var_name in ("self", "cls"):
        return None

    modified = lines.copy()
    # 가드 라인 삽입: if var is None: return / var = var or default
    guard_line = f"{ws}if {var_name} is None:\n{ws}    return  # None 가드 추가 by static_fixer\n"
    modified.insert(idx, guard_line)

    diff = _make_diff(lines, modified, fpath)
    return _result(
        diff=diff,
        test_plan=f"{var_name} is None 체크 후 재실행",
        confidence=0.65,
        fixer="none_attribute",
    )


# =============================================================================
# Fixer 5: import_name
# ImportError: cannot import name 'X' from 'Y'
# =============================================================================


def _fix_import_name(error_message: str, stack_trace: str) -> dict[str, Any] | None:
    """ImportError cannot import name → 유사한 exported 이름으로 교체."""
    m = re.search(
        r"ImportError: cannot import name '([^']+)' from '([^']+)'",
        error_message,
    )
    if not m:
        return None

    wrong_name = m.group(1)
    module_path = m.group(2)  # e.g. "ada.core.config"

    # 모듈 파일 찾기
    rel_path = module_path.replace(".", "/") + ".py"
    module_file = _PROJECT_ROOT / rel_path
    if not module_file.exists():
        return None

    module_lines = _read_source(module_file)
    if not module_lines:
        return None

    # 모듈의 exported 이름 수집
    try:
        tree = ast.parse("".join(module_lines))
    except SyntaxError:
        return None

    exported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                exported.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and not t.id.startswith("_"):
                    exported.add(t.id)

    matches = difflib.get_close_matches(wrong_name, exported, n=1, cutoff=0.70)
    if not matches:
        return None

    correct_name = matches[0]

    # import 파일 수정
    fpath, lineno = _parse_last_file_and_line(stack_trace)
    if not fpath or lineno < 1:
        return None

    lines = _read_source(fpath)
    if not lines:
        return None

    idx = lineno - 1
    if idx >= len(lines):
        return None

    modified = lines.copy()
    modified[idx] = re.sub(
        r"\b" + re.escape(wrong_name) + r"\b",
        correct_name,
        lines[idx],
    )

    if modified[idx] == lines[idx]:
        return None

    diff = _make_diff(lines, modified, fpath)
    return _result(
        diff=diff,
        test_plan=f"'{wrong_name}' → '{correct_name}' import 수정 후 재실행",
        confidence=0.78,
        fixer="import_name",
    )


# =============================================================================
# Fixer 6: unpack_mismatch
# ValueError: too many/not enough values to unpack
# =============================================================================


def _fix_unpack_mismatch(error_message: str, stack_trace: str) -> dict[str, Any] | None:
    """ValueError unpack mismatch → 언패킹 변수 수 조정 또는 *_extra 추가."""
    if "unpack" not in error_message.lower():
        return None
    if "ValueError" not in error_message:
        return None

    too_many = "too many" in error_message.lower()
    not_enough = "not enough" in error_message.lower()

    if not (too_many or not_enough):
        return None

    fpath, lineno = _parse_last_file_and_line(stack_trace)
    if not fpath or lineno < 1:
        return None

    lines = _read_source(fpath)
    if not lines:
        return None

    idx = lineno - 1
    if idx >= len(lines):
        return None

    line = lines[idx]

    # a, b, c = func() 패턴
    unpack_m = re.match(r"(\s*)(\w[\w\s,*]+?)\s*=\s*(.+)", line.rstrip())
    if not unpack_m:
        return None

    ws = unpack_m.group(1)
    lhs = unpack_m.group(2)
    rhs = unpack_m.group(3)

    modified = lines.copy()

    if too_many:
        # too many → 마지막에 *_rest 추가
        vars_list = [v.strip() for v in lhs.split(",") if v.strip()]
        vars_list.append("*_rest")
        modified[idx] = f"{ws}{', '.join(vars_list)} = {rhs}\n"
    else:
        # not enough → 변수 목록 앞에서 하나 제거 (가장 마지막 변수 제거)
        vars_list = [v.strip() for v in lhs.split(",") if v.strip()]
        if len(vars_list) <= 1:
            return None
        vars_list = vars_list[:-1]
        modified[idx] = f"{ws}{', '.join(vars_list)} = {rhs}\n"

    diff = _make_diff(lines, modified, fpath)
    if not diff:
        return None

    return _result(
        diff=diff,
        test_plan="언패킹 변수 수 조정 후 재실행",
        confidence=0.60,
        fixer="unpack_mismatch",
    )


# =============================================================================
# 공개 진입점
# =============================================================================

_FIXERS = [
    _fix_relative_import,
    _fix_none_slicing,
    _fix_name_typo,
    _fix_none_attribute,
    _fix_import_name,
    _fix_unpack_mismatch,
]


def try_static_fix(error_message: str, stack_trace: str) -> dict[str, Any] | None:
    """6종 정적 Fixer 순서대로 시도. 첫 번째 성공 결과 반환. 없으면 None.

    반환 형식:
        {
            "diff":       str,   # unified diff
            "test_plan":  str,   # 검증 방법
            "confidence": float, # 0.0~1.0
            "fixer":      str,   # fixer 이름
            "tier":       str,   # "static" 고정
        }
    """
    for fixer_fn in _FIXERS:
        try:
            result = fixer_fn(error_message, stack_trace)
            if result:
                return result
        except Exception:  # noqa: BLE001
            continue  # 개별 fixer 실패는 조용히 건너뜀
    return None
