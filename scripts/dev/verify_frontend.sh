#!/usr/bin/env bash
# ============================================================
# scripts/dev/verify_frontend.sh
# ============================================================
# 프런트엔드 수정 후 "전수 점검·배포 확인" 표준 스크립트.
# 목적: 호스트 수정이 컨테이너에 정상 반영됐고, 사용자가 웹 대시보드에서
#       새로고침(F5) 한 번이면 적용되는 상태인지 자동 점검한다.
#
# 실행(호스트에서, docker 접근 가능한 셸 — Git Bash/WSL/PowerShell+bash):
#   bash scripts/dev/verify_frontend.sh                 # 기본 점검
#   bash scripts/dev/verify_frontend.sh "zoom:0.75"     # 특정 변경 문자열이 컨테이너에 들어갔는지까지 확인
#
# 수정 권한: HJ 단독
# ============================================================
set -uo pipefail

CONTAINER="ada-frontend"
HOST_FILE="frontend/app.py"
CONT_FILE="/app/frontend/app.py"
HEALTH_URL="http://localhost:8501/_stcore/health"
PATTERN="${1:-}"

# repo 루트로 이동 (이 스크립트는 scripts/dev/ 에 있음)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../.." || { echo "repo 루트 이동 실패"; exit 1; }

PASS=0; FAIL=0
declare -a NUM DESC RES

add(){ NUM+=("$1"); DESC+=("$2"); RES+=("$3"); }
ok(){  PASS=$((PASS+1)); }
ng(){  FAIL=$((FAIL+1)); }

# ── Python 감지 (.venv → venv → 시스템) ─────────────────────
if   [ -f ".venv/Scripts/python.exe" ]; then PY=".venv/Scripts/python.exe"
elif [ -f ".venv/bin/python" ];        then PY=".venv/bin/python"
elif [ -f "venv/Scripts/python.exe" ]; then PY="venv/Scripts/python.exe"
elif [ -f "venv/bin/python" ];         then PY="venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then PY="python3"
else PY="python"; fi

# 호스트 SHA256 계산 헬퍼 (sha256sum 없으면 python 폴백)
host_sha(){
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" 2>/dev/null | awk '{print $1}'
  else
    "$PY" - "$1" <<'PYEOF'
import hashlib,sys
print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())
PYEOF
  fi
}

# ── [1] 코드 문법 (호스트) ──────────────────────────────────
if "$PY" -m py_compile "$HOST_FILE" 2>/dev/null; then
  add "1" "코드 문법 (호스트 py_compile)" "COMPILE_OK ✓"; ok
else
  add "1" "코드 문법 (호스트 py_compile)" "COMPILE_FAIL ✗"; ng
fi

DOCKER_OK=0
if command -v docker >/dev/null 2>&1 && docker ps >/dev/null 2>&1; then
  DOCKER_OK=1
fi

if [ "$DOCKER_OK" -eq 1 ]; then
  # ── [2] 코드 문법 (컨테이너) ─────────────────────────────
  # HJ 2026-06-14 — 컨테이너 내부 경로($CONT_FILE=/app/...)는 sh -c 따옴표 안에 넣어 전달한다.
  #   Git Bash(MSYS)는 docker exec 의 '맨 인자'로 놓인 /app/... 을 윈도우 경로(C:/Program Files/Git/...)로
  #   자동 변환해 컨테이너 점검(2·3·4)이 거짓 실패하지만, 따옴표 문자열 안의 경로는 변환하지 않아
  #   컨테이너 경로가 그대로 도달한다. (host curl 의 /dev/null 등은 영향받지 않게 docker exec 만 감쌈.)
  if docker exec "$CONTAINER" sh -c "python -m py_compile '$CONT_FILE'" 2>/dev/null; then
    add "2" "코드 문법 (컨테이너 py_compile)" "COMPILE_OK ✓"; ok
  else
    add "2" "코드 문법 (컨테이너 py_compile)" "COMPILE_FAIL ✗"; ng
  fi

  # ── [3] 마운트 동기화 (호스트↔컨테이너 SHA256) ───────────
  HSHA="$(host_sha "$HOST_FILE")"
  CSHA="$(docker exec "$CONTAINER" sh -c "sha256sum '$CONT_FILE'" 2>/dev/null | awk '{print $1}')"
  if [ -n "$HSHA" ] && [ "$HSHA" = "$CSHA" ]; then
    add "3" "마운트 동기화 (SHA256)" "일치 ${HSHA:0:6}…${HSHA: -6} ✓"; ok
  else
    add "3" "마운트 동기화 (SHA256)" "불일치 H=${HSHA:0:6} C=${CSHA:0:6} ✗"; ng
  fi

  # ── [4] 변경 반영 확인 (grep 패턴 — 인자 있을 때만) ──────
  if [ -n "$PATTERN" ]; then
    # grep -c 는 0건일 때 "0" 출력 + exit 1 → 뒤에 `|| echo 0` 을 붙이면 "0\n0" 두 줄이 되어
    # 정수 비교 실패(integer expression expected). 대입 실패 시 CNT=0 으로 단일 값 보장.
    CNT="$(docker exec "$CONTAINER" sh -c "grep -c -- '$PATTERN' '$CONT_FILE'" 2>/dev/null)" || CNT=0
    CNT="${CNT//[^0-9]/}"; CNT="${CNT:-0}"
    if [ "$CNT" -ge 1 ]; then
      add "4" "변경 반영 (컨테이너 grep '$PATTERN')" "${CNT}건 검출 ✓"; ok
    else
      add "4" "변경 반영 (컨테이너 grep '$PATTERN')" "0건 — 미반영 의심 ✗"; ng
    fi
  fi

  # ── [5] 중복·잔여 컨테이너 ───────────────────────────────
  RUNNING="$(docker ps        --filter "name=${CONTAINER}" --format '{{.Names}}' | grep -cx "$CONTAINER" || true)"
  ALL="$(    docker ps -a     --filter "name=${CONTAINER}" --format '{{.Names}}' | grep -cx "$CONTAINER" || true)"
  if [ "$RUNNING" = "1" ] && [ "$ALL" = "1" ]; then
    add "5" "중복·잔여 컨테이너" "ada-frontend 1개 (잔여 없음) ✓"; ok
  else
    add "5" "중복·잔여 컨테이너" "실행 ${RUNNING} / 전체 ${ALL} — 확인 필요 ✗"; ng
  fi

  # ── [6] 서비스 응답 (health) ─────────────────────────────
  CODE="$(curl -s -m 5 -o /dev/null -w '%{http_code}' "$HEALTH_URL" 2>/dev/null || echo 000)"
  if [ "$CODE" = "200" ]; then
    add "6" "서비스 응답 (/_stcore/health)" "HTTP 200 ✓"; ok
  else
    add "6" "서비스 응답 (/_stcore/health)" "HTTP ${CODE} ✗"; ng
  fi
else
  add "-" "컨테이너 점검" "docker 미접근 — 호스트 문법만 점검함 (Git Bash/WSL 등에서 재실행 권장)"
fi

# ── 결과 표 출력 ────────────────────────────────────────────
echo
echo "================ 프런트엔드 점검·조치 결과 ================"
printf "%-3s | %-38s | %s\n" "#" "점검 항목" "결과"
echo "----+----------------------------------------+--------------------------"
for i in "${!NUM[@]}"; do
  printf "%-3s | %-38s | %s\n" "${NUM[$i]}" "${DESC[$i]}" "${RES[$i]}"
done
echo "==========================================================="
echo "통과 ${PASS} · 실패 ${FAIL}"
if [ "$FAIL" -eq 0 ] && [ "$DOCKER_OK" -eq 1 ]; then
  echo "결론: 단일 컨테이너가 새 코드로 정상 응답 중. 웹 대시보드 새로고침(F5) 한 번이면 반영됩니다."
fi
exit "$FAIL"
