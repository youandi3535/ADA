"""api.routes.admin — Day 3 관리자 전용 라우터.

엔드포인트:
    GET /admin/audit                          최근 SecurityAuditLog 페이지네이션
    GET /admin/audit/summary                   event_type 별 카운트
    GET /admin/observability/langfuse          Langfuse 연결 헬스체크
    GET /admin/observability/prometheus_check  /metrics endpoint smoke check
    GET /admin/autofix/failure_logs            Phase 2 failure_logs 페이지네이션
    GET /admin/autofix/patch_applications      패치 적용 status 집계
    GET /admin/autofix/circuit_breakers        회로 차단기 현재 상태 + 최근 이벤트
    GET /admin/autofix/budget                  오늘 LLM 예산 스냅샷

모두 RBAC: admin 또는 service 역할만 허용.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ada.db.session import get_db
from ada.security.rbac import require_perm

router = APIRouter()

# 'admin' 권한 — RBAC 매트릭스에서 admin/service 만 허용
_admin_only = require_perm("admin.audit.read")


class AuditEntry(BaseModel):
    id: str
    event_type: str
    actor_user_id: Optional[str] = None
    actor_role: Optional[str] = None
    resource: Optional[str] = None
    action: Optional[str] = None
    result: Optional[str] = None
    ip_address: Optional[str] = None
    details: Optional[dict[str, Any]] = None
    created_at: Optional[str] = None


class AuditPage(BaseModel):
    items: list[AuditEntry]
    total: int
    page: int
    page_size: int


@router.get("/admin/audit", response_model=AuditPage, tags=["Admin"])
async def get_audit_log(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    event_type: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    result: Optional[str] = None,
    since_hours: Optional[int] = Query(None, ge=1, le=24 * 30),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),
) -> AuditPage:
    """SecurityAuditLog 페이지네이션 — admin 전용."""
    from ada.db.models import SecurityAuditLog

    where_clauses = []
    if event_type:
        where_clauses.append(SecurityAuditLog.event_type == event_type)
    if result:
        where_clauses.append(SecurityAuditLog.result == result)
    if actor_user_id:
        where_clauses.append(SecurityAuditLog.actor_user_id == actor_user_id)
    if since_hours:
        where_clauses.append(SecurityAuditLog.created_at >= datetime.utcnow() - timedelta(hours=since_hours))

    base_q = select(SecurityAuditLog)
    if where_clauses:
        for c in where_clauses:
            base_q = base_q.where(c)

    # total count
    count_q = select(func.count()).select_from(base_q.subquery())
    total = int((await db.execute(count_q)).scalar() or 0)

    rows = (
        await db.scalars(
            base_q.order_by(desc(SecurityAuditLog.created_at)).offset((page - 1) * page_size).limit(page_size)
        )
    ).all()

    items = [
        AuditEntry(
            id=str(r.id),
            event_type=r.event_type,
            actor_user_id=str(r.actor_user_id) if r.actor_user_id else None,
            actor_role=r.actor_role,
            resource=r.resource,
            action=r.action,
            result=r.result,
            ip_address=r.ip_address,
            details=r.details if isinstance(r.details, dict) else None,
            created_at=r.created_at.isoformat() if r.created_at else None,
        )
        for r in rows
    ]
    return AuditPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/admin/audit/summary", tags=["Admin"])
async def get_audit_summary(
    since_hours: int = Query(24, ge=1, le=24 * 30),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),
) -> dict[str, Any]:
    """event_type × result 별 누적 카운트 (최근 N 시간)."""
    from ada.db.models import SecurityAuditLog

    since = datetime.utcnow() - timedelta(hours=since_hours)
    rows = await db.execute(
        select(
            SecurityAuditLog.event_type,
            SecurityAuditLog.result,
            func.count().label("n"),
        )
        .where(SecurityAuditLog.created_at >= since)
        .group_by(SecurityAuditLog.event_type, SecurityAuditLog.result)
    )
    summary: dict[str, dict[str, int]] = {}
    for et, res, n in rows:
        summary.setdefault(et or "?", {})[res or "?"] = int(n)
    return {"since_hours": since_hours, "summary": summary}


@router.get("/admin/observability/langfuse", tags=["Admin"])
async def langfuse_health(_user: dict = Depends(_admin_only)) -> dict[str, Any]:
    """Day 3 — Langfuse 연결 헬스체크."""
    from ada.core.langfuse_client import verify_connection

    return verify_connection()


@router.get("/admin/observability/prometheus_check", tags=["Admin"])
async def prometheus_check(_user: dict = Depends(_admin_only)) -> dict[str, Any]:
    """Prometheus 메트릭 노출 smoke check."""
    from ada.observability.metrics import render_metrics

    body = render_metrics()
    text = body.decode("utf-8", errors="ignore")
    return {
        "available": "ada_agent_duration_seconds" in text or "ada_jobs_active" in text,
        "size_bytes": len(body),
        "sample_lines": text.splitlines()[:5],
    }


# =============================================================================
# ADR-008 L4 — PII 마스킹 통계
# =============================================================================


class PIIHourlyBucket(BaseModel):
    hour: str
    events: int
    tokens: int


class PIITopActor(BaseModel):
    actor_user_id: str
    events: int


class PIIStatsResponse(BaseModel):
    total_tokens_masked: int
    total_events: int
    by_hour: list[PIIHourlyBucket]
    top_actors: list[PIITopActor]
    since_hours: int


@router.get("/admin/security/pii", response_model=PIIStatsResponse, tags=["Admin", "Security"])
async def get_pii_stats(
    since_hours: int = Query(24, ge=1, le=24 * 30),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),
) -> PIIStatsResponse:
    """ADR-008 L4 — SecurityAuditLog 의 pii_anonymized 이벤트 집계."""
    from sqlalchemy import desc, select

    from ada.db.models import SecurityAuditLog

    since = datetime.utcnow() - timedelta(hours=since_hours)

    rows = (
        await db.scalars(
            select(SecurityAuditLog)
            .where(SecurityAuditLog.action == "pii_anonymized")
            .where(SecurityAuditLog.created_at >= since)
            .order_by(desc(SecurityAuditLog.created_at))
        )
    ).all()

    total_tokens = 0
    total_events = 0
    by_hour: dict[str, dict[str, int]] = {}
    actor_count: dict[str, int] = {}

    for r in rows:
        total_events += 1
        n = (r.details or {}).get("n_tokens", 0) if isinstance(r.details, dict) else 0
        total_tokens += int(n)

        hour_key = r.created_at.strftime("%Y-%m-%dT%H") if r.created_at else "unknown"
        bucket = by_hour.setdefault(hour_key, {"events": 0, "tokens": 0})
        bucket["events"] += 1
        bucket["tokens"] += int(n)

        actor = str(r.actor_user_id) if r.actor_user_id else "anonymous"
        actor_count[actor] = actor_count.get(actor, 0) + 1

    return PIIStatsResponse(
        total_tokens_masked=total_tokens,
        total_events=total_events,
        by_hour=[PIIHourlyBucket(hour=h, events=v["events"], tokens=v["tokens"]) for h, v in sorted(by_hour.items())],
        top_actors=sorted(
            [PIITopActor(actor_user_id=a, events=c) for a, c in actor_count.items()],
            key=lambda x: x.events,
            reverse=True,
        )[:10],
        since_hours=since_hours,
    )


# =============================================================================
# ADR-006 Phase 2 — Autofix 운영 모니터링 라우트
# =============================================================================

_KNOWN_BREAKERS = ["ollama", "claude_cli", "anthropic"]


class FailureLogItem(BaseModel):
    id: str
    error_hash: Optional[str] = None
    classified_as: Optional[str] = None
    severity: Optional[str] = None
    created_at: Optional[str] = None


class FailureLogPage(BaseModel):
    items: list[FailureLogItem]
    total: int
    page: int
    page_size: int


@router.get("/admin/autofix/failure_logs", tags=["Admin"])
async def get_failure_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=500),
    classified_as: Optional[str] = None,
    severity: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),
) -> FailureLogPage:
    """Phase 2 failure_logs 페이지네이션 — admin 전용."""
    from ada.db.models import FailureLog

    base_q = select(FailureLog)
    if classified_as:
        base_q = base_q.where(FailureLog.classified_as == classified_as)
    if severity:
        base_q = base_q.where(FailureLog.severity == severity)

    count_q = select(func.count()).select_from(base_q.subquery())
    total = int((await db.execute(count_q)).scalar() or 0)

    rows = (
        await db.scalars(base_q.order_by(desc(FailureLog.created_at)).offset((page - 1) * page_size).limit(page_size))
    ).all()

    items = [
        FailureLogItem(
            id=str(r.id),
            error_hash=r.error_hash,
            classified_as=r.classified_as,
            severity=r.severity,
            created_at=r.created_at.isoformat() if r.created_at else None,
        )
        for r in rows
    ]
    return FailureLogPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/admin/autofix/patch_applications", tags=["Admin"])
async def get_patch_applications(
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),
) -> dict[str, Any]:
    """patch_applications status 집계 — admin 전용."""
    from ada.db.models import PatchApplication

    result = await db.execute(
        select(PatchApplication.status, func.count().label("n")).group_by(PatchApplication.status)
    )
    status_counts: dict[str, int] = {}
    for row in result:
        status_counts[row[0] or "unknown"] = int(row[1])
    return {"total": sum(status_counts.values()), "status_counts": status_counts}


@router.get("/admin/autofix/circuit_breakers", tags=["Admin"])
async def get_circuit_breakers(
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),
) -> dict[str, Any]:
    """회로 차단기 현재 상태 + 최근 이벤트 — admin 전용."""
    from ada.db.models import CircuitBreakerEvent
    from ada.error_handler.circuit_breaker import _InMemoryBackend

    current_state: dict[str, dict[str, Any]] = {}
    for name in _KNOWN_BREAKERS:
        state = await _InMemoryBackend.get_state(name)
        current_state[name] = {"state": state or "unknown"}

    recent_rows = (
        await db.scalars(select(CircuitBreakerEvent).order_by(desc(CircuitBreakerEvent.created_at)).limit(50))
    ).all()
    recent_events = [
        {
            "id": str(r.id),
            "breaker_name": r.breaker_name,
            "event_type": r.event_type,
            "failure_count": r.failure_count,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in recent_rows
    ]
    return {"current_state": current_state, "recent_events": recent_events}


@router.get("/admin/autofix/budget", tags=["Admin"])
async def get_budget_snapshot(
    _user: dict = Depends(_admin_only),
) -> dict[str, Any]:
    """오늘 LLM 예산 현황 스냅샷 — admin 전용."""
    from ada.error_handler.budget import get_budget_manager

    bm = get_budget_manager()
    today_spend = await bm.get_today_spend()
    today_calls = await bm.get_today_calls()
    daily_limit = bm._daily_limit()
    exceeded = await bm.is_exceeded()
    remaining = await bm.remaining_budget()

    return {
        "today_spend_usd": round(today_spend, 4),
        "today_calls": today_calls,
        "daily_limit_usd": daily_limit,
        "remaining_usd": round(remaining, 4),
        "is_exceeded": exceeded,
        "date_utc": datetime.utcnow().date().isoformat(),
    }


@router.get("/admin/metrics/dashboard", tags=["Admin"])
async def get_metrics_dashboard(
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),
) -> dict[str, Any]:
    """데이터 저장·활용 현황 집계 — admin 전용 (관리자 대시보드용)."""
    from ada.db.models import ConversationLog, FailureLog, SelfLearningKB

    failures_total = await db.scalar(select(func.count()).select_from(FailureLog)) or 0
    failures_auto = (
        await db.scalar(select(func.count()).select_from(FailureLog).where(FailureLog.auto_handled_by_kb.is_(True)))
        or 0
    )
    kb_total = await db.scalar(select(func.count()).select_from(SelfLearningKB)) or 0
    qa_total = await db.scalar(select(func.count()).select_from(ConversationLog)) or 0
    qa_processed = (
        await db.scalar(select(func.count()).select_from(ConversationLog).where(ConversationLog.processed.is_(True)))
        or 0
    )
    kb_by_type: dict[str, int] = {}
    for _row in (await db.execute(select(SelfLearningKB.kb_type, func.count()).group_by(SelfLearningKB.kb_type))).all():
        kb_by_type[str(_row[0])] = int(_row[1])

    return {
        "failures_total": int(failures_total),
        "failures_auto_handled": int(failures_auto),
        "auto_handle_rate": (round(int(failures_auto) / int(failures_total) * 100, 1) if failures_total else 0.0),
        "kb_total": int(kb_total),
        "kb_by_type": kb_by_type,
        "qa_total": int(qa_total),
        "qa_processed": int(qa_processed),
    }


# =============================================================================
# 운영 콘솔 — 데이터 저장 실시간 통합 현황
#   VPS 원본(PostgreSQL/MinIO/MLflow/Redis) + 로컬 백업 서버를 한 화면에서 감시.
#   30개 테이블을 8개 데이터 카테고리로 분류 + 각 스토리지 연결 헬스(정상/경고/위험).
# =============================================================================

# 테이블 → 데이터 카테고리 매핑 (운영 콘솔 분류 기준). models.py 의 30개 테이블 전수 포함.
_CATEGORY_DEFS: list[dict[str, Any]] = [
    {
        "key": "raw",
        "title": "원본 데이터 · 업로드",
        "icon": "📥",
        "desc": "사용자가 올린 원본 데이터셋과 의미 임베딩",
        "stores": ["MinIO autoai-artifacts", "VPS /opt/ada/data", "PostgreSQL"],
        "tables": ["uploads", "dataset_embeddings"],
    },
    {
        "key": "jobs",
        "title": "분석 작업 · 실행 기록",
        "icon": "⚙️",
        "desc": "파이프라인 작업·에이전트 실행·게이트(HITL) 결정 이력",
        "stores": ["PostgreSQL"],
        "tables": [
            "jobs",
            "agent_runs",
            "experiments",
            "gate_decision_metrics",
            "decisions",
            "interactive_sessions",
            "intent_embeddings",
        ],
    },
    {
        "key": "outputs",
        "title": "산출물 · 학습 모델",
        "icon": "📦",
        "desc": "PPT·PDF·HTML 등 5종 산출물과 학습된 모델 아티팩트",
        "stores": ["MinIO autoai-artifacts", "MLflow"],
        "tables": ["outputs", "artifacts", "output_recipes", "models", "model_artifact_catalog"],
    },
    {
        "key": "errors",
        "title": "오류 자동 수정 (self-healing)",
        "icon": "🛠️",
        "desc": "오류 자동 캐치·진단·패치 이력 (원본은 AES-GCM 암호화 보관)",
        "stores": ["PostgreSQL (암호화)"],
        "tables": [
            "failure_logs",
            "error_kb",
            "pending_patches",
            "patch_applications",
            "circuit_breaker_events",
        ],
    },
    {
        "key": "learning",
        "title": "자기학습 KB",
        "icon": "🧠",
        "desc": "성공패턴·레시피·EDA·HPO·교훈 — 신규 작업에 재사용되는 학습 자산",
        "stores": ["PostgreSQL + pgvector"],
        "tables": ["self_learning_kb", "success_patterns", "rules", "lesson_embeddings", "job_distillation_log"],
    },
    {
        "key": "qa",
        "title": "Q&A · 대화 수집",
        "icon": "💬",
        "desc": "Cowork·Claude Code 대화 → 임베딩 → KB 학습 원천",
        "stores": ["PostgreSQL"],
        "tables": ["conversation_logs"],
    },
    {
        "key": "security",
        "title": "보안 · 계정 · 감사",
        "icon": "🔐",
        "desc": "로그인·감사 로그·계정·에이전트 레지스트리",
        "stores": ["PostgreSQL"],
        "tables": ["security_audit_log", "users", "oauth_accounts", "agent_registry"],
    },
    {
        "key": "backup",
        "title": "백업 카탈로그",
        "icon": "💾",
        "desc": "로컬 백업 서버 적재 기록 (Pull 방식, 1일 3회 03·12·18시)",
        "stores": ["로컬 /srv/backup/ada"],
        "tables": ["backup_catalog"],
    },
]

_ALL_TABLES: list[str] = [t for c in _CATEGORY_DEFS for t in c["tables"]]
# created_at 이 아닌 타임스탬프 컬럼을 쓰는 테이블 (신규 적재 감지·트렌드용)
_TS_COL: dict[str, str] = {"patch_applications": "applied_at", "job_distillation_log": "distilled_at"}


def _ts_col(table: str) -> str:
    return _TS_COL.get(table, "created_at")


@router.get("/admin/storage/overview", tags=["Admin"])
async def storage_overview(
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),
) -> dict[str, Any]:
    """운영 콘솔 — 데이터 저장·DB·백업 실시간 통합 현황 (admin 전용).

    한 번의 호출로 ① 스토리지 연결 헬스(정상/경고/위험) ② 8개 카테고리별 행수·용량
    ③ 30개 테이블 전수 인벤토리 ④ 7일 적재 트렌드 ⑤ 백업 현황 을 모두 반환한다.
    각 스토리지는 개별 try/except + 타임아웃으로 격리 — 하나가 죽어도 나머지는 표시된다.
    """
    import asyncio
    import time
    import urllib.request

    from sqlalchemy import text

    from ada.core.config import settings
    from tools.minio_tool import get_minio_client

    now = datetime.utcnow()
    out: dict[str, Any] = {"generated_at": now.isoformat() + "Z"}

    # ── 1) PostgreSQL: 정확한 행수 + 테이블 크기 + DB 총량 ──────────────────
    counts: dict[str, int] = {}
    sizes: dict[str, int] = {}
    recent24: dict[str, int] = {}
    db_total = 0
    pg_status = "down"
    pg_latency: Optional[float] = None
    pg_detail = "연결 실패"
    try:
        t0 = time.time()
        cnt_sql = " UNION ALL ".join(f"SELECT '{t}' AS tbl, count(*)::bigint AS n FROM {t}" for t in _ALL_TABLES)
        for r in (await db.execute(text(cnt_sql))).all():
            counts[r.tbl] = int(r.n)
        for r in (
            await db.execute(text("SELECT relname, pg_total_relation_size(relid) AS b FROM pg_stat_user_tables"))
        ).all():
            sizes[r.relname] = int(r.b)
        db_total = int(await db.scalar(text("SELECT pg_database_size(current_database())")) or 0)
        pg_latency = round((time.time() - t0) * 1000, 1)
        pg_status = "ok"
        pg_detail = f"{len(_ALL_TABLES)}개 테이블 · 응답 {pg_latency}ms"
    except Exception as e:  # noqa: BLE001
        out["pg_error"] = str(e)[:200]

    # 최근 24시간 신규 적재 (실시간 저장 여부 감지) — 별도 격리
    try:
        rec_sql = " UNION ALL ".join(
            f"SELECT '{t}' AS tbl, count(*)::bigint AS n FROM {t} WHERE {_ts_col(t)} > now() - interval '24 hours'"
            for t in _ALL_TABLES
        )
        for r in (await db.execute(text(rec_sql))).all():
            recent24[r.tbl] = int(r.n)
    except Exception:  # noqa: BLE001
        recent24 = {}

    # 앱 관점 실제 저장 용량 (MinIO 적재 바이트)
    uploads_bytes = outputs_bytes = 0
    try:
        uploads_bytes = int(await db.scalar(text("SELECT coalesce(sum(size_bytes),0) FROM uploads")) or 0)
        outputs_bytes = int(await db.scalar(text("SELECT coalesce(sum(file_size_bytes),0) FROM outputs")) or 0)
    except Exception:  # noqa: BLE001
        pass

    # ── 2) 보조 스토리지 헬스 (MinIO / Redis / MLflow) — 스레드 + 타임아웃 격리 ──
    def _scan_minio() -> dict[str, Any]:
        cli = get_minio_client()
        s3, bucket = cli.s3, cli.bucket
        total_b = total_n = pages = 0
        pref: dict[str, dict[str, int]] = {}
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
            for obj in page.get("Contents", []):
                sz = int(obj.get("Size", 0))
                total_b += sz
                total_n += 1
                top = obj["Key"].split("/", 1)[0]
                d = pref.setdefault(top, {"n": 0, "b": 0})
                d["n"] += 1
                d["b"] += sz
            pages += 1
            if pages >= 60 or total_n >= 60000:
                break
        return {
            "bucket": bucket,
            "objects": total_n,
            "bytes": total_b,
            "truncated": pages >= 60 or total_n >= 60000,
            "prefixes": sorted(
                [{"name": k, "objects": v["n"], "bytes": v["b"]} for k, v in pref.items()],
                key=lambda x: -x["bytes"],
            )[:12],
        }

    def _scan_redis() -> dict[str, Any]:
        import redis as _redis

        r = _redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
        r.ping()
        info = r.info()
        return {
            "keys": int(r.dbsize()),
            "used_memory": int(info.get("used_memory", 0)),
            "uptime_sec": int(info.get("uptime_in_seconds", 0)),
            "version": str(info.get("redis_version", "")),
        }

    def _check_mlflow() -> bool:
        uri = settings.mlflow_tracking_uri.rstrip("/")
        for path in ("/health", ""):
            try:
                with urllib.request.urlopen(uri + path, timeout=3) as resp:  # noqa: S310
                    if 200 <= resp.getcode() < 500:
                        return True
            except Exception:  # noqa: BLE001
                continue
        return False

    async def _safe(fn: Any, timeout: float = 5.0) -> tuple[bool, Any]:
        try:
            return True, await asyncio.wait_for(asyncio.to_thread(fn), timeout=timeout)
        except Exception as e:  # noqa: BLE001
            return False, str(e)[:160]

    (minio_ok, minio_res), (redis_ok, redis_res), (mlflow_ok, mlflow_res) = await asyncio.gather(
        _safe(_scan_minio),
        _safe(_scan_redis),
        _safe(_check_mlflow, timeout=4.0),
    )

    # ── 3) 백업 현황 (backup_catalog + 고정 스케줄) ─────────────────────────
    backup_last: list[dict[str, Any]] = []
    last_backup_at: Optional[str] = None
    try:
        from ada.db.models import BackupCatalog

        for bt in ("db", "data", "vault"):
            row = (
                await db.scalars(
                    select(BackupCatalog)
                    .where(BackupCatalog.backup_type == bt)
                    .order_by(desc(BackupCatalog.created_at))
                    .limit(1)
                )
            ).first()
            if row:
                backup_last.append(
                    {
                        "type": bt,
                        "at": row.created_at.isoformat() if row.created_at else None,
                        "size_bytes": int(row.size_bytes or 0),
                        "status": row.status or "ok",
                        "path": row.minio_path,
                    }
                )
                if row.created_at and (last_backup_at is None or row.created_at.isoformat() > last_backup_at):
                    last_backup_at = row.created_at.isoformat()
    except Exception:  # noqa: BLE001
        backup_last = []

    # 백업 상태 판정: 기록 있으면 신선도(>20h 경고/>30h 위험), 없으면 경고(앱 DB 미기록)
    backup_status = "warn"
    backup_note = (
        "백업 파일은 로컬 서버에 적재되지만 backup_catalog 기록이 아직 없습니다. "
        "백업 스크립트(backup_postgres.sh)를 1회 실행하면 카탈로그에 등록되어 🟢 정상으로 표시됩니다."
    )
    backup_age_h: Optional[float] = None
    if last_backup_at:
        try:
            # created_at 은 tz-aware(+00:00)일 수 있어 naive now(utcnow)와 직접 빼면 TypeError →
            # tz 있으면 UTC 로 정규화 후 tzinfo 제거해 naive-UTC 끼리 비교한다.
            _p = datetime.fromisoformat(last_backup_at.replace("Z", "+00:00"))
            if _p.tzinfo is not None:
                _p = _p.astimezone(timezone.utc).replace(tzinfo=None)
            age = (now - _p).total_seconds() / 3600.0
            backup_age_h = round(age, 1)
            backup_status = "ok" if age <= 20 else ("warn" if age <= 30 else "down")
            backup_note = f"최근 백업 {backup_age_h}시간 전 · 보존 14일"
        except Exception:  # noqa: BLE001
            pass

    # ── 4) 서비스 헬스 묶음 ────────────────────────────────────────────────
    services = [
        {
            "key": "postgres",
            "name": "PostgreSQL · 원본 DB",
            "where": "VPS ada-postgres",
            "status": pg_status,
            "metric": _fmt_bytes(db_total) if pg_status == "ok" else "—",
            "detail": pg_detail,
        },
        {
            "key": "minio",
            "name": "MinIO · 오브젝트 스토리지",
            "where": "VPS autoai-artifacts",
            "status": "ok" if minio_ok else "down",
            "metric": (_fmt_bytes(minio_res["bytes"]) if minio_ok else "—"),
            "detail": (f"{minio_res['objects']:,}개 객체" if minio_ok else f"연결 실패: {minio_res}"),
        },
        {
            "key": "redis",
            "name": "Redis · 실시간 큐·캐시",
            "where": "VPS ada-redis",
            "status": "ok" if redis_ok else "down",
            "metric": (_fmt_bytes(redis_res["used_memory"]) if redis_ok else "—"),
            "detail": (
                f"{redis_res['keys']:,}개 키 · v{redis_res['version']}" if redis_ok else f"연결 실패: {redis_res}"
            ),
        },
        {
            "key": "mlflow",
            "name": "MLflow · 학습 추적",
            "where": "VPS mlflow:5000",
            "status": "ok" if mlflow_ok else "down",
            "metric": ("정상" if mlflow_ok else "—"),
            "detail": ("추적 서버 응답" if mlflow_ok else "응답 없음"),
        },
        {
            "key": "backup",
            "name": "로컬 백업 서버 · 학원 Linux",
            "where": "/srv/backup/ada (Pull)",
            "status": backup_status,
            "metric": (f"{backup_age_h}h 전" if backup_age_h is not None else "기록 없음"),
            "detail": backup_note,
        },
    ]

    # ── 5) 카테고리 롤업 ───────────────────────────────────────────────────
    categories = []
    total_rows_all = 0
    for c in _CATEGORY_DEFS:
        rows = sum(counts.get(t, 0) for t in c["tables"])
        byts = sum(sizes.get(t, 0) for t in c["tables"])
        rec = sum(recent24.get(t, 0) for t in c["tables"])
        total_rows_all += rows
        cat_status = "ok" if pg_status == "ok" else "down"
        if c["key"] == "backup":
            cat_status = backup_status
        categories.append(
            {
                **{k: c[k] for k in ("key", "title", "icon", "desc", "stores")},
                "total_rows": rows,
                "total_bytes": byts,
                "recent_24h": rec,
                "status": cat_status,
                "tables": [
                    {
                        "name": t,
                        "rows": counts.get(t, 0),
                        "bytes": sizes.get(t, 0),
                        "recent_24h": recent24.get(t, 0),
                    }
                    for t in c["tables"]
                ],
            }
        )

    # ── 6) 7일 적재 트렌드 (차트용) ────────────────────────────────────────
    async def _daily(table: str) -> list[dict[str, Any]]:
        try:
            col = _ts_col(table)
            rows = (
                await db.execute(
                    text(
                        f"SELECT to_char(date_trunc('day', {col}),'MM-DD') AS d, count(*)::bigint AS n "
                        f"FROM {table} WHERE {col} > now() - interval '7 days' GROUP BY 1 ORDER BY 1"
                    )
                )
            ).all()
            return [{"d": r.d, "n": int(r.n)} for r in rows]
        except Exception:  # noqa: BLE001
            return []

    trends = {
        "jobs": await _daily("jobs"),
        "failures": await _daily("failure_logs"),
        "qa": await _daily("conversation_logs"),
        "outputs": await _daily("outputs"),
    }

    # ── 6-b) 24시간 적재 트렌드 (시간 단위 · 1일 추이) ─────────────────────
    async def _hourly(table: str) -> list[dict[str, Any]]:
        try:
            col = _ts_col(table)
            rows = (
                await db.execute(
                    text(
                        f"SELECT to_char(date_trunc('hour', {col}),'HH24:00') AS d, count(*)::bigint AS n "
                        f"FROM {table} WHERE {col} > now() - interval '24 hours' GROUP BY 1 ORDER BY 1"
                    )
                )
            ).all()
            return [{"d": r.d, "n": int(r.n)} for r in rows]
        except Exception:  # noqa: BLE001
            return []

    trends_24h = {
        "jobs": await _hourly("jobs"),
        "failures": await _hourly("failure_logs"),
        "qa": await _hourly("conversation_logs"),
        "outputs": await _hourly("outputs"),
    }

    # ── 7) 오류 자동수정 · 학습 하이라이트 (요약 카드) ─────────────────────
    highlight: dict[str, Any] = {}
    try:
        fl_total = counts.get("failure_logs", 0)
        fl_auto = int(await db.scalar(text("SELECT count(*) FROM failure_logs WHERE auto_handled_by_kb = true")) or 0)
        kb_by_type: dict[str, int] = {}
        for r in (await db.execute(text("SELECT kb_type, count(*) AS n FROM self_learning_kb GROUP BY kb_type"))).all():
            kb_by_type[str(r.kb_type)] = int(r.n)
        qa_processed = int(await db.scalar(text("SELECT count(*) FROM conversation_logs WHERE processed = true")) or 0)
        highlight = {
            "failures_total": fl_total,
            "failures_auto_handled": fl_auto,
            "auto_handle_rate": (round(fl_auto / fl_total * 100, 1) if fl_total else 0.0),
            "kb_total": counts.get("self_learning_kb", 0),
            "kb_by_type": kb_by_type,
            "qa_total": counts.get("conversation_logs", 0),
            "qa_processed": qa_processed,
        }
    except Exception:  # noqa: BLE001
        highlight = {}

    # ── 7-b) 자가치유·자기학습 활용 현황 (언제/무엇이/어떻게 작동·적용됐나) ───────────
    #   저장만 하는 게 아니라 '실제로 활용/자동수정에 쓰인' 수치 + 최근 이벤트(과정·결과)를 노출.
    self_healing: dict[str, Any] = {"errors": {}, "learning": {}, "recent": []}
    try:

        async def _c(sql: str) -> int:
            return int(await db.scalar(text(sql)) or 0)

        _d24 = "now() - interval '24 hours'"
        # 오류: 캐치(failure_logs) + 실제 자동수정 적용(patch_applications) + KB 자동해결(auto_handled_by_kb)
        self_healing["errors"] = {
            "caught_total": counts.get("failure_logs", 0),
            "caught_24h": await _c(f"SELECT count(*) FROM failure_logs WHERE created_at > {_d24}"),
            "auto_fixed_total": await _c("SELECT count(*) FROM patch_applications WHERE status='success'"),
            "auto_fixed_24h": await _c(
                f"SELECT count(*) FROM patch_applications WHERE status='success' AND applied_at > {_d24}"
            ),
            "kb_resolved_total": await _c("SELECT count(*) FROM failure_logs WHERE auto_handled_by_kb = true"),
            "kb_resolved_24h": await _c(
                f"SELECT count(*) FROM failure_logs WHERE auto_handled_by_kb = true AND created_at > {_d24}"
            ),
            "rolled_back": await _c("SELECT count(*) FROM patch_applications WHERE status='rolled_back'"),
        }
        # 자기학습: 학습자산 수 + 재사용(누적 success_count 합) + 24h 활용(최근 갱신/자동해결)
        self_healing["learning"] = {
            "assets": counts.get("self_learning_kb", 0) + counts.get("error_kb", 0),
            "reuse_total": (await _c("SELECT coalesce(sum(success_count),0) FROM self_learning_kb"))
            + (await _c("SELECT coalesce(sum(success_count),0) FROM error_kb")),
            "reuse_24h": self_healing["errors"]["kb_resolved_24h"],
            "active_24h": await _c(f"SELECT count(*) FROM self_learning_kb WHERE updated_at > {_d24}"),
        }
        # 최근 자동수정 이벤트 (언제 · 어떤 단계/오류 · 누가/어떻게(commit) · 결과)
        ev_rows = (
            await db.execute(
                text(
                    "SELECT pa.applied_at, pa.status, pa.applied_by, pa.git_commit_sha, pa.duration_ms, "
                    "ek.error_signature, ek.fingerprint "
                    "FROM patch_applications pa LEFT JOIN error_kb ek ON ek.id = pa.error_kb_id "
                    "ORDER BY pa.applied_at DESC LIMIT 8"
                )
            )
        ).all()
        for r in ev_rows:
            fp = r.fingerprint if isinstance(r.fingerprint, dict) else {}
            self_healing["recent"].append(
                {
                    "at": r.applied_at.isoformat() if r.applied_at else None,
                    "status": r.status or "",
                    "by": r.applied_by or "",
                    "sha": (r.git_commit_sha or "")[:8],
                    "ms": int(r.duration_ms or 0),
                    "stage": str(fp.get("stage", "") or ""),
                    "error_type": str(fp.get("error_type", "") or ""),
                    "signature": (r.error_signature or "")[:120],
                }
            )
    except Exception:  # noqa: BLE001
        pass

    # ── 8) 스토리지 토폴로지 (VPS 원본 → 로컬 백업) ────────────────────────
    storage_nodes = [
        {
            "role": "primary",
            "name": "VPS 웹 서버 (원본 · 실시간)",
            "path": "/opt/ada · ada-postgres · autoai-artifacts",
            "status": pg_status if pg_status == "ok" else "warn",
            "detail": f"DB {_fmt_bytes(db_total)}"
            + (f" · MinIO {_fmt_bytes(minio_res['bytes'])}" if minio_ok else " · MinIO 점검필요"),
        },
        {
            "role": "backup",
            "name": "로컬 백업 서버 (학원 Linux)",
            "path": "/srv/backup/ada/{postgres,datasets}",
            "status": backup_status,
            "detail": backup_note,
        },
    ]

    out.update(
        {
            "services": services,
            "kpis": {
                "db_total_bytes": db_total,
                "minio_bytes": (minio_res["bytes"] if minio_ok else None),
                "minio_objects": (minio_res["objects"] if minio_ok else None),
                # 영구 저장소(PostgreSQL + MinIO) 누적 총량 — '지금까지 저장된 모든 데이터'.
                # Redis(used_memory)는 휘발성 캐시이므로 누적 총량에서 제외한다.
                "persistent_total_bytes": db_total + (minio_res["bytes"] if minio_ok else 0),
                "total_rows": total_rows_all,
                "uploads_bytes": uploads_bytes,
                "outputs_bytes": outputs_bytes,
                "last_backup_at": last_backup_at,
                "backup_age_h": backup_age_h,
            },
            "categories": categories,
            "minio": (minio_res if minio_ok else {"error": minio_res}),
            "redis": (redis_res if redis_ok else {"error": redis_res}),
            "trends": trends,
            "trends_24h": trends_24h,
            "highlight": highlight,
            "self_healing": self_healing,
            "backup": {
                "schedule": "매일 03 · 12 · 18시 (1일 3회)",
                "method": "Pull (로컬 서버 → VPS pg_dump)",
                "retention_days": 14,
                "paths": ["/srv/backup/ada/postgres", "/srv/backup/ada/datasets"],
                "status": backup_status,
                "note": backup_note,
                "last": backup_last,
            },
            "storage_nodes": storage_nodes,
            "db_total_bytes": db_total,
        }
    )
    return out


def _fmt_bytes(n: Optional[int]) -> str:
    """바이트 → 사람이 읽는 단위 (KB/MB/GB)."""
    if not n:
        return "0 B"
    v = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if v < 1024 or unit == "TB":
            return f"{v:.1f} {unit}" if unit != "B" else f"{int(v)} B"
        v /= 1024
    return f"{v:.1f} TB"
