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

        for bt in ("db", "minio", "data", "vault"):
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
            backup_note = f"최근 백업 {backup_age_h}시간 전 · 영구 저장"
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

    # ── 6) 실시간 활동 로그 ────────────────────────────────────────────────
    # 여러 테이블의 최신 기록을 '실제 내용'으로 통합 — 무엇이 어디에 어떤 내용으로
    # 저장·학습·해결되는지 운영 콘솔 맨 아래 실시간 로그에 표시한다. 테이블별 try 격리.
    recent_activity: list[dict[str, Any]] = []

    def _clip(s: Any, n: int) -> str:
        t = "" if s is None else " ".join(str(s).split())  # 개행·연속공백 정리
        return (t[: n - 1] + "…") if len(t) > n else t

    def _push(ts: Any, icon: str, kind: str, where: str, title: str, detail: str) -> None:
        if ts is None:
            return
        recent_activity.append(
            {
                "ts": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                "icon": icon,
                "kind": kind,
                "where": where,
                "title": _clip(title, 80),
                "detail": _clip(detail, 160),
            }
        )

    _PER = 12  # 테이블당 최신 N (내용 보강 — 더 풍부한 피드)
    _OL = {
        "OUT-01": "PPT",
        "OUT-02": "PDF 보고서",
        "OUT-03": "발표 대본",
        "OUT-04": "HTML 대시보드",
        "OUT-07": "인사이트 요약",
    }
    # HJ 2026-06-19 — '실시간 활동 로그' 비어 보임 수정 + '무엇이 어디에 어떻게 저장되는지' 전면 노출.
    #   기존 8개 소스(Q&A·자동수정·오류·KB·산출물·백업·감사)는 모두 이벤트성이라 분석이 돌아도 거의 안 쌓임.
    #   정작 분석 중 실제로 쓰이는 jobs/agent_runs/models/experiments/artifacts 가 피드에 없었다.
    #   → 분석 활동(작업·에이전트 실행·모델·실험·아티팩트)을 추가하고, where 에 저장 위치
    #     (PostgreSQL·테이블 / MinIO·경로 / MLflow)를 명시한다. 소스별 try 격리로 한 테이블 실패가
    #     전체 피드를 비우지 않게 한다(기존 단일 try 는 한 곳만 어긋나도 통째로 빈 배열이 됐다).
    try:
        from ada.db.models import (
            AgentRun as _AR,
            Artifact as _ART,
            BackupCatalog as _BC,
            ConversationLog as _CL,
            ErrorKB as _EK,
            Experiment as _EXP,
            FailureLog as _FL,
            Job as _J,
            Model as _M,
            Output as _OUT,
            PatchApplication as _PA,
            SecurityAuditLog as _SA,
            SelfLearningKB as _KB,
        )
    except Exception:  # noqa: BLE001
        _AR = _ART = _BC = _CL = _EK = _EXP = _FL = _J = _M = _OUT = _PA = _SA = _KB = None

    def _tail(s: Any, n: int = 56) -> str:
        t = "" if s is None else str(s)
        return ("…" + t[-(n - 1) :]) if len(t) > n else t

    # ── KB 학습: kb_type 한글 라벨 + payload 에서 '실제 학습 내용' 한 줄 추출 ──
    _KB_LABEL = {
        "qa_pair": "Q&A 학습",
        "success_pattern": "성공 패턴",
        "recipe": "재사용 레시피",
        "hpo_warm_start": "HPO 시드",
        "eda_template": "EDA 템플릿",
        "failure_lesson": "실패 교훈",
    }

    def _kb_detail(kb_type: str, payload: Any) -> str:
        """self_learning_kb payload 에서 사람이 읽을 '실제 학습 내용' 한 줄."""
        p = payload if isinstance(payload, dict) else {}
        t = kb_type or ""
        if t == "qa_pair":
            return f"Q: {_clip(p.get('question'), 70)}  →  A: {_clip(p.get('answer'), 95)}"
        if t == "success_pattern":
            return (
                f"{p.get('category') or '?'} / 타깃 {p.get('target') or '-'} / 의도: {_clip(p.get('user_intent'), 80)}"
            )
        if t == "recipe":
            m = p.get("metric") if isinstance(p.get("metric"), dict) else {}
            mtxt = f"{m.get('name', '')} {m.get('value', '')}".strip()
            base = f"{p.get('category') or '?'} → {p.get('best_model') or '?'}({p.get('framework') or '-'})"
            return base + (f" · {mtxt}" if mtxt else "")
        if t == "hpo_warm_start":
            bp = p.get("best_params") if isinstance(p.get("best_params"), dict) else {}
            keys = ", ".join(list(bp)[:6])
            return f"{p.get('model') or '?'} 하이퍼파라미터" + (f": {keys}" if keys else "")
        if t == "eda_template":
            return f"{p.get('category') or '?'} · {p.get('n_rows') or '?'}행 × {p.get('n_cols') or '?'}컬럼 EDA 절차"
        if t == "failure_lesson":
            return f"{p.get('category') or '?'} 실패 → {_clip(p.get('error'), 100)}"
        return _clip(", ".join(f"{k}={v}" for k, v in list(p.items())[:4]), 120) if p else "-"

    def _build_kb(r: Any) -> tuple:
        label = _KB_LABEL.get(r.kb_type, r.kb_type or "?")
        cat = f" · {r.category}" if r.category else ""
        conf = f" · 신뢰도 {r.confidence:.2f}" if r.confidence is not None else ""
        reuse = f" · 재사용 {r.success_count}회" if (r.success_count or 0) > 1 else ""
        return (
            r.created_at,
            "🧠",
            "KB 학습",
            "PostgreSQL · self_learning_kb",
            f"{label}{cat}{conf}{reuse}",
            _kb_detail(r.kb_type, r.payload),
        )

    _BK_WHAT = {
        "db": "PostgreSQL 전체 DB 덤프(pg_dump · 모든 테이블)",
        "minio": "MinIO 오브젝트(업로드 데이터셋·산출물·모델)",
        "data": "데이터셋 파일",
        "vault": "Vault 시크릿",
    }

    def _build_bk(r: Any) -> tuple:
        bt = r.backup_type or "?"
        return (
            r.created_at,
            "💾",
            "백업",
            "로컬 · " + _tail(r.minio_path, 48),
            f"{_BK_WHAT.get(bt, bt)} · {r.status or 'ok'}",
            f"{_fmt_bytes(r.size_bytes)} · {r.note or ''}",
        )

    async def _src(model: Any, order_col: Any, build: Any) -> None:
        # 소스 1개 — 쿼리/행 변환 실패가 전체 피드를 비우지 않도록 개별 격리.
        if model is None:
            return
        try:
            rows = list((await db.scalars(select(model).order_by(desc(order_col)).limit(_PER))).all())
        except Exception:  # noqa: BLE001
            return
        for r in rows:
            try:
                args = build(r)
                if args:
                    _push(*args)
            except Exception:  # noqa: BLE001
                continue

    # ── 분석 활동 (가장 빈번): 작업 진행 + 에이전트 실행 ─────────────────────
    await _src(
        _J,
        _J.updated_at if _J is not None else None,
        lambda r: (
            r.updated_at or r.created_at,
            "🚀",
            "분석 작업",
            "PostgreSQL · jobs",
            f"{r.category or '?'} · {r.status or 'pending'}",
            f"게이트 {r.current_gate or 'G1'} · 타깃 {r.target_column or '-'} · 재시도 {r.retry_count or 0}",
        ),
    )
    await _src(
        _AR,
        _AR.created_at if _AR is not None else None,
        lambda r: (
            r.created_at,
            "⚙️",
            "에이전트 실행",
            "PostgreSQL · agent_runs",
            f"{r.agent_name} · {r.status}",
            f"게이트 {r.gate or '-'} · {r.duration_ms or 0}ms · 토큰 in{r.input_tokens or 0}/out{r.output_tokens or 0}"
            + (f" · 오류 {_clip(r.error, 50)}" if r.error else ""),
        ),
    )
    # ── Q&A / 자동수정 / 오류 / KB (이벤트성) ───────────────────────────────
    await _src(
        _CL,
        _CL.created_at if _CL is not None else None,
        lambda r: (
            r.created_at,
            "💬",
            "Q&A 저장",
            "PostgreSQL · conversation_logs",
            f"{r.team_member or '?'} · {r.source or 'claude_code'}",
            f"Q: {_clip(r.question, 70)}  →  A: {_clip(r.answer, 90)}",
        ),
    )
    await _src(
        _PA,
        _PA.applied_at if _PA is not None else None,
        lambda r: (
            r.applied_at,
            "🔧",
            "자동수정",
            "PostgreSQL · patch_applications",
            f"{r.applied_by or 'auto-fix-bot'} · {r.status or '?'}",
            f"commit {(r.git_commit_sha or '-')[:8]} · {r.duration_ms or 0}ms",
        ),
    )
    await _src(
        _FL,
        _FL.created_at if _FL is not None else None,
        lambda r: (
            r.created_at,
            "⚠️",
            "오류 캐치",
            "PostgreSQL · failure_logs",
            f"{r.error_category or '미분류'} · {r.classified_as or '대기'}",
            r.error_message or "",
        ),
    )
    await _src(_KB, _KB.created_at if _KB is not None else None, _build_kb)
    await _src(
        _EK,
        _EK.created_at if _EK is not None else None,
        lambda r: (
            r.created_at,
            "📚",
            "오류 KB",
            "PostgreSQL · error_kb",
            r.error_signature or "(서명 없음)",
            f"해결: {_clip(r.resolution, 110)}",
        ),
    )
    # ── 파일/모델 실제 저장 위치 (MinIO 경로 노출) ─────────────────────────
    await _src(
        _OUT,
        _OUT.created_at if _OUT is not None else None,
        lambda r: (
            r.created_at,
            "📦",
            "산출물 저장",
            "MinIO · " + _tail(r.minio_path),
            f"{_OL.get(r.output_code, r.output_code)} · {r.status or 'completed'}",
            f"{_fmt_bytes(r.file_size_bytes)} · {r.generation_ms or 0}ms",
        ),
    )
    await _src(
        _M,
        _M.created_at if _M is not None else None,
        lambda r: (
            r.created_at,
            "🤖",
            "모델 저장",
            "MinIO · " + _tail(r.minio_path),
            f"{r.model_name} · {r.framework}" + (" · best" if r.is_best else ""),
            f"mlflow {(r.mlflow_run_id or '-')[:8]} · sha {(r.model_sha256 or '-')[:8]}",
        ),
    )
    await _src(
        _ART,
        _ART.created_at if _ART is not None else None,
        lambda r: (
            r.created_at,
            "🗂️",
            "아티팩트 저장",
            "MinIO · " + _tail(r.minio_path),
            f"{r.artifact_type}",
            _tail(r.minio_path, 80),
        ),
    )
    await _src(
        _EXP,
        _EXP.created_at if _EXP is not None else None,
        lambda r: (
            r.created_at,
            "🧪",
            "실험 기록",
            "MLflow · experiments",
            f"{r.category or '?'} · {r.status or 'created'}",
            f"mlflow_exp {r.mlflow_experiment_id or '-'}",
        ),
    )
    await _src(_BC, _BC.created_at if _BC is not None else None, _build_bk)
    await _src(
        _SA,
        _SA.created_at if _SA is not None else None,
        lambda r: (
            r.created_at,
            "🔐",
            "보안 감사",
            "PostgreSQL · security_audit_log",
            f"{r.event_type or '?'} · {r.action or '-'}",
            f"{r.actor_role or '-'} · {r.result or '-'}",
        ),
    )

    # 최신순 정렬 후 상위 40개 (프론트는 10줄 표시 + 자체 스크롤로 나머지 열람)
    recent_activity.sort(key=lambda x: x["ts"], reverse=True)
    recent_activity = recent_activity[:60]

    # ── 7) 시간에 따른 학습 효과 (얼마나 좋아지고 있나, %) ─────────────────────
    #   실제 영속 테이블만 사용: models.metrics(성능) / failure_logs.auto_handled_by_kb(KB 즉시해결=
    #   외부 LLM·Claude 불필요) / patch_applications.status(자동수정) . 윈도별 값 + 최초 대비 Δ%.
    learning_trend: dict[str, Any] = {"windows": ["전체", "1년", "6개월", "1개월", "이번주"], "metrics": [], "note": ""}
    try:
        _aware = lambda t: t.replace(tzinfo=timezone.utc) if t is not None and t.tzinfo is None else t  # noqa: E731
        _wn = datetime.now(timezone.utc)
        _WIN = [("all", None), ("year", 365), ("half", 180), ("month", 30), ("week", 7)]

        def _cutoff(days: Optional[int]) -> Optional[datetime]:
            return None if days is None else _wn - timedelta(days=days)

        def _avg_by_window(rows: list[tuple]) -> dict[str, Optional[float]]:
            """rows=[(ts,val)] → 윈도별 평균(비율 metric 은 val 을 0/1 로 넣으면 비율)."""
            acc: dict[str, list[float]] = {k: [] for k, _ in _WIN}
            t0 = None
            for ts, val in rows:
                ts = _aware(ts)
                if ts is None or val is None:
                    continue
                if t0 is None or ts < t0:
                    t0 = ts
                for k, days in _WIN:
                    c = _cutoff(days)
                    if c is None or ts >= c:
                        acc[k].append(float(val))
            res: dict[str, Optional[float]] = {}
            for k, _ in _WIN:
                res[k] = (sum(acc[k]) / len(acc[k])) if acc[k] else None
            # 최초 30일 평균(first) — Δ% 기준선
            first_vals = [
                float(v) for ts, v in rows if v is not None and t0 is not None and _aware(ts) <= t0 + timedelta(days=30)
            ]
            res["_first"] = (sum(first_vals) / len(first_vals)) if first_vals else None
            return res

        def _delta(cur: Optional[float], first: Optional[float]) -> Optional[float]:
            if cur is None or first is None or first == 0:
                return None
            return round((cur - first) / abs(first) * 100, 1)

        def _primary_metric_val(m: Any) -> Optional[float]:
            if not isinstance(m, dict):
                return None
            for k in ("val_f1", "val_accuracy", "val_roc_auc", "val_r2", "f1", "accuracy", "roc_auc", "r2"):
                if isinstance(m.get(k), (int, float)):
                    return float(m[k])
            return None

        # (1) 모델 평균 성능 — best 모델 primary metric
        try:
            from ada.db.models import Model as _MM

            mrows = list(
                (
                    await db.scalars(
                        select(_MM).where(_MM.is_best.is_(True)).order_by(desc(_MM.created_at)).limit(3000)
                    )
                ).all()
            )
            mv = _avg_by_window([(r.created_at, _primary_metric_val(r.metrics)) for r in mrows])
            learning_trend["metrics"].append(
                {
                    "label": "🤖 모델 평균 성능",
                    "icon": "🤖",
                    "fmt": "ratio",
                    "better": "up",
                    "vals": {k: mv[k] for k, _ in _WIN},
                    "delta": _delta(mv["week"] or mv["month"], mv["_first"]),
                }
            )
        except Exception:  # noqa: BLE001
            pass

        # (2) 오류 자동수정 성공률 — patch_applications status='success' 비율
        try:
            from ada.db.models import PatchApplication as _PP

            prows = list((await db.scalars(select(_PP).order_by(desc(_PP.applied_at)).limit(10000))).all())
            pv = _avg_by_window([(r.applied_at, 1.0 if (r.status == "success") else 0.0) for r in prows])
            learning_trend["metrics"].append(
                {
                    "label": "🔧 오류 자동수정 성공률",
                    "icon": "🔧",
                    "fmt": "pct",
                    "better": "up",
                    "vals": {k: (pv[k] * 100 if pv[k] is not None else None) for k, _ in _WIN},
                    "delta": _delta(pv["week"] or pv["month"], pv["_first"]),
                }
            )
        except Exception:  # noqa: BLE001
            pass

        # (3) KB 즉시해결률(학습으로 LLM 없이 해결) & (4) Claude·외부LLM 의존률(=1-그것)
        try:
            from ada.db.models import FailureLog as _FF

            frows = list((await db.scalars(select(_FF).order_by(desc(_FF.created_at)).limit(20000))).all())
            kv = _avg_by_window([(r.created_at, 1.0 if r.auto_handled_by_kb else 0.0) for r in frows])
            learning_trend["metrics"].append(
                {
                    "label": "🧠 KB 즉시해결률 (학습 자동해결)",
                    "icon": "🧠",
                    "fmt": "pct",
                    "better": "up",
                    "vals": {k: (kv[k] * 100 if kv[k] is not None else None) for k, _ in _WIN},
                    "delta": _delta(kv["week"] or kv["month"], kv["_first"]),
                }
            )
            # Claude·외부 LLM 의존률 = 100 - KB즉시해결률 (낮아질수록 좋음)
            dep = {k: (100 - kv[k] * 100 if kv[k] is not None else None) for k, _ in _WIN}
            dep_first = (100 - kv["_first"] * 100) if kv["_first"] is not None else None
            dep_cur = dep["week"] if dep["week"] is not None else dep["month"]
            learning_trend["metrics"].append(
                {
                    "label": "☁️ Claude·외부 LLM 의존률",
                    "icon": "☁️",
                    "fmt": "pct",
                    "better": "down",
                    "vals": dep,
                    "delta": _delta(dep_cur, dep_first),
                }
            )
        except Exception:  # noqa: BLE001
            pass

        learning_trend["note"] = (
            "모델 성능은 best 모델의 대표 지표 평균, 자동수정률은 패치 성공 비율, KB 즉시해결률은 학습된 지식으로 "
            "LLM 없이 즉시 해결한 비율입니다. Claude 의존률은 그 보수값(학습이 쌓일수록 낮아지면 좋음). "
            "Δ% 는 '최초 30일' 대비 현재. 데이터가 짧으면 일부 구간은 '—'(축적 중)으로 표시됩니다."
        )
    except Exception:  # noqa: BLE001
        learning_trend = {"windows": [], "metrics": [], "note": "집계 실패"}

    # ── 8) API 운영 비용 (분석 단계별 LLM 추정비용 + 인프라 고정비) ───────────
    #   ⚠️ LLM 비용 = agent_runs 토큰 × 단가(추정). Ollama(1~3단계)=로컬·무료. 4~6단계=Claude(유료).
    #   ⚠️ 인프라 고정비(VPS 등)는 데이터로 알 수 없어 '설정값' — 아래 _INFRA_MONTHLY_USD 에 실제 금액 입력.
    cost_overview: dict[str, Any] = {}
    try:
        from sqlalchemy import text as _sqltext

        # 분석 단계(1~7) ↔ 에이전트 매핑 + 백엔드(1~3 Ollama 무료 / 4~6 Claude 유료)
        _STAGE = [
            (1, "데이터 파악", "Ollama", ["data_profiler", "schema_validator", "intent_elicitor"]),
            (2, "분석 방향", "Ollama", ["eda_agent"]),
            (3, "전처리·피처", "Ollama", ["preprocessing_strategist", "feature_engineer"]),
            (
                4,
                "모델 학습",
                "Claude",
                [
                    "model_selection",
                    "hyperparameter_tuner",
                    "training_executor",
                    "training_monitor",
                    "metrics_aggregator",
                ],
            ),
            (5, "평가·인사이트", "Claude", ["fine_tune_executor", "eval_agent", "explainability", "insight"]),
            (6, "리포트·산출물", "Claude", ["report_composer"]),
            (7, "학습·저장", "Ollama", ["self_learning", "supervisor", "security_guard"]),
        ]
        _agent_stage = {a: (sn, lbl, be) for sn, lbl, be, agents in _STAGE for a in agents}
        # Claude 분석 단가(설정값) — 4~6단계 추정. 기본 sonnet 급(1K 토큰당 USD). 실제 모델에 맞게 조정 가능.
        _CLAUDE_RATE = {"input": 0.003, "output": 0.015}

        # 인프라 고정비(월, USD) — ⚠️ 실제 금액으로 수정(기본 0 = 미입력, 허수 표시 안 함)
        _INFRA_MONTHLY_USD = [
            {"name": "VPS 서버(호스팅)", "usd": 0.0},
            {"name": "도메인", "usd": 0.0},
            {"name": "스토리지·백업·기타", "usd": 0.0},
        ]

        async def _tokens_since(days: Optional[int]) -> dict[str, tuple]:
            """agent_name → (sum_in, sum_out), 최근 days 일(None=전체)."""
            where = "" if days is None else "WHERE created_at >= now() - (:d || ' days')::interval"
            sql = f"SELECT agent_name, COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0) FROM agent_runs {where} GROUP BY agent_name"
            params = {} if days is None else {"d": str(days)}
            try:
                res = await db.execute(_sqltext(sql), params)
                return {row[0]: (int(row[1] or 0), int(row[2] or 0)) for row in res}
            except Exception:  # noqa: BLE001
                return {}

        def _stage_costs(tok: dict[str, tuple]) -> tuple:
            """토큰맵 → 단계별 비용/토큰 + LLM 합계 USD."""
            per = {
                sn: {"stage": sn, "label": lbl, "backend": be, "in": 0, "out": 0, "usd": 0.0}
                for sn, lbl, be, _ in _STAGE
            }
            total = 0.0
            for agent, (ti, to) in tok.items():
                st = _agent_stage.get(agent)
                if not st:
                    continue
                sn, lbl, be = st
                per[sn]["in"] += ti
                per[sn]["out"] += to
                usd = (
                    ((ti / 1000.0) * _CLAUDE_RATE["input"] + (to / 1000.0) * _CLAUDE_RATE["output"])
                    if be == "Claude"
                    else 0.0
                )
                per[sn]["usd"] += usd
                total += usd
            return list(per.values()), round(total, 4)

        _WINS_COST = {"day": 1, "week": 7, "month": 30, "total": None}
        llm_by_win: dict[str, float] = {}
        stages_total: list = []
        for wk, wd in _WINS_COST.items():
            tok = await _tokens_since(wd)
            stages, llm_usd = _stage_costs(tok)
            llm_by_win[wk] = llm_usd
            if wk == "total":
                stages_total = stages

        # 인프라 비용: 월 합 → 일/주 환산, 총액 = 월합 × (서비스 가동개월). 가동개월은 최초 job 기준.
        infra_month = round(sum(x["usd"] for x in _INFRA_MONTHLY_USD), 2)
        try:
            _first_job = await db.scalar(_sqltext("SELECT MIN(created_at) FROM jobs"))
            _elapsed_days = (
                max(1.0, (datetime.now(timezone.utc) - _aware(_first_job)).total_seconds() / 86400.0)
                if _first_job
                else 30.0
            )
        except Exception:  # noqa: BLE001
            _elapsed_days = 30.0
        infra_by_win = {
            "day": round(infra_month / 30.0, 2),
            "week": round(infra_month / 30.0 * 7, 2),
            "month": round(infra_month, 2),
            "total": round(infra_month / 30.0 * _elapsed_days, 2),
        }
        # 자동수정 Claude 비용(Redis budget, 최근만) — 오늘 스냅샷
        autofix_today = None
        try:
            import redis as _rd

            _rc = _rd.from_url(settings.redis_url, decode_responses=True)
            _dk = datetime.utcnow().strftime("%Y-%m-%d")
            _sp = _rc.get(f"ada:budget:spend:{_dk}")
            autofix_today = round(float(_sp), 4) if _sp else 0.0
        except Exception:  # noqa: BLE001
            autofix_today = None

        cost_overview = {
            "stages": stages_total,
            "llm": llm_by_win,
            "infra_items": _INFRA_MONTHLY_USD,
            "infra": infra_by_win,
            "autofix_today_usd": autofix_today,
            "elapsed_days": round(_elapsed_days, 1),
            "totals": {wk: round(llm_by_win.get(wk, 0.0) + infra_by_win.get(wk, 0.0), 2) for wk in _WINS_COST},
            "note": (
                "LLM 비용은 agent_runs 토큰×단가 추정입니다. 1~3·7단계는 Ollama(로컬·무료), 4~6단계는 Claude(유료). "
                "인프라 고정비(VPS 등)는 데이터로 알 수 없어 '설정값'이며, 현재 0(미입력)입니다 — 실제 금액 입력 시 합산됩니다."
            ),
        }
    except Exception:  # noqa: BLE001
        cost_overview = {"stages": [], "llm": {}, "infra": {}, "totals": {}, "note": "집계 실패"}

    out.update(
        {
            "services": services,
            "recent_activity": recent_activity,
            "learning_trend": learning_trend,
            "cost_overview": cost_overview,
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
                "method": "Pull (로컬 서버 → VPS) · DB pg_dump + MinIO mc mirror(증분)",
                "retention": "영구 저장",
                "paths": [
                    "/srv/backup/ada/postgres",
                    "/srv/backup/ada/minio",
                    "/srv/backup/ada/datasets",
                ],
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
