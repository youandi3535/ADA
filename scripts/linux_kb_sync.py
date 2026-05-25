#!/usr/bin/env python3
"""scripts/linux_kb_sync.py — 리눅스 서버 Q&A 동기화 + 임베딩 스크립트

[동작 흐름]
1. GET /kb/conversation/unprocessed  — 웹서버에서 미처리 Q&A 가져오기
2. 각 Q&A 에 대해:
   a. question 텍스트 임베딩 (paraphrase-multilingual-mpnet-base-v2, 768 dim)
   b. 중복 체크 (SHA256 해시)
   c. self_learning_kb 에 upsert
   d. PATCH /kb/conversation/{id}/done 으로 처리 완료 표시
3. 처리 결과 요약 출력

[실행 방법]
  python3 scripts/linux_kb_sync.py           # 기본 실행
  python3 scripts/linux_kb_sync.py --dry-run  # 저장 없이 내용 출력만
  python3 scripts/linux_kb_sync.py --limit 50 # 최대 50개만 처리

[cron 설정 예시 - 하루 3회]
  0 8,14,21 * * * cd /path/to/ADA && python3 scripts/linux_kb_sync.py >> /var/log/ada_kb_sync.log 2>&1

[환경변수 / .env]
  KB_SERVER_URL       웹서버 주소  (기본: http://localhost:8000)
  KB_COLLECT_SECRET   X-KB-Secret 헤더
  DATABASE_URL        리눅스 서버 PostgreSQL (pgvector 포함)
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("kb_sync")

# ---------------------------------------------------------------------------
# 설정 로드
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent


def _load_env() -> dict[str, str]:
    """프로젝트 루트 .env 파일 파싱."""
    env_file = _PROJECT_ROOT / ".env"
    result: dict[str, str] = {}
    if not env_file.exists():
        return result
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            result[key] = val
    return result


def _cfg(key: str, default: str = "") -> str:
    _env = _load_env()
    return os.environ.get(key, "").strip() or _env.get(key, default)


# ---------------------------------------------------------------------------
# 웹서버 HTTP 유틸
# ---------------------------------------------------------------------------


def _api_get(url: str, secret: str) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={"X-KB-Secret": secret, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _api_patch(url: str, secret: str, data: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-KB-Secret": secret,
        },
        method="PATCH",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


# ---------------------------------------------------------------------------
# 임베딩
# ---------------------------------------------------------------------------

_embedder = None  # 지연 초기화 (한 번만 로드)


def _get_embedder():
    global _embedder  # noqa: PLW0603
    if _embedder is None:
        from sentence_transformers import SentenceTransformer  # type: ignore

        log.info("Loading embedding model paraphrase-multilingual-mpnet-base-v2 …")
        _embedder = SentenceTransformer("sentence-transformers/paraphrase-multilingual-mpnet-base-v2")
        log.info("Embedding model loaded.")
    return _embedder


def _embed(text: str) -> list[float]:
    """텍스트 → 768차원 float 리스트."""
    vec = _get_embedder().encode(text, normalize_embeddings=True)
    return vec.tolist()


# ---------------------------------------------------------------------------
# 해시 & 중복 체크
# ---------------------------------------------------------------------------


def _make_hash(question: str, answer: str) -> str:
    """Q+A 내용의 SHA256 해시 (중복 방지용)."""
    raw = f"{question.strip()}\n{answer.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# DB — async SQLAlchemy
# ---------------------------------------------------------------------------


async def _upsert_kb(
    db_url: str,
    question: str,
    answer: str,
    team_member: str,
    project: str,
    source: str,
    embedding: list[float],
    content_hash: str,
    dry_run: bool,
) -> str | None:
    """self_learning_kb 에 Q&A pair 를 upsert. KB row id 반환."""
    if dry_run:
        return str(uuid.uuid4())  # dry-run: 가짜 id

    # 비동기 DB 드라이버 URL 변환
    if db_url.startswith("postgresql://"):
        async_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    else:
        async_url = db_url

    from sqlalchemy import text as sa_text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    engine = create_async_engine(async_url, echo=False)

    try:
        async with AsyncSession(engine) as session:
            # 이미 있는지 해시로 체크
            existing_id = await session.scalar(
                sa_text("SELECT id FROM self_learning_kb WHERE hash = :h").bindparams(h=content_hash)
            )
            if existing_id:
                log.debug("Duplicate skipped hash=%s", content_hash[:16])
                return str(existing_id)

            row_id = uuid.uuid4()
            payload = {
                "question": question,
                "answer": answer,
                "team_member": team_member,
                "project": project,
                "source": source,
            }

            # pgvector 컬럼 삽입 — CAST() 구문으로 asyncpg 파라미터 충돌 방지
            # (:param::type 형식은 SQLAlchemy text()가 ':' 를 두 번 파싱해 오류 발생)
            payload_json = json.dumps(payload, ensure_ascii=False)
            emb_str = "[" + ",".join(f"{v:.6f}" for v in embedding) + "]"

            await session.execute(
                sa_text(
                    "INSERT INTO self_learning_kb "
                    "(id, kb_type, category, hash, payload, embedding, confidence, success_count) "
                    "VALUES (CAST(:row_id AS uuid), :kb_type, :cat, :hash, "
                    "        CAST(:pld AS jsonb), CAST(:emb AS vector), :conf, 1) "
                    "ON CONFLICT (hash) DO NOTHING"
                ).bindparams(
                    row_id=str(row_id),
                    kb_type="qa_pair",
                    cat=project or "general",
                    hash=content_hash,
                    pld=payload_json,
                    emb=emb_str,
                    conf=0.7,
                )
            )
            await session.commit()
            log.debug("Inserted kb id=%s", str(row_id)[:8])
            return str(row_id)
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# 메인 처리 루프
# ---------------------------------------------------------------------------


async def _run(server_url: str, secret: str, db_url: str, limit: int, dry_run: bool) -> None:
    # 1. 미처리 Q&A 가져오기
    try:
        resp = _api_get(f"{server_url}/kb/conversation/unprocessed?limit={limit}", secret)
    except urllib.error.URLError as e:
        log.error("Cannot reach web server %s: %s", server_url, e)
        sys.exit(1)

    items = resp.get("items", [])
    total = resp.get("total", 0)
    log.info("Fetched %d unprocessed Q&A pairs (limit=%d)", total, limit)

    if not items:
        log.info("Nothing to process. Done.")
        return

    ok, skip, fail = 0, 0, 0

    for item in items:
        item_id = item["id"]
        question = item.get("question", "")
        answer = item.get("answer", "")
        member = item.get("team_member") or "unknown"
        project = item.get("project") or "general"
        source = item.get("source") or "claude_code"

        if len(question) < 5 or len(answer) < 5:
            log.debug("Too short, skip id=%s", item_id[:8])
            skip += 1
            continue

        # 2. 임베딩
        try:
            if dry_run:
                emb = [0.0] * 768
                log.info("[DRY-RUN] Q: %s…", question[:60])
                log.info("[DRY-RUN] A: %s…", answer[:60])
            else:
                emb = _embed(question)
        except Exception as e:  # noqa: BLE001
            log.warning("Embedding failed id=%s: %s", item_id[:8], e)
            fail += 1
            continue

        # 3. 해시 계산 & DB upsert
        content_hash = _make_hash(question, answer)
        try:
            kb_id = await _upsert_kb(
                db_url=db_url,
                question=question,
                answer=answer,
                team_member=member,
                project=project,
                source=source,
                embedding=emb,
                content_hash=content_hash,
                dry_run=dry_run,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("DB upsert failed id=%s: %s", item_id[:8], e)
            fail += 1
            continue

        # 4. 처리 완료 표시 (웹서버)
        try:
            if not dry_run:
                _api_patch(
                    f"{server_url}/kb/conversation/{item_id}/done",
                    secret,
                    {"kb_id": kb_id},
                )
            ok += 1
            log.info("OK [%d/%d] id=%s member=%s", ok, total, item_id[:8], member)
        except urllib.error.URLError as e:
            log.warning("PATCH done failed id=%s: %s", item_id[:8], e)
            fail += 1

    log.info("=== DONE: ok=%d  skip=%d  fail=%d ===", ok, skip, fail)


def main() -> None:
    parser = argparse.ArgumentParser(description="ADA 팀 Q&A 동기화 (리눅스 서버 전용)")
    parser.add_argument("--limit", type=int, default=100, help="최대 처리 건수 (기본 100)")
    parser.add_argument("--dry-run", action="store_true", help="DB 저장 없이 내용 출력만")
    args = parser.parse_args()

    server_url = _cfg("KB_SERVER_URL", "http://localhost:8000").rstrip("/")
    secret = _cfg("KB_COLLECT_SECRET", "")
    db_url = _cfg("DATABASE_URL", "postgresql://autoai:changeme@postgres:5432/autoai")

    log.info("KB Sync start  server=%s  limit=%d  dry_run=%s", server_url, args.limit, args.dry_run)

    asyncio.run(_run(server_url, secret, db_url, args.limit, args.dry_run))


if __name__ == "__main__":
    main()
