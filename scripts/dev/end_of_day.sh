#!/usr/bin/env bash
# ============================================================
# scripts/dev/end_of_day.sh
# ============================================================
# 하루 작업 마무리 자동화 스크립트.
#
# 실행 순서:
#   0) 의존성 자동 동기화 (pip install -r requirements/dev.txt)
#   1) 영역 검증 (check_scope.sh)
#   2) 로컬 테스트 (pytest)
#   3) origin/main 최신화 (fetch)
#   4) rebase onto origin/main
#   5) rebase 후 테스트 재확인
#   6) push (--force-with-lease)
#
# 사용법:
#   bash scripts/dev/end_of_day.sh
#   bash scripts/dev/end_of_day.sh --skip-tests        # 테스트 건너뛰기
#   bash scripts/dev/end_of_day.sh --no-rebase         # rebase 안 함
#   bash scripts/dev/end_of_day.sh --category timeseries  # 본인 카테고리 테스트만
#
# 수정 권한: HJ 단독
# ============================================================

set -e

# ─── 의존성 자동 동기화 ───
# requirements/dev.txt 는 base + api + worker 를 모두 포함하므로
# 팀원이 별도로 pip install 을 하지 않아도 항상 CI 와 동일한 환경이 보장됩니다.
TEST_REQS="requirements/test.txt"
if [ -f "$TEST_REQS" ]; then
    echo "▶ 테스트 의존성 동기화 중 (pip install -r $TEST_REQS) ..."
    # PYTHONUTF8=1 : Windows 에서 requirements 파일의 한글 주석을 올바르게 읽기 위해 필요
    # test.txt 는 torch/uvloop 등 플랫폼 비호환 패키지를 제외한 경량 파일
    PYTHONUTF8=1 pip install -q --upgrade-strategy only-if-needed -r "$TEST_REQS"
    echo "  완료"
    echo ""
fi

# ─── 옵션 파싱 ───
SKIP_TESTS=0
NO_REBASE=0
CATEGORY=""
for arg in "$@"; do
    case "$arg" in
        --skip-tests)  SKIP_TESTS=1 ;;
        --no-rebase)   NO_REBASE=1 ;;
        --category=*)  CATEGORY="${arg#*=}" ;;
        --category)    ;;  # 다음 인자에서 처리 (간단히 미지원)
        -h|--help)
            sed -n '4,22p' "$0"
            exit 0
            ;;
    esac
done

# ─── 안전 가드 ───
BRANCH=$(git branch --show-current)
if [ -z "$BRANCH" ]; then
    echo "❌ 분리된 HEAD 상태입니다. feature 브랜치로 이동하세요."
    exit 1
fi
if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "develop" ]; then
    echo "❌ '$BRANCH' 브랜치에서는 실행 금지. feature 브랜치에서 실행하세요."
    exit 1
fi

# 깨끗하지 않은 작업 디렉토리 경고
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "⚠️  스테이지/워킹트리에 커밋되지 않은 변경이 있습니다."
    read -r -p "    계속할까요? (y/N): " ans
    [ "$ans" = "y" ] || [ "$ans" = "Y" ] || { echo "취소"; exit 1; }
fi

echo "▶ Branch: $BRANCH"
[ -n "$CATEGORY" ] && echo "▶ Category 한정: $CATEGORY"
echo ""

# ─── Step 1: 영역 검증 ───
echo "▶ 1/6 영역 검증"
if [ -f scripts/dev/check_scope.sh ]; then
    # 커밋된 변경 + 스테이지 변경을 모두 검증하기 위해
    # HEAD 대비 main 과 비교
    bash scripts/dev/check_scope.sh || {
        echo "영역 검증 실패. 위 안내에 따라 수정 후 재시도하세요."
        exit 1
    }
else
    echo "⚠️  scripts/dev/check_scope.sh 없음 — skip"
fi
echo ""

# ─── Step 2: 로컬 테스트 ───
if [ "$SKIP_TESTS" -eq 0 ]; then
    echo "▶ 2/6 로컬 테스트 (--skip-tests 로 건너뛰기 가능)"
    if [ -n "$CATEGORY" ]; then
        pytest "tests/handlers/${CATEGORY}/" -q
    else
        pytest tests/ -q
    fi
    echo ""
else
    echo "▶ 2/6 테스트 skip (--skip-tests)"
    echo ""
fi

# ─── Step 3: origin 최신화 ───
echo "▶ 3/6 origin 최신화 (fetch)"
git fetch origin
echo ""

# ─── Step 4: rebase ───
if [ "$NO_REBASE" -eq 0 ]; then
    echo "▶ 4/6 rebase onto origin/main"

    # 이미 최신이면 rebase skip
    LOCAL_BASE=$(git merge-base "$BRANCH" origin/main)
    REMOTE_HEAD=$(git rev-parse origin/main)
    if [ "$LOCAL_BASE" = "$REMOTE_HEAD" ]; then
        echo "  이미 origin/main 최신 — rebase 불필요"
    else
        git rebase origin/main || {
            echo ""
            echo "❌ rebase 충돌 발생. 수동 해결 후 다시 실행하세요:"
            echo "    git rebase --continue   (충돌 해결 후)"
            echo "    git rebase --abort      (취소)"
            exit 1
        }
    fi
    echo ""
else
    echo "▶ 4/6 rebase skip (--no-rebase)"
    echo ""
fi

# ─── Step 5: rebase 후 재테스트 ───
if [ "$SKIP_TESTS" -eq 0 ] && [ "$NO_REBASE" -eq 0 ]; then
    echo "▶ 5/6 rebase 후 테스트 재확인"
    if [ -n "$CATEGORY" ]; then
        pytest "tests/handlers/${CATEGORY}/" -q
    else
        pytest tests/ -q
    fi
    echo ""
else
    echo "▶ 5/6 재테스트 skip"
    echo ""
fi

# ─── Step 6: push ───
echo "▶ 6/6 push (--force-with-lease)"
git push --force-with-lease origin "$BRANCH"
echo ""

# ─── 완료 안내 ───
REPO_URL=$(git remote get-url origin 2>/dev/null | sed -E 's|git@github.com:|https://github.com/|; s|\.git$||')
PR_URL="${REPO_URL}/pull/new/${BRANCH}"

echo "─────────────────────────────────────────────────────────"
echo "✅ 완료!"
echo ""
echo "다음 단계:"
echo "  1) PR 생성/갱신: $PR_URL"
echo "  2) CI 그린 확인 (lint-and-test, docker-build-check)"
echo "  3) Code owner 리뷰 받기"
echo "  4) Merge (또는 merge queue 추가)"
echo "─────────────────────────────────────────────────────────"
