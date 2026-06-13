#!/usr/bin/env bash
# ============================================================
# scripts/dev/check_shared_deps.sh
# ============================================================
# 공유 의존성 파일 (requirements/*.txt, pyproject.toml,
# .pre-commit-config.yaml, alembic.ini, .github/) 수정 시 경고.
#
# 경고만 출력하고 항상 통과 (exit 0).
# 실제 차단은 CODEOWNERS 가 PR 단계에서 강제한다.
#
# pre-commit 의 인라인 `bash -c '...'` entry 는 Windows 에서
# 괄호(`(`) 가 포함된 명령 치환을 셸로 재파싱할 때
# `syntax error near unexpected token '('` 로 깨진다.
# 그래서 별도 스크립트 파일로 분리했다.
#
# 수정 권한: HJ 단독 (.github/CODEOWNERS 참조)
# ============================================================

changed=$(git diff --cached --name-only \
    | grep -E "^(requirements/.*\.txt|pyproject\.toml|\.pre-commit-config\.yaml|alembic\.ini|\.github/)" || true)

if [ -n "$changed" ]; then
    echo "⚠️  공유 파일 수정 감지 — HJ 리뷰 필요:"
    echo "$changed" | sed 's/^/  - /'
fi

exit 0
