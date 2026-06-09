#!/usr/bin/env bash
# =============================================================
# daily_check.sh  —  ADA VPS 일일 헬스체크
# 실행: /opt/ada/scripts/daily_check.sh
# cron: 0 7 * * * /opt/ada/scripts/daily_check.sh > /var/log/ada/daily.log 2>&1
# =============================================================
set -euo pipefail

PASS="✅" WARN="⚠️ " FAIL="🔴"
ISSUES=0

log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
ok()   { log "$PASS $*"; }
warn() { log "$WARN $*"; ISSUES=$((ISSUES+1)); }
fail() { log "$FAIL $*"; ISSUES=$((ISSUES+1)); }

log "========== ADA 일일 헬스체크 시작 =========="

# ── 1. 컨테이너 상태 ──────────────────────────────────────────
log "--- 1. 컨테이너 상태"
UNHEALTHY=$(docker ps --filter "health=unhealthy" --format "{{.Names}}" | tr '\n' ' ')
NOT_RUNNING=$(docker ps -a --filter "status=exited" --filter "status=dead" \
              --format "{{.Names}}" | tr '\n' ' ')
[[ -z "$UNHEALTHY" ]] && ok "모든 컨테이너 healthy" || fail "unhealthy: $UNHEALTHY"
[[ -z "$NOT_RUNNING" ]] && ok "종료된 컨테이너 없음" || warn "종료됨: $NOT_RUNNING"

# ── 2. DB 연결 수 ─────────────────────────────────────────────
log "--- 2. DB 연결 수"
DB_CONN=$(docker exec ada-postgres psql -U autoai -tAc \
          "SELECT count(*) FROM pg_stat_activity;" 2>/dev/null || echo "ERR")
if [[ "$DB_CONN" == "ERR" ]]; then
  fail "DB 연결 실패"
elif [[ "$DB_CONN" -gt 80 ]]; then
  warn "DB 연결 수 높음: $DB_CONN / 100"
else
  ok "DB 연결 수: $DB_CONN / 100"
fi

# ── 3. 롱쿼리 ────────────────────────────────────────────────
log "--- 3. 롱쿼리 (>10초)"
LONG_Q=$(docker exec ada-postgres psql -U autoai -tAc \
  "SELECT count(*) FROM pg_stat_activity
   WHERE state='active' AND now()-query_start > interval '10 seconds';" 2>/dev/null || echo "ERR")
if [[ "$LONG_Q" == "ERR" ]]; then
  warn "롱쿼리 확인 실패"
elif [[ "$LONG_Q" -gt 0 ]]; then
  warn "롱쿼리 $LONG_Q 건 감지"
else
  ok "롱쿼리 없음"
fi

# ── 4. 마이그레이션 ──────────────────────────────────────────
log "--- 4. Alembic 마이그레이션"
CURRENT=$(docker exec ada-api alembic current 2>/dev/null | grep -v INFO | tr -d ' \n' || echo "ERR")
HEAD=$(docker exec ada-api alembic heads 2>/dev/null | grep -v INFO | tr -d ' \n' || echo "ERR")
if [[ "$CURRENT" == "$HEAD" && "$CURRENT" != "ERR" ]]; then
  ok "마이그레이션 최신: $CURRENT"
else
  fail "마이그레이션 불일치 — current: $CURRENT / head: $HEAD"
fi

# ── 5. 디스크 ────────────────────────────────────────────────
log "--- 5. 디스크"
DISK_PCT=$(df / | awk 'NR==2{print $5}' | tr -d '%')
INODE_PCT=$(df -i / | awk 'NR==2{print $5}' | tr -d '%')
[[ "$DISK_PCT" -lt 80 ]] && ok "디스크 ${DISK_PCT}%" || fail "디스크 ${DISK_PCT}% — 정리 필요"
[[ "$INODE_PCT" -lt 80 ]] && ok "inode ${INODE_PCT}%" || fail "inode ${INODE_PCT}% — 정리 필요"

# ── 6. 메모리 ────────────────────────────────────────────────
log "--- 6. 메모리"
AVAIL_PCT=$(free | awk '/^Mem/{printf "%d", $7/$2*100}')
[[ "$AVAIL_PCT" -ge 20 ]] && ok "메모리 여유 ${AVAIL_PCT}%" || warn "메모리 여유 ${AVAIL_PCT}% — 위험"

# ── 7. 컨테이너별 메모리 한계 근접 체크 ──────────────────────
log "--- 7. 컨테이너 메모리 한계 근접 (>85%)"
docker stats --no-stream --format "{{.Name}} {{.MemPerc}}" | while read -r name pct; do
  pct_num=${pct//%/}
  pct_int=${pct_num%%.*}
  if [[ "$pct_int" -ge 85 ]]; then
    warn "$name 메모리 ${pct} 한계 근접"
  fi
done
ok "컨테이너 메모리 체크 완료"

# ── 8. 외부 노출 포트 ─────────────────────────────────────────
log "--- 8. 외부 노출 포트"
UNEXPECTED=$(ss -tlnp | grep -v 127.0.0.1 | grep LISTEN | \
             grep -v ':80 \|:443 \|:22 \|:53 \|11434' || true)
[[ -z "$UNEXPECTED" ]] && ok "노출 포트 정상 (22/80/443)" || warn "예상 외 포트 노출:\n$UNEXPECTED"

# ── 9. TLS 인증서 만료 ───────────────────────────────────────
log "--- 9. TLS 인증서 만료일"
CERT_EXPIRY=$(echo | openssl s_client -connect ada-aiagent.com:443 \
              -servername ada-aiagent.com 2>/dev/null \
              | openssl x509 -noout -enddate 2>/dev/null \
              | cut -d= -f2 || echo "ERR")
if [[ "$CERT_EXPIRY" == "ERR" ]]; then
  warn "TLS 인증서 확인 실패"
else
  EXPIRY_EPOCH=$(date -d "$CERT_EXPIRY" +%s 2>/dev/null || echo 0)
  NOW_EPOCH=$(date +%s)
  DAYS_LEFT=$(( (EXPIRY_EPOCH - NOW_EPOCH) / 86400 ))
  [[ "$DAYS_LEFT" -ge 30 ]] && ok "TLS 인증서 ${DAYS_LEFT}일 남음" || warn "TLS 인증서 ${DAYS_LEFT}일 남음 — 갱신 필요"
fi

# ── 10. 시계 동기화 ──────────────────────────────────────────
log "--- 10. 시계 동기화"
NTP_OK=$(timedatectl | grep "synchronized: yes" || true)
[[ -n "$NTP_OK" ]] && ok "NTP 동기화 정상" || warn "NTP 동기화 실패"

# ── 11. 보안 업데이트 ────────────────────────────────────────
log "--- 11. OS 보안 업데이트"
SEC_CNT=$(apt list --upgradable 2>/dev/null | grep -ci security || true)
[[ "$SEC_CNT" -eq 0 ]] && ok "보안 업데이트 없음" || warn "보안 업데이트 ${SEC_CNT}개 미적용"

# ── 12. fail2ban ─────────────────────────────────────────────
log "--- 12. fail2ban"
F2B=$(sudo fail2ban-client status sshd 2>/dev/null | grep "Currently failed" | awk '{print $NF}' || echo "ERR")
[[ "$F2B" == "ERR" ]] && warn "fail2ban 확인 실패" || ok "fail2ban 정상 (현재 실패 시도: $F2B)"

# ── 결과 요약 ────────────────────────────────────────────────
log "=========================================="
if [[ "$ISSUES" -eq 0 ]]; then
  log "$PASS 모든 체크 통과 — 이상 없음"
else
  log "$FAIL 이슈 ${ISSUES}건 발견 — 위 로그 확인"
fi
log "========== 헬스체크 종료 =========="
exit $([[ "$ISSUES" -eq 0 ]] && echo 0 || echo 1)
