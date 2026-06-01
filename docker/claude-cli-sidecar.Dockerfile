# ============================================================
# Claude CLI Sidecar - 자동 오류 처리용 (Day16에서 본격 사용)
# - 코드 read-only 마운트
# - --cap-drop ALL, no-new-privileges
# - --allowed-tools=Read,Grep,Glob 만 허용 (R-602)
# ============================================================

FROM node:20-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Claude Code CLI 설치
RUN npm install -g @anthropic-ai/claude-code

# 비루트 사용자
RUN useradd -m -u 1001 claude
USER claude
WORKDIR /workspace

# 사이드카는 long-lived idle 컨테이너로 동작한다.
# 오류 처리기(harness)가 `docker exec ada-claude-sidecar claude -p "..." --allowed-tools ...`
# 로 호출하므로, 부팅 시 claude 를 foreground 로 실행하면 안 된다.
# (TTY 없는 컨테이너에서 `claude` 는 --print 모드로 전환 → 입력 없음 → 즉시 종료 → restart 루프)
ENTRYPOINT []
CMD ["sleep", "infinity"]
