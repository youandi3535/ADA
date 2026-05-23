#!/usr/bin/env bash
# ============================================================
# scripts/dev/check_scope.sh
# ============================================================
# 본인 영역 외 파일 수정 시 커밋 차단.
# pre-commit 훅에서 호출되며, 긴급시 --no-verify 로 우회 가능.
#
# 작성자 식별: git config user.email 패턴 매칭
# 매핑 변경 시 .github/CODEOWNERS 와 동기화 필수
#
# 수정 권한: HJ 단독
# ============================================================

set -e

EMAIL=$(git config user.email 2>/dev/null || echo "")
CHANGED=$(git diff --cached --name-only)

# 변경 없으면 통과
if [ -z "$CHANGED" ]; then
    exit 0
fi

# ─── 작성자 → 역할 매핑 ───
# 팀원 추가 시 본인 git email 의 일부 단어를 패턴으로 추가
# 예: 본인 email 이 alice@company.com 이면 *alice* 패턴 추가
case "$EMAIL" in
    *hj*|*HJ*|*youandi*|*admin*)
        ROLE="HJ (시스템·메타·인프라)"
        ALLOWED_REGEX=".*"   # HJ 는 전체 권한
        ;;
    *cs*|*CS*|*member-a*|*memberA*|*timeseries*|*ts-*)
        ROLE="CS (timeseries)"
        ALLOWED_REGEX="^(agents/handlers/timeseries/|pipelines/timeseries/|tests/handlers/timeseries/|requirements/handlers-timeseries\.txt$)"
        ;;
    *ny*|*NY*|*member-b*|*memberB*|*anomaly*|*anom-*|*olivia*)
        ROLE="NY (anomaly)"
        ALLOWED_REGEX="^(agents/handlers/anomaly/|pipelines/anomaly/|tests/handlers/anomaly/|requirements/handlers-anomaly\.txt$)"
        ;;
    *jh*|*JH*|*member-c*|*memberC*|*tabular*|*tab-*|*twinking*)
        ROLE="jh (tabular)"
        ALLOWED_REGEX="^(agents/handlers/tabular/|pipelines/tabular_(ml|dl)/|tests/handlers/tabular/|requirements/handlers-tabular\.txt$)"
        ;;
    *)
        echo "❌ check_scope: 알 수 없는 작성자 — '${EMAIL:-<empty>}'"
        echo ""
        echo "git config user.email 에 다음 패턴 중 하나가 포함돼야 합니다:"
        echo "  - hj / youandi / admin    (HJ — 전체 권한)"
        echo "  - cs / timeseries         (CS — 시계열)"
        echo "  - ny / anomaly            (NY — 이상탐지)"
        echo "  - jh / tabular            (jh — 정형ML/DL)"
        echo ""
        echo "예시 설정 (1회):"
        echo "  git config user.email \"cs@team.com\""
        echo ""
        echo "또는 본 스크립트 (scripts/dev/check_scope.sh) 의 case 문에 본인 패턴 추가."
        exit 1
        ;;
esac

# ─── 영역 외 수정 검출 ───
VIOLATIONS=$(echo "$CHANGED" | grep -vE "$ALLOWED_REGEX" || true)

if [ -n "$VIOLATIONS" ]; then
    echo "❌ 영역 외 파일 수정 감지 — 역할: $ROLE"
    echo ""
    echo "허용 영역 (정규식): $ALLOWED_REGEX"
    echo ""
    echo "위반 파일:"
    echo "$VIOLATIONS" | sed 's/^/  ✗ /'
    echo ""
    echo "─────────────────────────────────────────────────────────"
    echo "공유 파일 수정이 정말 필요하면:"
    echo "  1) HJ 와 사전 협의"
    echo "  2) git commit --no-verify  (훅 우회)"
    echo "  3) PR 본문에 '공유 파일 수정 사유' 명시"
    echo "  4) CODEOWNERS 가 자동으로 HJ 리뷰 요구"
    echo "─────────────────────────────────────────────────────────"
    exit 1
fi

N_FILES=$(echo "$CHANGED" | grep -c . || echo 0)
echo "✅ 영역 검증 통과 — $ROLE ($N_FILES files)"
exit 0
