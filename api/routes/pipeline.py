"""api.routes.pipeline — 파이프라인 라우터 (Day06).

POST /pipeline/start         → 새 job 시작
GET  /pipeline/status/{job}  → 진행 상황
POST /pipeline/resume/{job}  → 5게이트 응답 후 재개
GET  /pipeline/result/{job}  → 최종 결과
GET  /pipeline/gate/{job}    → 현재 게이트 proposals + 실시간 진행률
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ada.core.config import settings
from ada.core.logger import get_logger
from ada.core.state import PipelineState
from ada.db.models import Job, Output, Upload
from ada.db.session import get_db
from api.schemas.pipeline import (
    OutputItem,
    PipelineResultResponse,
    PipelineResumeRequest,
    PipelineStartRequest,
    PipelineStartResponse,
    PipelineStatusResponse,
)

log = get_logger("api.pipeline")


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------
def _key_from_minio_path(minio_path: str, bucket: str) -> str:
    """``s3://{bucket}/{key}`` → ``{key}``  (그 외 형식은 그대로 통과)."""
    if minio_path.startswith("s3://"):
        rest = minio_path[len("s3://") :]
        if rest.startswith(f"{bucket}/"):
            return rest[len(bucket) + 1 :]
        return rest.split("/", 1)[1] if "/" in rest else rest
    return minio_path


router = APIRouter()


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------
@router.post("/start", response_model=PipelineStartResponse)
async def start_pipeline(req: PipelineStartRequest, db: AsyncSession = Depends(get_db)) -> PipelineStartResponse:
    upload = await db.scalar(select(Upload).where(Upload.file_id == req.file_id))
    if upload is None:
        raise HTTPException(404, detail="file_id not found")

    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        file_id=req.file_id,
        category=req.category or "pending",
        target_column=req.target_column,
        user_question=req.user_question,
        user_intent=req.user_intent,
        requested_outputs=req.requested_outputs,
        status="pending",
    )
    db.add(job)
    await db.flush()

    from orchestrator.runner import run_pipeline_task

    state = PipelineState(
        job_id=str(job_id),
        file_id=req.file_id,
        category=req.category or "pending",
        target_column=req.target_column,
        user_question=req.user_question,
        user_intent=req.user_intent,
        requested_outputs=list(req.requested_outputs),
        max_retries=req.max_retries,
    )
    run_pipeline_task.apply_async(args=[str(job_id), state.to_dict()], queue="pipeline")

    return PipelineStartResponse(
        job_id=str(job_id),
        status="pending",
        created_at=job.created_at or datetime.utcnow(),
        estimated_duration_min=10,
    )


@router.get("/status/{job_id}", response_model=PipelineStatusResponse)
async def status(job_id: str, db: AsyncSession = Depends(get_db)) -> PipelineStatusResponse:
    import json as _json

    job = await db.scalar(select(Job).where(Job.id == uuid.UUID(job_id)))
    if job is None:
        raise HTTPException(404, detail="job not found")

    effective_status = job.status
    effective_current_gate = job.current_gate

    # Redis gate_data 로 보정: 활성 게이트가 있으면 DB "completed" 를 "running" 으로 재정의.
    # 에러 복구 후 재시작 시 gate 재통과 과정에서 current_gate=None 이 되어 DB 가 completed 로
    # 잘못 표기되는 경우를 방어한다.
    try:
        import redis as _redis

        _r = _redis.from_url(settings.redis_url, decode_responses=True)
        _raw = _r.get(f"ada:gate_data:{job_id}")
        if _raw:
            _gd = _json.loads(_raw)
            _active_gate = _gd.get("gate")
            if _active_gate and _gd.get("proposals"):
                effective_current_gate = _active_gate
                if effective_status in ("completed", "pending"):
                    effective_status = "running"
    except Exception:
        pass

    prog = 100 if effective_status == "completed" else (50 if effective_status == "running" else 0)
    return PipelineStatusResponse(
        job_id=str(job.id),
        status=effective_status,
        category=job.category,
        target_column=job.target_column,
        current_agent=None,
        current_gate=effective_current_gate,
        progress_pct=prog,
        error=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
        requested_outputs=job.requested_outputs or [],
    )


@router.post("/resume/{job_id}")
async def resume(job_id: str, req: PipelineResumeRequest, db: AsyncSession = Depends(get_db)) -> dict:
    job = await db.scalar(select(Job).where(Job.id == uuid.UUID(job_id)))
    if job is None:
        raise HTTPException(404, detail="job not found")
    from orchestrator.runner import resume_pipeline_task

    resume_pipeline_task.apply_async(
        args=[job_id, {"gate": req.gate, "choice": req.choice}],
        queue="pipeline",
    )
    return {"job_id": job_id, "gate": req.gate, "queued": True}


@router.get("/result/{job_id}", response_model=PipelineResultResponse)
async def result(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    expiry: int = 3600,
) -> PipelineResultResponse:
    """파이프라인 결과 — Output 테이블 + MinIO presigned URL."""
    job = await db.scalar(select(Job).where(Job.id == uuid.UUID(job_id)))
    if job is None:
        raise HTTPException(404, detail="job not found")

    rows = (
        await db.scalars(select(Output).where(Output.job_id == uuid.UUID(job_id)).order_by(Output.created_at.asc()))
    ).all()

    items: list[OutputItem] = []

    mc = None
    if rows:
        try:
            from tools.minio_tool import get_minio_client

            mc = get_minio_client()
        except Exception as e:
            log.warning("minio_client_unavailable", error=str(e))

    for row in rows:
        key = _key_from_minio_path(row.minio_path, settings.minio_bucket)
        filename = Path(key).name or "(unnamed)"
        url: str | None = None
        if mc is not None:
            try:
                url = mc.get_presigned_url(key, expiry=expiry)
            except Exception as e:
                log.warning(
                    "presigned_url_failed",
                    output_code=row.output_code,
                    minio_path=row.minio_path,
                    error=str(e),
                )

        items.append(
            OutputItem(
                code=row.output_code,
                filename=filename,
                minio_path=row.minio_path,
                size_bytes=row.file_size_bytes,
                generation_ms=row.generation_ms,
                status=row.status or "completed",
                url=url,
                url_expires_in=expiry,
            )
        )

    return PipelineResultResponse(
        job_id=str(job.id),
        status=job.status,
        outputs=items,
        requested_outputs=list(job.requested_outputs or []),
    )


@router.get("/gate/{job_id}")
async def gate_detail(job_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """현재 게이트 proposals + 실시간 진행률/에이전트.

    runner._save_gate_data() 가 Redis 에 저장한 ada:gate_data:{job_id} 를 직접 읽어
    graph.get_state() 와 워커 전용 패키지(matplotlib 등) 없이 동작한다.
    """
    job = await db.scalar(select(Job).where(Job.id == uuid.UUID(job_id)))
    if job is None:
        raise HTTPException(404, detail="job not found")

    data: dict = {
        "gate": job.current_gate,
        "category": job.category,
        "target_column": job.target_column,
        "proposals": [],
        "user_choice": None,
        "insights": None,
        "eval_result": None,
        "best_model": None,
        "eda_summary": None,
        "output_paths": {},
        "requested_outputs": [],
    }

    try:
        import json as _json2

        import redis as _redis2

        from ada.core.config import settings as _s2

        _rc2 = _redis2.Redis.from_url(_s2.redis_url)
        _raw_gate = _rc2.get(f"ada:gate_data:{job_id}")
        if _raw_gate:
            _gd = _json2.loads(_raw_gate)
            data["gate"] = _gd.get("gate") or job.current_gate
            data["proposals"] = _gd.get("proposals") or []
            # 직전 단계 결과 필드 전부를 게이트 화면에 노출 (eda_summary/eval_result 추가)
            # HJ 2026-06-09 G1 단축 Z' — g2_pending 추가 (gate_direction 진행 중 신호)
            for k in (
                "category",
                "target_column",
                "insights",
                "data_profile",
                "requested_outputs",
                "best_model",
                "pipeline_status",
                "eda_summary",
                "eval_result",
                "g2_pending",
                "topic_proposals",  # CS 2026-06-10 — G2 Sub-1 주제 후보 forward
            ):
                v = _gd.get(k)
                if v is not None:
                    data[k] = v
            # output_paths: gate_data 값이 있으면 DB 값을 덮어씀 (완료 후 저장된 게 정확)
            if _gd.get("output_paths"):
                data["output_paths"] = {**(data.get("output_paths") or {}), **_gd["output_paths"]}
    except Exception:  # noqa: BLE001
        pass

    # CS 2026-06-11 — category 누락/pending 보정.
    # data_profiler 완료 전에 _save_g2_screen_ready 가 실행되면 Redis 에 category="pending"
    # 또는 None 이 저장될 수 있고, 그 결과 frontend gateHeader 가 _default 로 떨어진다.
    # data_profile 기반 휴리스틱으로 4 카테고리 중 하나를 강제 보장 → 어떤 데이터든 정상 표시.
    if not data.get("category") or data.get("category") == "pending":
        _dp = data.get("data_profile") or {}
        _date_col = _dp.get("date_col") or _dp.get("detected_time_col")
        _has_target = bool(data.get("target_column") or _dp.get("has_target") or _dp.get("detected_target"))
        _rows = int(_dp.get("rows") or (_dp.get("shape") or {}).get("rows") or 0)
        _cols = int(_dp.get("cols") or (_dp.get("shape") or {}).get("cols") or 0)
        if _date_col:
            data["category"] = "timeseries"
        elif not _has_target and _rows >= 500:
            data["category"] = "anomaly_detection"
        elif _rows >= 50_000 and _cols >= 20:
            data["category"] = "tabular_dl"
        else:
            data["category"] = "tabular_ml"

    try:
        rows = (await db.scalars(select(Output).where(Output.job_id == job.id))).all()
        if rows:
            data["output_paths"] = {o.output_code: o.minio_path for o in rows}
    except Exception:  # noqa: BLE001
        pass

    try:
        import json as _json

        import redis as _redis

        from ada.core.config import settings as _settings

        rc = _redis.Redis.from_url(_settings.redis_url)
        raw = rc.get(f"ada:progress:{job_id}")
        if raw:
            pr = _json.loads(raw)
            data["current_agent"] = pr.get("agent")
            data["progress_pct"] = pr.get("progress")
            data["progress_ts"] = pr.get("ts")
            # 단계 baseline ETA — orchestrator.runner.publish_progress 가 단계 시작 시점에 publish.
            # 프론트 _stageEta 가 이 값을 우선 사용하여 첫 1초부터 합리적 ETA 표시.
            if pr.get("eta_sec") is not None:
                data["eta_sec"] = pr.get("eta_sec")
            if pr.get("eta_base_ts") is not None:
                data["eta_base_ts"] = pr.get("eta_base_ts")
            if pr.get("status"):
                data["pipeline_status"] = pr.get("status")
            if pr.get("error"):
                data["pipeline_error"] = pr.get("error")
        # HJ 2026-06-09 G1 단축 γ — partial domain 정보 (G1 진행 화면 점진 표시).
        # data_profiler 의 도메인 streaming 콜백이 ada:domain_partial:{job_id} 에 저장.
        try:
            raw_partial = rc.get(f"ada:domain_partial:{job_id}")
            if raw_partial:
                data["domain_partial"] = _json.loads(raw_partial)
        except Exception:  # noqa: BLE001
            pass
        # HJ 2026-06-10 — stage 2~6 의 long-phase agent 가 publish 한 인크리멘털 상태.
        # eda_agent / methodology_proposer / ... 의 _emit 가 ada:stage_partial:{job_id} 에 누적.
        try:
            raw_sp = rc.get(f"ada:stage_partial:{job_id}")
            if raw_sp:
                data["stage_partial"] = _json.loads(raw_sp)
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        pass

    if job.status in ("failed", "completed") and not data.get("pipeline_status"):
        data["pipeline_status"] = job.status
        if job.status == "failed" and job.error_message:
            data["pipeline_error"] = job.error_message

    return data


# ---------------------------------------------------------------------------
# 산출물 다운로드 프록시 — MinIO 내부 주소를 API 가 중계
# ---------------------------------------------------------------------------
_DL_META: dict[str, tuple[str, str]] = {
    "OUT-01": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", "presentation.pptx"),
    "OUT-02": ("application/pdf", "report.pdf"),
    "OUT-03": ("text/plain; charset=utf-8", "script.txt"),
    "OUT-04": ("text/html; charset=utf-8", "dashboard.html"),
    "OUT-07": ("text/markdown; charset=utf-8", "insight.md"),
}


@router.get("/download/{job_id}/{output_code}")
async def download_output(job_id: str, output_code: str) -> None:
    """MinIO 에 저장된 산출물을 스트리밍 다운로드 (브라우저 직접 요청용)."""
    import io as _io
    import json as _json

    import redis as _redis
    from fastapi.responses import StreamingResponse

    from ada.core.config import settings as _s
    from tools.minio_tool import get_minio_client

    # Redis gate_data 에서 output_paths 읽기
    try:
        _r = _redis.from_url(_s.redis_url, decode_responses=True)
        _raw = _r.get(f"ada:gate_data:{job_id}")
        if not _raw:
            raise HTTPException(404, "결과를 찾을 수 없습니다.")
        _gd = _json.loads(_raw)
        _output_paths: dict = _gd.get("output_paths") or {}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "Redis 조회 실패")

    minio_path = _output_paths.get(output_code)
    if not minio_path:
        raise HTTPException(404, f"{output_code} 파일이 생성되지 않았습니다.")

    try:
        mc = get_minio_client()
        key = minio_path.replace(f"s3://{mc.bucket}/", "") if minio_path.startswith("s3://") else minio_path
        body = mc.download_bytes(key)
    except Exception as e:
        raise HTTPException(500, f"파일 다운로드 실패: {e}")

    ct, fname = _DL_META.get(output_code, ("application/octet-stream", "output.bin"))
    return StreamingResponse(
        _io.BytesIO(body),
        media_type=ct,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ---------------------------------------------------------------------------
# CS 2026-06-10 — G2 Sub-1 주제 선정 후 분석 방향 LLM 재호출
# ---------------------------------------------------------------------------
@router.post("/gate/G2/directions/{job_id}")
async def propose_directions_for_topic(job_id: str, req: dict) -> dict:
    """G2 Sub-1 주제 선택 후 분석 방향 LLM 호출.

    Body: {"topic": "선택된 주제 텍스트"}
    Response: {"proposals": [{id,title,rationale,...}], "topic": "..."}

    동작:
      1) Redis full_state 로드 → PipelineState 복원
      2) AnalysisProposerAgent.propose_directions_with_topic(state, topic) 호출
      3) Redis ada:gate_data 의 proposals 갱신 + g2_pending=False
      4) Redis ada:full_state 의 gate_responses[G2] 갱신 (proposals + topic)
      5) graph.aupdate_state 호출 → LangGraph checkpointer 도 동기화 (결함 1)
      6) 응답 반환
    """
    import json as _json

    import redis as _redis

    from ada.core.state import PipelineState
    from agents.gates.analysis_proposer import AnalysisProposerAgent

    topic = ((req or {}).get("topic") or "").strip()
    if not topic:
        raise HTTPException(400, "topic required")

    r = _redis.Redis.from_url(settings.redis_url)

    raw_fs = r.get(f"ada:full_state:{job_id}")
    if not raw_fs:
        raise HTTPException(404, "state not found")
    try:
        state_dict = _json.loads(raw_fs)
        state = PipelineState(**state_dict)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"state reconstruction failed: {e}") from e

    agent = AnalysisProposerAgent()
    try:
        new_proposals = await agent.propose_directions_with_topic(state, topic)
    except Exception as e:  # noqa: BLE001
        log.warning("g2_directions_endpoint_failed", error=str(e))
        raise HTTPException(500, "direction generation failed") from e

    new_gate_responses = dict(state_dict.get("gate_responses") or {})
    new_gate_responses["G2"] = {
        **(new_gate_responses.get("G2") or {}),
        "proposals": new_proposals,
        "topic": topic,
        "awaiting_decision": True,
    }

    # 1) Redis gate_data 갱신
    try:
        raw_gd = r.get(f"ada:gate_data:{job_id}")
        gd = _json.loads(raw_gd) if raw_gd else {}
        gd["proposals"] = new_proposals
        gd["g2_pending"] = False
        r.set(
            f"ada:gate_data:{job_id}",
            _json.dumps(gd, ensure_ascii=False, default=str),
            ex=86400,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("g2_gate_data_patch_failed", error=str(e))

    # 2) Redis full_state 갱신
    try:
        state_dict["gate_responses"] = new_gate_responses
        r.set(
            f"ada:full_state:{job_id}",
            _json.dumps(state_dict, ensure_ascii=False, default=str),
            ex=86400,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("g2_full_state_patch_failed", error=str(e))

    # 3) LangGraph checkpointer 동기화 (결함 1) — snap 우선 머지 회피
    try:
        from orchestrator.checkpoint import CompatMemorySaver, load_checkpoint, save_checkpoint
        from orchestrator.graph import build_graph

        checkpointer = CompatMemorySaver()
        load_checkpoint(checkpointer, job_id)
        graph = build_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": job_id}}
        await graph.aupdate_state(
            config,
            {"gate_responses": new_gate_responses},
        )
        save_checkpoint(checkpointer, job_id)
    except Exception as e:  # noqa: BLE001
        log.warning("g2_aupdate_state_failed", error=str(e))
        # aupdate_state 실패해도 Redis full_state 는 갱신됐으므로 일부 fallback 동작

    return {"proposals": new_proposals, "topic": topic}
