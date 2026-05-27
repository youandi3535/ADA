#!/usr/bin/env bash
# =============================================================
# .github/scripts/fill_pr.sh
# PR 제목·본문 자동 채움 스크립트
# GitHub Action (auto-pr.yml) 에서 호출됨
#
# 필요 환경변수:
#   GH_TOKEN   - GitHub API 토큰 (PR 수정 + GitHub Models AI 호출 겸용)
#   PR_NUMBER  - PR 번호
#   BASE_SHA   - base 브랜치 SHA
#   HEAD_SHA   - head 브랜치 SHA
#   BRANCH     - head 브랜치명 (예: feat/hj-day2)
#
# GitHub Models API (models.inference.ai.azure.com):
#   - GITHUB_TOKEN 으로 인증 → 별도 API 키 불필요
#   - gpt-4o-mini 모델로 PR 제목 요약 생성
# =============================================================
set -e

# ── 브랜치 prefix 추출 (feat/hj-day2 → hj-day2) ─────────────
BRANCH_PREFIX=$(echo "$BRANCH" | sed 's|feat/||')

# ── Day 추출 (feat/hj-day2 → 2) ──────────────────────────────
DAY_NUM=$(echo "$BRANCH" | grep -oE 'day[0-9]+' | grep -oE '[0-9]+' || echo "?")

# ── 커밋 목록 (base..head) ────────────────────────────────────
COMMIT_LIST=$(git log "${BASE_SHA}..${HEAD_SHA}" --format="- %s" --reverse)
if [ -z "$COMMIT_LIST" ]; then
    COMMIT_LIST="- (커밋 없음)"
fi

echo "▶ 커밋 목록:"
echo "$COMMIT_LIST" | sed 's/^/    /'

# ── GitHub Models AI로 대표 제목 생성 ───────────────────────
echo "▶ GitHub Models AI로 PR 제목 생성 중..."

# Python으로 API 호출 (JSON 이스케이프 문제 방지)
PR_TITLE_BODY=$(python3 - <<PYEOF
import json, urllib.request, urllib.error, os, sys

commits = """${COMMIT_LIST}"""
branch_prefix = "${BRANCH_PREFIX}"

prompt = f"""아래는 하나의 Pull Request에 포함된 커밋 메시지 목록이야.
이 커밋들을 종합해서 PR 전체를 대표하는 제목을 한 줄로 만들어줘.

조건:
- 한글로 작성
- 30자 이내
- 앞에 브랜치명이나 prefix 붙이지 말 것 (별도로 붙여줄 거야)
- 구체적으로 무엇을 했는지 알 수 있게
- 예시: "end_of_day.sh Windows 호환성 및 자동화 개선"

커밋 목록:
{commits}

제목만 출력 (다른 설명 없이):"""

payload = {
    "model": "gpt-4o-mini",
    "max_tokens": 100,
    "messages": [{"role": "user", "content": prompt}]
}

req = urllib.request.Request(
    "https://models.inference.ai.azure.com/chat/completions",
    data=json.dumps(payload).encode(),
    headers={
        "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
        "content-type": "application/json",
    }
)

try:
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
        title = result["choices"][0]["message"]["content"].strip().strip('"').strip("'")
        print(title)
except urllib.error.HTTPError as e:
    print(f"API_ERROR: {e.read().decode()}", file=sys.stderr)
    sys.exit(1)
PYEOF
)

# ── 최종 PR 제목 조합: "브랜치prefix: AI생성제목" ────────────
PR_TITLE="${BRANCH_PREFIX}: ${PR_TITLE_BODY}"
echo "▶ PR 제목: ${PR_TITLE}"

# ── 현재 PR 본문 가져오기 ────────────────────────────────────
CURRENT_BODY=$(gh pr view "$PR_NUMBER" --json body --jq '.body')

# ── Day 정보 자동 채움 (Day __ → Day N) ─────────────────────
NEW_BODY=$(echo "$CURRENT_BODY" | sed "s/\*\*Day\*\*: Day __/**Day**: Day ${DAY_NUM}/")

# ── 커밋 목록 섹션 삽입/갱신 ────────────────────────────────
if echo "$NEW_BODY" | grep -qF "## 📝 커밋 목록"; then
    # 기존 섹션 교체
    NEW_BODY=$(echo "$NEW_BODY" | awk \
        -v commits="$COMMIT_LIST" \
        'BEGIN{skip=0}
         /^## 📝 커밋 목록/{print; print ""; print commits; print ""; skip=1; next}
         skip && /^---/{skip=0}
         !skip{print}')
else
    # 섹션 없음 → 변경 요약 다음 --- 뒤에 삽입
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
echo "✅ PR #${PR_NUMBER} 업데이트 완료: ${PR_TITLE}"
