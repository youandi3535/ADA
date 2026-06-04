#!/usr/bin/env python3
"""scripts/linux_kb_sync.py — KB 동기화 (qa_pair + Day24 failure_lesson 크로스팀 풀)

[모드 1: --mode=qa]  기존 — Q&A 동기화 (리눅스 서버 내부 unprocessed 처리)
1. GET /kb/conversation/unprocessed  — 웹서버에서 미처리 Q&A 가져오기
2. 각 Q&A 에 대해:
   a. question 텍스트 임베딩 (paraphrase-multilingual-mpnet-base-v2, 768 dim)
   b. 중복 체크 (SHA256 해시)
   c. self_learning_kb 에 upsert
   d. PATCH /kb/conversation/{id}/done 으로 처리 완료 표시

[모드 2: --mode=failure_lessons]  Day24 — 팀원 로컬 풀러
1. GET /kb/conversation/failure_lessons?since=<last_sync_ts>  ← VPS 의 누적 KB
2. 각 row 를 로컬 self_learning_kb 에 ON CONFLICT (hash) DO UPDATE 로 적재
3. 임베딩 재생성 후 lesson_embeddings 도 upsert
4. .ada_failure_lesson_sync_ts 파일로 마지막 sync timestamp 저장
   → 다음 실행 시 since 파라미터로 사용 (증분 동기화)

[모드 3: --mode=both]  두 모드 순차 실행 (cron 추천)

[실행 방법]
  python3 scripts/linux_kb_sync.py                          # 기본 = qa
  python3 scripts/linux_kb_sync.py --mode=failure_lessons   # 크로스팀 풀
  python3 scripts/linux_kb_sync.py --mode=both --limit 200
  python3 scripts/linux_kb_sync.py --dry-run                # 저장 없이 내용만

[cron 설정 예시 - 하루 3회 양쪽 동시]
  0 8,14,21 * * * cd /path/to/ADA && python3 scripts/linux_kb_sync.py --mode=both >> /var/log/ada_kb_sync.log 2>&1

[환경변수 / .env]
  KB_SERVER_URL          웹서버 주소  (기본: http://localhost:8000)
  KB_COLLECT_SECRET      X-KB-Secret 헤더
  DATABASE_URL           로컬 PostgreSQL (pgvector 포함, Docker 네트워크 기준)
  KB_SYNC_DATABASE_URL   (선택) KB Sync 전용 DB URL. Docker 외부(Windows host/스케줄러)
                         실행 시 'postgres' 컨테이너 alias 가 resolve 안 되므로
                         published 포트(localhost:5433) 로 분리. 설정 시 DATABASE_URL 우선.
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


# ---------------------------------------------------------------------------
# Day24 — Cross-team failure_lesson pull
# ---------------------------------------------------------------------------

_TS_FILE = _PROJECT_ROOT / ".ada_failure_lesson_sync_ts"


def _read_last_sync_ts() -> str | None:
    """마지막 sync timestamp 읽기 (없으면 None)."""
    if not _TS_FILE.exists():
        return None
    try:
        return _TS_FILE.read_text(encoding="utf-8").strip() or None
    except Exception:  # noqa: BLE001
        return None


def _write_last_sync_ts(ts: str) -> None:
    try:
        _TS_FILE.write_text(ts, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.warning("write_last_sync_ts_failed: %s", e)


def _summarize_for_embedding(payload: dict) -> str:
    """failure_lesson payload 에서 임베딩용 요약 텍스트.

    agents.self_learning._summarize_fix 와 동일한 알고리즘.
    """
    parts = []
    sig = (payload.get("error_signature") or "")[:300]
    if sig:
        parts.append(f"ERROR: {sig}")
    explanation = (payload.get("explanation") or "")[:300]
    if explanation:
        parts.append(f"FIX_EXPLANATION: {explanation}")
    fix_diff = payload.get("fix_diff") or ""
    hunk_headers = [ln for ln in fix_diff.splitlines() if ln.startswith(("--- ", "+++ ", "@@"))][:10]
    if hunk_headers:
        parts.append("DIFF_TARGETS: " + " | ".join(hunk_headers))
    return "\n".join(parts)[:1000]


async def _upsert_failure_lesson(
    db_url: str,
    item: dict,
    dry_run: bool,
) -> tuple[str, str]:
    """failure_lesson 1건을 로컬 self_learning_kb 에 upsert + lesson_embeddings 에 임베딩.

    Returns:
        (status, kb_id)  — status in {"inserted","updated","skipped","dryrun"}
    """
    error_hash = item.get("error_hash") or ""
    payload = item.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:  # noqa: BLE001
            payload = {}
    confidence = float(item.get("confidence") or 0.5)

    if not error_hash or not isinstance(payload, dict) or not payload.get("fix_diff"):
        return "skipped", ""

    if dry_run:
        return "dryrun", item.get("kb_id") or ""

    # 비동기 DB
    if db_url.startswith("postgresql://"):
        async_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    else:
        async_url = db_url

    from sqlalchemy import text as sa_text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    engine = create_async_engine(async_url, echo=False)
    new_id = str(uuid.uuid4())

    try:
        async with AsyncSession(engine) as session:
            # ON CONFLICT(hash) DO UPDATE — agents.self_learning.record_error_fix 와 동일
            row = await session.execute(
                sa_text(
                    """
                    INSERT INTO self_learning_kb
                        (id, kb_type, hash, payload, confidence, success_count,
                         created_at, updated_at)
                    VALUES (
                        CAST(:id AS uuid),
                        'failure_lesson',
                        :hash,
                        CAST(:payload AS jsonb),
                        :confidence,
                        1,
                        NOW(),
                        NOW()
                    )
                    ON CONFLICT (hash) DO UPDATE SET
                        payload = EXCLUDED.payload,
                        confidence = (
                            (self_learning_kb.confidence * self_learning_kb.success_count
                             + EXCLUDED.confidence) / (self_learning_kb.success_count + 1)
                        ),
                        success_count = self_learning_kb.success_count + 1,
                        updated_at = NOW()
                    RETURNING id, (xmax = 0) AS inserted
                    """
                ).bindparams(
                    id=new_id,
                    hash=error_hash,
                    payload=json.dumps(payload, ensure_ascii=False),
                    confidence=max(0.0, min(1.0, confidence)),
                )
            )
            fetched = row.fetchone()
            if not fetched:
                await session.commit()
                return "skipped", ""
            kb_id = str(fetched[0])
            inserted = bool(fetched[1])

            # 임베딩 — 로컬에서 다시 생성. 모델 미설치/네트워크 실패 시 KB row 만 저장
            summary = _summarize_for_embedding(payload)
            try:
                emb = _embed(summary)
            except Exception as e:  # noqa: BLE001
                log.warning("embed model unavailable kb_id=%s: %s", kb_id[:8], e)
                emb = None
            if emb is not None:
                try:
                    emb_str = "[" + ",".join(f"{v:.6f}" for v in emb) + "]"
                    await session.execute(
                        sa_text(
                            """
                            INSERT INTO lesson_embeddings (kb_id, target, embedding)
                            VALUES (CAST(:kb_id AS uuid), :target, CAST(:emb AS vector))
                            ON CONFLICT (kb_id) DO UPDATE
                                SET target = EXCLUDED.target,
                                    embedding = EXCLUDED.embedding
                            """
                        ).bindparams(kb_id=kb_id, target=summary[:1000], emb=emb_str)
                    )
                except Exception as e:  # noqa: BLE001
                    log.warning("index failed kb_id=%s: %s", kb_id[:8], e)
                    # KB row 는 살아있음 — 다음 sync 에서 retry

            await session.commit()
            return ("inserted" if inserted else "updated"), kb_id
    finally:
        await engine.dispose()


async def _run_failure_lessons(server_url: str, secret: str, db_url: str, limit: int, dry_run: bool) -> None:
    """크로스팀 failure_lesson 풀러 — VPS → 로컬."""
    last_ts = _read_last_sync_ts()
    qs = f"?limit={limit}"
    if last_ts:
        # since 는 URL encode 안 해도 ISO 형식이라 안전
        qs += f"&since={last_ts}"

    url = f"{server_url}/kb/conversation/failure_lessons{qs}"
    log.info("Pull failure_lessons since=%s limit=%d", last_ts or "(no-state)", limit)

    try:
        resp = _api_get(url, secret)
    except urllib.error.URLError as e:
        log.error("Cannot reach %s: %s", url, e)
        return

    items = resp.get("items", [])
    total = resp.get("total", 0)
    log.info("Fetched %d failure_lessons", total)

    if not items:
        return

    ok = ins = upd = skip = fail = 0
    max_ts = last_ts or ""

    for item in items:
        try:
            status, _ = await _upsert_failure_lesson(db_url, item, dry_run)
        except Exception as e:  # noqa: BLE001
            log.warning("upsert failed kb_id=%s: %s", (item.get("kb_id") or "?")[:8], e)
            fail += 1
            continue

        if status == "inserted":
            ins += 1
            ok += 1
        elif status == "updated":
            upd += 1
            ok += 1
        elif status == "dryrun":
            ok += 1
        else:
            skip += 1

        # 가장 최근 updated_at 추적 (next sync since 후보)
        ut = item.get("updated_at") or ""
        if ut and ut > max_ts:
            max_ts = ut

    # 다음 sync 를 위해 timestamp 저장 (dry-run 은 갱신 안 함)
    if not dry_run and max_ts and max_ts != last_ts:
        _write_last_sync_ts(max_ts)
        log.info("Last sync ts updated → %s", max_ts)

    log.info(
        "=== FAILURE_LESSONS DONE: ok=%d (ins=%d upd=%d) skip=%d fail=%d ===",
        ok,
        ins,
        upd,
        skip,
        fail,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="ADA KB sync (Q&A + failure_lessons)")
    parser.add_argument(
        "--mode",
        choices=["qa", "failure_lessons", "both"],
        default="qa",
        help="qa: 기존 Q&A 처리 / failure_lessons: 크로스팀 풀 / both: 둘 다 (cron 추천)",
    )
    parser.add_argument("--limit", type=int, default=100, help="최대 처리 건수 (기본 100)")
    parser.add_argument("--dry-run", action="store_true", help="DB 저장 없이 내용 출력만")
    args = parser.parse_args()

    server_url = _cfg("KB_SERVER_URL", "http://localhost:8000").rstrip("/")
    secret = _cfg("KB_COLLECT_SECRET", "")
    # KB Sync 전용 DB URL 우선. 미설정 시 일반 DATABASE_URL fallback.
    db_url = _cfg("KB_SYNC_DATABASE_URL", "") or _cfg(
        "DATABASE_URL", "postgresql://autoai:changeme@postgres:5432/autoai"
    )

    log.info(
        "KB Sync start  mode=%s  server=%s  limit=%d  dry_run=%s",
        args.mode,
        server_url,
        args.limit,
        args.dry_run,
    )

    qa_failed = False
    if args.mode in ("qa", "both"):
        try:
            asyncio.run(_run(server_url, secret, db_url, args.limit, args.dry_run))
        except SystemExit:
            qa_failed = True
            if args.mode == "qa":
                raise
            log.warning("qa mode failed, continuing to failure_lessons (--mode=both)")
        except Exception as e:  # noqa: BLE001
            qa_failed = True
            log.error("qa mode exception: %s", e)
            if args.mode == "qa":
                sys.exit(1)
    if args.mode in ("failure_lessons", "both"):
        try:
            asyncio.run(_run_failure_lessons(server_url, secret, db_url, args.limit, args.dry_run))
        except Exception as e:  # noqa: BLE001
            log.error("failure_lessons mode exception: %s", e)
            if args.mode == "failure_lessons":
                sys.exit(1)
    if args.mode == "both" and qa_failed:
        sys.exit(2)  # 부분 실패 신호 (cron 알람용)


if __name__ == "__main__":
    main()
