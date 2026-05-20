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

ENTRYPOINT ["claude"]
