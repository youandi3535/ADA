#!/usr/bin/env bash
# =============================================================
# .github/scripts/fill_pr.sh
# PR 제목·본문 자동 채움 스크립트
# GitHub Action (auto-pr.yml) 에서 호출됨
#
# 필요 환경변수:
#   GH_TOKEN    - GitHub API 토큰
#   PR_NUMBER   - PR 번호
#   BASE_SHA    - base 브랜치 SHA
#   HEAD_SHA    - head 브랜치 SHA
#   BRANCH      - head 브랜치명 (예: feat/hj-day2)
# =============================================================
set -e

# ── PR 제목: 마지막 커밋 메시지 ──────────────────────────────
PR_TITLE=$(git log -1 --format="%s" "$HEAD_SHA")

# ── Day 추출 (feat/hj-day2 → 2) ──────────────────────────────
DAY_NUM=$(echo "$BRANCH" | grep -oE 'day[0-9]+' | grep -oE '[0-9]+' || echo "?")

# ── 커밋 목록 (base..head) ────────────────────────────────────
COMMIT_LIST=$(git log "${BASE_SHA}..${HEAD_SHA}" --format="- %s" --reverse)
if [ -z "$COMMIT_LIST" ]; then
    COMMIT_LIST="- (커밋 없음)"
fi

echo "▶ PR #${PR_NUMBER} 업데이트 시작"
echo "  제목: ${PR_TITLE}"
echo "  Day:  Day ${DAY_NUM}"
echo "  커밋:"
echo "$COMMIT_LIST" | sed 's/^/    /'

# ── 현재 PR 본문 가져오기 ────────────────────────────────────
CURRENT_BODY=$(gh pr view "$PR_NUMBER" --json body --jq '.body')

# ── Day 정보 자동 채움 (Day __ → Day N) ─────────────────────
NEW_BODY=$(echo "$CURRENT_BODY" | sed "s/\*\*Day\*\*: Day __/**Day**: Day ${DAY_NUM}/")

# ── 커밋 목록 섹션 삽입/갱신 ────────────────────────────────
# 기존에 "## 📝 커밋 목록" 섹션이 있으면 내용 교체,
# 없으면 "## 🎯 변경 요약" 섹션 뒤의 --- 다음에 새로 삽입
COMMITS_ESCAPED=$(echo "$COMMIT_LIST" | sed 's/[&/\]/\\&/g')

if echo "$NEW_BODY" | grep -qF "## 📝 커밋 목록"; then
    # 기존 섹션 교체: 섹션 헤더 다음 줄부터 다음 --- 전까지 교체
    NEW_BODY=$(echo "$NEW_BODY" | awk \
        -v commits="$COMMIT_LIST" \
        'BEGIN{skip=0}
         /^## 📝 커밋 목록/{print; print ""; print commits; print ""; skip=1; next}
         skip && /^---/{skip=0}
         !skip{print}')
else
    # 섹션 없음: 변경 요약(🎯) 다음 --- 뒤에 삽입
    NEW_BODY=$(echo "$NEW_BODY" | awk \
        -v commits="$COMMIT_LIST" \
        'BEGIN{found=0; inserted=0}
         /^## 🎯 변경 요약/{found=1}
         found && !inserted && /^---/{
             print; print "";
             print "## 📝 커밋 목록 (자동 생성)"; print "";
             print commits; print "";
             inserted=1; next
         }
         {print}')
fi

# ── PR 제목 + 본문 업데이트 ──────────────────────────────────
BODY_FILE=$(mktemp)
echo "$NEW_BODY" > "$BODY_FILE"

gh pr edit "$PR_NUMBER" \
    --title "$PR_TITLE" \
    --body-file "$BODY_FILE"

rm -f "$BODY_FILE"

echo "✅ PR #${PR_NUMBER} 업데이트 완료"
