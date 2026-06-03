#!/usr/bin/env bash
# scripts/dev/register_kb_sync_cron.sh
# ADA KB cross-team puller 를 Linux/Mac crontab 에 등록
#
# 사용법:
#   bash scripts/dev/register_kb_sync_cron.sh           # 등록
#   bash scripts/dev/register_kb_sync_cron.sh --remove  # 제거
#
# 동작:
#   1. 프로젝트 경로 자동 감지
#   2. .venv/bin/python 우선, 없으면 python3
#   3. 하루 3회 (08:00 / 14:00 / 21:00) `linux_kb_sync.py --mode=both` 실행
#   4. 로그: /tmp/ada_kb_sync.log
#   5. 이미 등록돼 있으면 멱등 (덮어쓰기)

set -euo pipefail

# 마커 — 우리 항목만 식별/제거하기 위해 cron 라인 끝에 붙임
MARKER="# ada-kb-sync"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SYNC_SCRIPT="$PROJECT_ROOT/scripts/linux_kb_sync.py"
LOG_FILE="${ADA_KB_SYNC_LOG:-/tmp/ada_kb_sync.log}"

# --- Python 결정 -------------------------------------------------------------
if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
    PY="$PROJECT_ROOT/.venv/bin/python"
    echo "[INFO] venv Python 사용: $PY"
elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
    echo "[WARN] venv 없음 → 시스템 python3 사용: $PY"
else
    echo "[ERROR] python3 가 PATH 에 없습니다" >&2
    exit 1
fi

if [[ ! -f "$SYNC_SCRIPT" ]]; then
    echo "[ERROR] linux_kb_sync.py 없음: $SYNC_SCRIPT" >&2
    exit 1
fi

# --- 기존 항목 제거 (멱등 + --remove 양쪽 사용) ----------------------------------
CURRENT_CRON="$(crontab -l 2>/dev/null || true)"
NEW_CRON="$(echo "$CURRENT_CRON" | grep -v -F "$MARKER" || true)"

if [[ "${1:-}" == "--remove" ]]; then
    if [[ "$CURRENT_CRON" == "$NEW_CRON" ]]; then
        echo "[INFO] 등록된 항목 없음"
    else
        echo "$NEW_CRON" | crontab -
        echo "[OK] ada-kb-sync 항목 제거"
    fi
    exit 0
fi

# --- 등록 --------------------------------------------------------------------
CMD="cd \"$PROJECT_ROOT\" && \"$PY\" \"$SYNC_SCRIPT\" --mode=both >> \"$LOG_FILE\" 2>&1 $MARKER"
ENTRIES="0 8,14,21 * * * $CMD"

# 기존 cron + 새 항목
FINAL_CRON="$(printf '%s\n%s\n' "$NEW_CRON" "$ENTRIES" | sed '/^$/d')"
echo "$FINAL_CRON" | crontab -

echo ""
echo "[OK] crontab 등록 완료"
echo "    Python    : $PY"
echo "    Script    : $SYNC_SCRIPT"
echo "    스케줄    : 매일 08:00 / 14:00 / 21:00"
echo "    Log       : $LOG_FILE"
echo ""
echo "현재 등록 확인:  crontab -l | grep ada-kb-sync"
echo "지금 한번 시험:  $PY $SYNC_SCRIPT --mode=both"
echo "제거하려면:     bash scripts/dev/register_kb_sync_cron.sh --remove"
