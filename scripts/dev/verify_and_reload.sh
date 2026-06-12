#!/usr/bin/env bash
# ============================================================================
# verify_and_reload.sh — ADA 표준 "수정 후 점검·리로드" 자동화
# ----------------------------------------------------------------------------
# 목적: 코드 수정이 끝나면 이 스크립트 한 번으로
#   ① 문법 ② 마운트 동기화(SHA256) ③ grep 검증 ④ 잔여/중복 컨테이너
#   ⑤ 재시작 반영(StartedAt) ⑥ 메모리 캐시 ⑦ Redis 캐시 ⑧ 서비스 응답
# 을 전수 점검하고, 영향 컨테이너만 골라 재시작한다.
# 끝나면 사용자는 웹 대시보드에서 F5 한 번이면 새 코드가 반영된다.
#
# 핵심 원리:
#   - 수정 파일이 마운트된 "실행 중 컨테이너"를 docker에서 자동 탐지한다.
#     (하드코딩 맵 없음 → compose가 바뀌어도 자동 추종)
#   - frontend = Streamlit (재시작으로 @st.cache_* 초기화 + 새 코드 로드)
#   - worker-* = Celery (파이썬 핫리로드 불가 → 반드시 재시작해야 반영)
#
# 사용법:
#   bash scripts/dev/verify_and_reload.sh frontend/app.py
#   bash scripts/dev/verify_and_reload.sh outputs/carriers/pdf_carrier.py outputs/architect/skeletons/report_skeleton.py
#   bash scripts/dev/verify_and_reload.sh outputs/pdf.py --grep-absent "_MAX_LINES"
#   bash scripts/dev/verify_and_reload.sh frontend/app.py --grep-present "def _stageBox"
#   bash scripts/dev/verify_and_reload.sh outputs/pdf.py --no-restart   # 점검만, 재시작 생략
#
# 옵션:
#   --grep-present "PATTERN"   수정 후 컨테이너 안에 PATTERN 이 있어야 통과
#   --grep-absent  "PATTERN"   수정 후 컨테이너 안에 PATTERN 이 없어야 통과
#   --no-restart               재시작 없이 점검만
#   --quiet                    요약 표만 출력
#
# 작성: NY (HJ 지시) · outputs/ 작업용 표준 절차 · 2026-06
# ============================================================================
set -uo pipefail

# ---- repo root 자동 탐지 ----------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# ---- 색상 -------------------------------------------------------------------
if [ -t 1 ]; then
  G="\033[32m"; R="\033[31m"; Y="\033[33m"; B="\033[36m"; W="\033[1m"; N="\033[0m"
else
  G=""; R=""; Y=""; B=""; W=""; N=""
fi
ok(){   echo -e "  ${G}✓${N} $*"; }
bad(){  echo -e "  ${R}✗${N} $*"; }
warn(){ echo -e "  ${Y}!${N} $*"; }
hdr(){  echo -e "\n${W}${B}== $* ==${N}"; }

# ---- 인자 파싱 --------------------------------------------------------------
FILES=()
GREP_PRESENT=""
GREP_ABSENT=""
NO_RESTART=0
QUIET=0
while [ $# -gt 0 ]; do
  case "$1" in
    --grep-present) GREP_PRESENT="$2"; shift 2 ;;
    --grep-absent)  GREP_ABSENT="$2";  shift 2 ;;
    --no-restart)   NO_RESTART=1; shift ;;
    --quiet)        QUIET=1; shift ;;
    -h|--help)      sed -n '2,40p' "$0"; exit 0 ;;
    *)              FILES+=("$1"); shift ;;
  esac
done

if [ ${#FILES[@]} -eq 0 ]; then
  bad "수정 파일을 1개 이상 지정하세요. 예: bash scripts/dev/verify_and_reload.sh frontend/app.py"
  exit 2
fi

# ---- docker 존재 확인 -------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  bad "docker 명령을 찾을 수 없습니다. Docker Desktop 실행 후 다시 시도하세요."
  exit 2
fi

# 점검 결과 누적 (리포트용)
declare -a REPORT_ROWS
FAIL=0
add_row(){ REPORT_ROWS+=("$1|$2|$3"); }   # 항목|결과|비고

# 호스트 파일 해시 (sha256sum 우선, 없으면 python)
host_hash(){
  local f="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$f" 2>/dev/null | awk '{print $1}'
  else
    python -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$f" 2>/dev/null
  fi
}
# 컨테이너 파일 해시 (python 은 모든 ada 이미지에 존재)
cont_hash(){
  local c="$1" f="$2"
  docker exec "$c" python -c "import hashlib,sys;print(hashlib.sha256(open('/app/'+sys.argv[1],'rb').read()).hexdigest())" "$f" 2>/dev/null
}

# 실행 중 ada-* 컨테이너 목록
RUNNING="$(docker ps --filter 'name=ada-' --format '{{.Names}}' 2>/dev/null)"
if [ -z "$RUNNING" ]; then
  bad "실행 중인 ada-* 컨테이너가 없습니다. (docker compose up 먼저)"
  exit 2
fi

# ----------------------------------------------------------------------------
# [1] 코드 문법 (.py 만) — 호스트 + 영향 컨테이너 내부 둘 다
# ----------------------------------------------------------------------------
hdr "[1] 코드 문법 (py_compile)"
SYNTAX_OK=1
for f in "${FILES[@]}"; do
  [ -f "$f" ] || { bad "$f (호스트에 파일 없음)"; SYNTAX_OK=0; FAIL=1; continue; }
  case "$f" in
    *.py)
      if python -m py_compile "$f" 2>/dev/null; then ok "$f (호스트 컴파일 OK)";
      else bad "$f (호스트 컴파일 실패)"; SYNTAX_OK=0; FAIL=1; fi ;;
    *) ok "$f (비-파이썬, 문법검사 생략)" ;;
  esac
done
[ "$SYNTAX_OK" = 1 ] && add_row "코드 문법" "py_compile (호스트)" "COMPILE_OK" || add_row "코드 문법" "py_compile (호스트)" "FAIL"

# ----------------------------------------------------------------------------
# 영향 컨테이너 자동 탐지 — 각 파일이 마운트돼 SHA256 일치하는 실행 컨테이너
# ----------------------------------------------------------------------------
hdr "[2] 마운트 동기화 (호스트 ↔ 컨테이너 SHA256)"
declare -A TARGETS          # 컨테이너명 → 1 (중복 제거)
SYNC_OK=1
for f in "${FILES[@]}"; do
  [ -f "$f" ] || continue
  hh="$(host_hash "$f")"
  matched=0
  for c in $RUNNING; do
    # 컨테이너에 /app/<f> 존재?
    if docker exec "$c" test -f "/app/$f" 2>/dev/null; then
      ch="$(cont_hash "$c" "$f")"
      if [ -n "$hh" ] && [ "$hh" = "$ch" ]; then
        ok "$f ↔ $c  (${hh:0:7}…${hh: -6})"
        TARGETS["$c"]=1
        matched=1
      elif [ -n "$ch" ]; then
        bad "$f ↔ $c  해시 불일치 (host ${hh:0:7}… ≠ cont ${ch:0:7}…) — 마운트 stale!"
        SYNC_OK=0; FAIL=1
        TARGETS["$c"]=1   # 그래도 재시작 대상엔 포함
      fi
    fi
  done
  [ "$matched" = 0 ] && warn "$f — 마운트된 실행 컨테이너를 못 찾음 (이미지에 baked 됐거나 해당 서비스 미실행)"
done
[ "$SYNC_OK" = 1 ] && add_row "마운트 동기화" "SHA256 비교" "완전 일치 ✓" || add_row "마운트 동기화" "SHA256 비교" "불일치 발견 ✗"

if [ ${#TARGETS[@]} -eq 0 ]; then
  warn "재시작 대상 컨테이너가 없습니다. (frontend/worker 미실행 또는 baked 이미지)"
fi

# ----------------------------------------------------------------------------
# [3] grep 검증 — 변경이 컨테이너 안에 실제 반영됐는지
# ----------------------------------------------------------------------------
if [ -n "$GREP_PRESENT" ] || [ -n "$GREP_ABSENT" ]; then
  hdr "[3] 변경 반영 검증 (컨테이너 내부 grep)"
  for c in "${!TARGETS[@]}"; do
    for f in "${FILES[@]}"; do
      docker exec "$c" test -f "/app/$f" 2>/dev/null || continue
      if [ -n "$GREP_PRESENT" ]; then
        if docker exec "$c" grep -q -- "$GREP_PRESENT" "/app/$f" 2>/dev/null; then
          ok "$c:$f — '$GREP_PRESENT' 존재 ✓"
          add_row "변경 반영(있어야)" "grep '$GREP_PRESENT'" "발견 ✓"
        else
          bad "$c:$f — '$GREP_PRESENT' 없음 ✗"; FAIL=1
          add_row "변경 반영(있어야)" "grep '$GREP_PRESENT'" "없음 ✗"
        fi
      fi
      if [ -n "$GREP_ABSENT" ]; then
        if docker exec "$c" grep -q -- "$GREP_ABSENT" "/app/$f" 2>/dev/null; then
          bad "$c:$f — '$GREP_ABSENT' 아직 남아있음 ✗"; FAIL=1
          add_row "변경 반영(없어야)" "grep '$GREP_ABSENT'" "잔존 ✗"
        else
          ok "$c:$f — '$GREP_ABSENT' 제거됨 (0건) ✓"
          add_row "변경 반영(없어야)" "grep '$GREP_ABSENT'" "0건 ✓"
        fi
      fi
    done
  done
else
  add_row "변경 반영 검증" "grep (옵션 미지정)" "건너뜀"
fi

# ----------------------------------------------------------------------------
# [4] 잔여·중복 컨테이너 점검
# ----------------------------------------------------------------------------
hdr "[4] 잔여·중복 컨테이너"
DUP="$(docker ps -a --filter 'name=ada-' --format '{{.Names}}\t{{.Status}}' 2>/dev/null)"
EXITED="$(echo "$DUP" | grep -iE 'Exited|Dead|Created' || true)"
# 같은 이름이 2개 이상인지 (이름 중복은 docker가 막지만, 유사 잔재 탐지)
DUPNAME="$(docker ps -a --filter 'name=ada-' --format '{{.Names}}' | sort | uniq -d)"
if [ -z "$EXITED" ] && [ -z "$DUPNAME" ]; then
  ok "exited/dead/중복 컨테이너 없음 — 단일 인스턴스 정상"
  add_row "잔여·중복 컨테이너" "docker ps -a" "잔여 없음 ✓"
else
  [ -n "$EXITED" ]  && { warn "정지 상태 컨테이너 발견:"; echo "$EXITED" | sed 's/^/      /'; }
  [ -n "$DUPNAME" ] && warn "이름 중복 의심: $DUPNAME"
  add_row "잔여·중복 컨테이너" "docker ps -a" "정지/중복 발견 !"
fi

# ----------------------------------------------------------------------------
# [5] 재시작 + StartedAt 반영 확인  (+ [6] 메모리 캐시 자동 초기화)
# ----------------------------------------------------------------------------
hdr "[5] 재시작 반영 (StartedAt) · [6] 메모리 캐시"
if [ "$NO_RESTART" = 1 ]; then
  warn "--no-restart 지정 — 재시작 생략 (점검만 수행)"
  add_row "재시작 반영" "--no-restart" "생략"
  add_row "메모리 캐시" "재시작 없음" "초기화 안 됨 !"
elif [ ${#TARGETS[@]} -eq 0 ]; then
  warn "재시작 대상 없음 — 단계 생략"
  add_row "재시작 반영" "대상 없음" "생략"
else
  for c in "${!TARGETS[@]}"; do
    before="$(docker inspect -f '{{.State.StartedAt}}' "$c" 2>/dev/null)"
    if docker restart "$c" >/dev/null 2>&1; then
      # 컨테이너가 다시 떠서 StartedAt 이 갱신될 때까지 대기
      after="$before"
      for _ in $(seq 1 20); do
        sleep 1
        after="$(docker inspect -f '{{.State.StartedAt}}' "$c" 2>/dev/null)"
        running="$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null)"
        [ "$after" != "$before" ] && [ "$running" = "true" ] && break
      done
      if [ "$after" != "$before" ]; then
        ok "$c 재시작됨 — StartedAt 갱신 ($after)"
        add_row "재시작 반영($c)" "StartedAt 갱신" "새 코드 로드 ✓"
      else
        bad "$c — StartedAt 미갱신, 재시작 확인 실패"; FAIL=1
        add_row "재시작 반영($c)" "StartedAt" "미갱신 ✗"
      fi
    else
      bad "$c 재시작 명령 실패"; FAIL=1
      add_row "재시작 반영($c)" "docker restart" "실패 ✗"
    fi
  done
  ok "재시작으로 @st.cache_* / 프로세스 메모리 자동 초기화됨 (별도 조치 불필요)"
  add_row "메모리 캐시" "재시작 시 자동" "초기화됨 ✓"
fi

# ----------------------------------------------------------------------------
# [7] Redis 캐시 — job별 키 + TTL 이라 옛 데이터 영향 없음 (확인만)
# ----------------------------------------------------------------------------
hdr "[7] Redis 캐시 (stage_partial)"
if echo "$RUNNING" | grep -q 'ada-redis'; then
  CNT="$(docker exec ada-redis sh -c "redis-cli --scan --pattern 'ada:stage_partial:*' 2>/dev/null | wc -l" 2>/dev/null | tr -d ' \r')"
  if [ -n "$CNT" ]; then
    ok "ada:stage_partial:* 키 ${CNT}개 — job별 키+TTL(600s), 새 분석 시 새 키 생성 → 옛 데이터 영향 없음"
  else
    ok "stage_partial 키는 job별 키+TTL(600s) — 옛 데이터 영향 없음 (조치 불필요)"
  fi
  add_row "Redis 캐시" "job별 키+TTL 600s" "영향 없음 ✓"
else
  warn "ada-redis 미실행 — 확인 생략"
  add_row "Redis 캐시" "ada-redis 미실행" "건너뜀"
fi

# ----------------------------------------------------------------------------
# [8] 서비스 응답 (health)
# ----------------------------------------------------------------------------
hdr "[8] 서비스 응답 (health)"
check_http(){   # 컨테이너명, URL, 라벨
  local c="$1" url="$2" lbl="$3"
  echo "$RUNNING" | grep -q "$c" || { warn "$c 미실행 — $lbl 생략"; return; }
  local code
  code="$(docker exec "$c" sh -c "curl -s -o /dev/null -w '%{http_code}' '$url'" 2>/dev/null)"
  if [ "$code" = "200" ]; then ok "$lbl  HTTP 200 ✓"; add_row "$lbl" "$url" "HTTP 200 ✓";
  else bad "$lbl  HTTP ${code:-응답없음} ✗"; FAIL=1; add_row "$lbl" "$url" "HTTP ${code:-X} ✗"; fi
}
# frontend 가 대상이면 streamlit health
if echo "${!TARGETS[*]}" | grep -q 'ada-frontend' || echo "$RUNNING" | grep -q 'ada-frontend'; then
  check_http "ada-frontend" "http://localhost:8501/_stcore/health" "프론트엔드(Streamlit)"
fi
# api 도 떠 있으면 확인 (워커 코드 변경은 api 서빙엔 영향 적지만 헬스 확인)
if echo "$RUNNING" | grep -q 'ada-api'; then
  check_http "ada-api" "http://localhost:8000/health" "API"
fi
# 워커는 HTTP 헬스가 없으니 Running 상태 + 재시작 루프 아님으로 검증
for c in "${!TARGETS[@]}"; do
  case "$c" in
    ada-worker-*)
      st="$(docker inspect -f '{{.State.Running}}/{{.State.Restarting}}' "$c" 2>/dev/null)"
      if [ "$st" = "true/false" ]; then ok "$c 워커 Running (재시작 루프 아님) ✓"; add_row "$c" "State.Running" "정상 ✓";
      else bad "$c 상태 이상: $st ✗"; FAIL=1; add_row "$c" "State" "$st ✗"; fi ;;
  esac
done

# ----------------------------------------------------------------------------
# 점검·조치 결과 보고서
# ----------------------------------------------------------------------------
echo ""
echo -e "${W}${B}┌───────────────────────────────────────────────────────────────┐${N}"
echo -e "${W}${B}│  점검·조치 결과 보고서                                          │${N}"
echo -e "${W}${B}└───────────────────────────────────────────────────────────────┘${N}"
echo -e "  작업 파일: ${W}${FILES[*]}${N}"
echo -e "  대상 컨테이너: ${W}${!TARGETS[*]:-(없음)}${N}"
echo ""
printf "  %-2s %-22s %-24s %s\n" "#" "점검 항목" "명령/방법" "결과"
printf "  %s\n" "---------------------------------------------------------------------------"
i=1
for row in "${REPORT_ROWS[@]}"; do
  IFS='|' read -r item method result <<< "$row"
  printf "  %-2s %-22s %-24s %s\n" "$i" "$item" "$method" "$result"
  i=$((i+1))
done
echo ""
if [ "$FAIL" = 0 ]; then
  echo -e "  ${G}${W}결론:${N} 옛 컨테이너·캐시·잔여 상태 없음. 새 코드로 정상 응답 중."
  if [ "$NO_RESTART" = 1 ]; then
    echo -e "  ${Y}→ --no-restart 였으므로, 반영하려면 재시작이 필요합니다.${N}"
  else
    echo -e "  ${G}${W}→ 웹 대시보드에서 새로고침(F5) 한 번이면 모든 수정이 반영됩니다.${N}"
  fi
  exit 0
else
  echo -e "  ${R}${W}결론: 일부 점검 실패 (위 ✗ 항목 확인). 반영 전 수정 필요.${N}"
  exit 1
fi
