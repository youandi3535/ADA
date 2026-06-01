#!/usr/bin/env sh
# scripts/dev/setup_hooks_unix.sh — Linux/Mac 팀원용 1회 설정
# 실행: sh scripts/dev/setup_hooks_unix.sh

set -e

SETTINGS=".claude/settings.json"

if [ ! -f "$SETTINGS" ]; then
  echo "ERROR: $SETTINGS not found. 프로젝트 루트에서 실행하세요."
  exit 1
fi

# python → python3 으로 교체 (run_hook.py 호출 부분만)
if command -v python3 >/dev/null 2>&1; then
  PY="python3"
elif command -v python >/dev/null 2>&1; then
  PY="python"
else
  echo "ERROR: python3 / python 을 찾을 수 없습니다."
  exit 1
fi

# sed: macOS(BSD) 와 Linux(GNU) 모두 호환
sed -i.bak "s|python -X utf8 scripts/run_hook.py|$PY -X utf8 scripts/run_hook.py|g" "$SETTINGS"

echo "✅ $SETTINGS 의 hook 커맨드를 '$PY' 로 업데이트했습니다."
echo "   백업: ${SETTINGS}.bak"
echo "   Claude Code 를 재시작하면 적용됩니다."
