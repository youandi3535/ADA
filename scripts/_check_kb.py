#!/usr/bin/env python3
import json
import os
import urllib.request
from pathlib import Path

env = {}
if Path(".env").exists():
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")

url = os.environ.get("KB_SERVER_URL", env.get("KB_SERVER_URL", "http://115.68.216.191/api")).rstrip("/")
secret = os.environ.get("KB_COLLECT_SECRET", env.get("KB_COLLECT_SECRET", ""))

# 최근 저장 내역 조회
req = urllib.request.Request(
    url + "/kb/conversation/unprocessed?limit=10",
    headers={"X-KB-Secret": secret},
)
try:
    with urllib.request.urlopen(req, timeout=8) as r:
        data = json.loads(r.read())
    print(f"[Claude Code] 최근 미처리 대화: {len(data)}건")
    for item in data:
        mid = str(item.get("id", ""))[:8]
        member = str(item.get("team_member", "?"))
        source = str(item.get("source", "?"))
        print(f"  member={member}  source={source}  id={mid}")
except Exception as e:
    print(f"KB 조회 실패: {e}")

# 전체 저장 건수
req2 = urllib.request.Request(
    url + "/kb/conversation/stats",
    headers={"X-KB-Secret": secret},
)
try:
    with urllib.request.urlopen(req2, timeout=8) as r:
        stats = json.loads(r.read())
    print(f"\n[KB 통계] {stats}")
except Exception as e:
    print(f"통계 조회 실패: {e}")

# Cowork 세션 파일 확인
appdata = os.environ.get("APPDATA", "")
cowork = Path(appdata) / "Claude"
print(f"\n[Cowork] Claude 앱 경로: {cowork}")
if cowork.exists():
    sessions = cowork / "local-agent-mode-sessions"
    if sessions.exists():
        files = [f for f in sessions.rglob("*") if f.is_file() and f.suffix in (".txt", ".json", ".md")]
        print(f"  세션 파일: {len(files)}개")
        for f in sorted(files, key=lambda x: x.stat().st_mtime)[-3:]:
            print(f"  {f.name}")
    else:
        subdirs = [d.name for d in cowork.iterdir() if d.is_dir()]
        print(f"  local-agent-mode-sessions 없음. 하위 폴더: {subdirs}")
else:
    print("  Claude 앱 미설치 또는 경로 다름")
