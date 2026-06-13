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
            # HJ 2026-06-11 — G3~G6 풍부 데이터 forward 확장. PipelineState 에 있던 필드들이
            #   응답에 누락되어 frontend 가 undefined 만 받던 문제 해결.
            #   사용자가 강조: "G1·G2 처럼 G3~G6 도 실시간 분석 내용 받아와야 함" → 같은 forward 패턴 적용.
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
                # HJ 2026-06-11 — G3~G6 모달 콘텐츠용 풍부 필드 추가:
                "chosen_recipe",  # G2 선택 결과 = G3 모달 첫 행
                "user_intent",  # G1 사용자 의도 = G2 이후 화면 컨텍스트
                "preprocessing_strategy",  # G3 strategist 결과 = G4 모달
                "feature_engineering",  # G3 strategist 결과 = G4 모달
                "preprocessing_plan",  # G3 plan steps
                "candidate_models",  # G4 model_selection 결과 = G5 모달
                "best_params",  # G4 tuner 결과 = G5 모달
                "explainability",  # G5 결과 = G6 모달
            ):
                v = _gd.get(k)
                if v is not None:
                    # CS 2026-06-11 — gate_data 의 stale "category": "pending" 이
                    # job.category(이미 _persist_detection 으로 정확히 갱신됨)를
                    # 다시 "pending" 으로 덮어써서 아래 휴리스틱이 tabular_ml 로
                    # 강제 확정시키는 문제 방지.
                    if (
                        k == "category"
                        and (not v or v == "pending")
                        and data.get("category") not in (None, "", "pending")
                    ):
                        continue
                    data[k] = v
            # output_paths: gate_data 값이 있으면 DB 값을 덮어씀 (완료 후 저장된 게 정확)
            if _gd.get("output_paths"):
                data["output_paths"] = {**(data.get("output_paths") or {}), **_gd["output_paths"]}
    except Exception:  # noqa: BLE001
        pass

    # CS 2026-06-12 — data_profiler 가 카테고리 확정 즉시(G1 초반) 기록한 1회성 고정 키.
    # ada:gate_data 의 category 가 아직 없거나(0~수초) "pending" 이어도, 이 키는 detection
    # 시점에 한 번만 쓰여 이후 절대 덮어쓰이지 않으므로 휴리스틱보다 먼저, 최우선으로 신뢰한다.
    if not data.get("category") or data.get("category") == "pending":
        try:
            import redis as _redis3

            from ada.core.config import settings as _s3

            _rc3 = _redis3.Redis.from_url(_s3.redis_url, decode_responses=True)
            _pinned = _rc3.get(f"ada:category:{job_id}")
            if _pinned:
                data["category"] = _pinned
        except Exception:  # noqa: BLE001
            pass

    # CS 2026-06-12 — category 누락/pending 보정 (보수적 휴리스틱 v2).
    # 본인 의도: "강제는 최후 수단", "유연하게 들어오는 데이터로 인지".
    # 강한 신호만 매칭하고 모호한 케이스는 "pending" 유지 →
    # frontend gateHeader/modalHtml 의 prefetchResult.category 폴백 (Ollama LLM 결과) 사용.
    #
    # 4 카테고리 안전 매트릭스:
    #   - 시계열: date_col 결정적 신호 → timeseries
    #   - 이상탐지: 사용자 의도 키워드 (anomaly/outlier/사기 등) → anomaly_detection
    #   - 정형 DL: target + 고차원 (rows>=50k AND cols>=20) → tabular_dl
    #   - 정형 ML: target + 데이터 있음 (그 외) → tabular_ml
    #   - 모호 (target 미박힘 + 신호 없음): pending 유지 → prefetch 폴백
    #
    # 이전(2026-06-11) 휴리스틱의 위험 시나리오 제거:
    #   X 정형 ML (rows>=500, target 미박힘) → anomaly_detection 오분류
    #   X 정형 DL (cols<20, rows>=50k) → tabular_ml 오분류
    if not data.get("category") or data.get("category") == "pending":
        _dp = data.get("data_profile") or {}
        _date_col = _dp.get("date_col") or _dp.get("detected_time_col")
        _target = data.get("target_column") or _dp.get("detected_target")
        _has_target = bool(_target)
        _rows = int(_dp.get("rows") or (_dp.get("shape") or {}).get("rows") or 0)
        _cols = int(_dp.get("cols") or (_dp.get("shape") or {}).get("cols") or 0)
        _intent = (data.get("user_intent") or "").lower()
        _anomaly_keywords = (
            "이상탐지",
            "이상 탐지",
            "anomaly",
            "outlier",
            "novelty",
            "사기",
            "fraud",
            "이탈",
            "비정상",
        )
        _has_anomaly_intent = any(k in _intent for k in _anomaly_keywords)

        if _date_col:
            data["category"] = "timeseries"  # 시계열: date_col 결정적
        elif _has_anomaly_intent:
            data["category"] = "anomaly_detection"  # 이상탐지: 명시 의도 키워드
        elif _has_target and _rows >= 50_000 and _cols >= 20:
            data["category"] = "tabular_dl"  # 정형 DL: target + 고차원
        elif _has_target and _rows > 0:
            data["category"] = "tabular_ml"  # 정형 ML: target + 데이터
        # 그 외 → "pending" 유지 → frontend prefetchResult.category 폴백 작동

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

    # HJ 2026-06-13 — G3(방법론) 화면 진입 감지 → 전처리 윤색 선계산 1회 디스패치.
    #   사용자가 방법론을 고르는 동안 worker(-c 2)가 plan+윤색을 미리 만들어 Redis 캐시에 저장 →
    #   resume 후 preprocessing_strategist 가 캐시 히트로 즉시 표시(품질 보장·0 블록). G2 eda_prefetch 동형.
    #   gate_detail 은 폴링되므로 NX 락으로 job 당 1회만 디스패치. 실패/미완은 노드가 그 자리 폴백.
    if data.get("gate") == "G3":
        try:
            import redis as _rp

            from ada.core.config import settings as _sp

            _rcp = _rp.Redis.from_url(_sp.redis_url)
            if _rcp.set(f"ada:g3_pre_prefetch_lock:{job_id}", "1", nx=True, ex=600):
                from orchestrator.runner import g3_pre_prefetch_task

                g3_pre_prefetch_task.apply_async(args=[job_id], queue="pipeline")
                log.info("g3_pre_prefetch_dispatched", job_id=job_id)
        except Exception as e:  # noqa: BLE001
            log.warning("g3_pre_prefetch_dispatch_failed", error=str(e))

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
# ---------------------------------------------------------------------------
# HJ 2026-06-12 — G2 분석 방향 백그라운드 선(先)생성 캐시.
#   주제 5개를 사용자가 고르기 전에 미리 생성해 Redis 에 캐싱 → 선택 시 즉시 반환(대기 0).
#   추천(첫 주제)부터 순차 생성. 직접 입력(custom)은 캐시에 없어 기존대로 동기 생성됨.
#   캐시 구조: Redis Hash  ada:g2_dircache:{job_id}
#     field = 주제 제목 텍스트, value = {"status":"pending"|"done"|"error","proposals":[...]}
# ---------------------------------------------------------------------------
_G2_DIRCACHE_TTL = 86400


def _g2_dircache_key(job_id: str) -> str:
    return f"ada:g2_dircache:{job_id}"


def _g2_dircache_get(r, job_id: str, topic: str) -> dict | None:
    """캐시에서 해당 주제 엔트리(dict) 조회. 없거나 오류면 None."""
    import json as _json

    try:
        raw = r.hget(_g2_dircache_key(job_id), topic.strip())
        if not raw:
            return None
        return _json.loads(raw)
    except Exception:  # noqa: BLE001
        return None


async def _g2_dircache_wait(r, job_id: str, topic: str, timeout_s: float = 175.0):
    """prefetch 가 생성 중(pending)이면 done 될 때까지 폴링 — 중복 LLM 호출 방지.

    완료되면 proposals(list) 반환, error 또는 timeout 이면 None(→ 호출측이 동기 생성 폴백).
    """
    import asyncio as _asyncio

    waited = 0.0
    step = 0.5
    while waited < timeout_s:
        await _asyncio.sleep(step)
        waited += step
        entry = _g2_dircache_get(r, job_id, topic)
        if not entry:
            continue
        st = entry.get("status")
        if st == "done" and entry.get("proposals"):
            return entry["proposals"]
        if st == "error":
            return None
    return None


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

    # HJ 2026-06-12 — 캐시 우선: prefetch 가 이미 만든 분석 방향이면 즉시 사용(대기 0).
    #   pending(생성 중)이면 완료까지 대기해 중복 LLM 호출을 피한다.
    #   캐시 미스(직접 입력 등)면 기존대로 그 자리에서 동기 생성.
    new_proposals = None
    _cached = _g2_dircache_get(r, job_id, topic)
    if _cached and _cached.get("status") == "done" and _cached.get("proposals"):
        new_proposals = _cached["proposals"]
        log.info("g2_directions_cache_hit", topic=topic[:60])
    elif _cached and _cached.get("status") == "pending":
        new_proposals = await _g2_dircache_wait(r, job_id, topic)
        if new_proposals is not None:
            log.info("g2_directions_cache_wait_hit", topic=topic[:60])
    if new_proposals is None:
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


async def _prefetch_eda_insights(state) -> None:
    """C′-1 — EDA 인사이트 선계산을 worker Celery 태스크로 위임.

    api 컨테이너엔 pandas 가 없어 직접 계산 불가 → worker(pandas 보유)에서 실행, 결과는 Redis 캐시.
    resume 시 eda_agent 노드가 캐시 재사용해 _dynamic_insights(120~160초)를 스킵한다.
    """
    if not state.job_id:
        return
    try:
        from orchestrator.runner import g2_eda_prefetch_task

        g2_eda_prefetch_task.apply_async(args=[state.job_id], queue="pipeline")
        log.info("g2_eda_prefetch_dispatched", job_id=state.job_id)
    except Exception as e:  # noqa: BLE001
        log.warning("g2_eda_prefetch_dispatch_failed", error=str(e))


async def _prefetch_methodology(state, ck_key, rec_topic) -> None:
    """C′-2 — 추천 주제의 추천 방향(directions[0])으로 방법론 후보 선계산 → 캐시.

    추천 주제의 directions 캐시에서 첫 방향 제목을 읽어 methodology LLM 을 미리 돌린다.
    resume 시 gate_methodology 노드가 (job_id, 방향제목, category) 일치하면 재사용(63~87초 절감).
    실패·미완은 무시 → 노드가 기존대로 그 자리에서 생성(폴백).
    """
    import json as _json

    import redis as _redis

    from agents.gates.methodology_proposer import (
        MethodologyProposerAgent,
        _g2_method_cache_get,
        _g2_method_cache_set,
    )

    if not state.job_id:
        return
    try:
        r = _redis.Redis.from_url(settings.redis_url)
        raw = r.hget(ck_key, rec_topic)
        if not raw:
            return
        d = _json.loads(raw)
        props = [p for p in (d.get("proposals") or []) if isinstance(p, dict) and not p.get("is_custom")]
        rec_dir = (props[0].get("title") or "").strip() if props else ""
    except Exception as e:  # noqa: BLE001
        log.warning("g2_method_prefetch_read_failed", error=str(e))
        return
    if not rec_dir:
        return
    if _g2_method_cache_get(state.job_id, rec_dir, state.category):
        return  # 이미 캐시됨
    try:
        llm_opts = await MethodologyProposerAgent()._generate_for_title(state, rec_dir)
    except Exception as e:  # noqa: BLE001
        log.warning("g2_method_prefetch_llm_failed", error=str(e))
        return
    if llm_opts:
        _g2_method_cache_set(state.job_id, rec_dir, state.category, llm_opts)
        log.info("g2_method_prefetch_done", n=len(llm_opts), direction=rec_dir[:50])


@router.post("/gate/G2/directions/prefetch/{job_id}")
async def prefetch_directions_for_topics(job_id: str, req: dict) -> dict:
    """G2 주제 5개의 분석 방향을 백그라운드 선(先)생성.

    Body: {"topics": ["추천주제", "주제2", ...]}  (배열 첫번째=추천 → 제일 먼저 생성)

    동작:
      - 즉시 응답 반환(fire-and-forget). 실제 생성은 asyncio background task 가 수행.
      - 추천부터 순차로 propose_directions_with_topic 호출 → Redis 캐시에 저장.
      - Ollama(qwen2.5:7b, CPU)는 동시 호출 시 경합으로 더 느려지므로 반드시 '순차' 생성.
      - 사용자가 '선택 완료' 를 누르면 /directions/{job_id} 가 이 캐시를 먼저 조회 → 즉시 응답.
      - job 단위 Redis 락으로 중복 prefetch task 기동을 막는다.
    """
    import asyncio as _asyncio
    import json as _json

    import redis as _redis

    from ada.core.state import PipelineState
    from agents.gates.analysis_proposer import AnalysisProposerAgent

    topics = [t.strip() for t in ((req or {}).get("topics") or []) if isinstance(t, str) and t.strip()][:5]
    if not topics:
        return {"status": "no_topics", "count": 0}

    r = _redis.Redis.from_url(settings.redis_url)
    raw_fs = r.get(f"ada:full_state:{job_id}")
    if not raw_fs:
        raise HTTPException(404, "state not found")
    try:
        state = PipelineState(**_json.loads(raw_fs))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"state reconstruction failed: {e}") from e

    ck = _g2_dircache_key(job_id)
    lock_key = f"{ck}:lock"
    # job 당 1회만 prefetch 기동 (중복 task 방지). 10분 후 자동 해제.
    if not r.set(lock_key, "1", nx=True, ex=600):
        return {"status": "already_running", "count": len(topics)}

    async def _runner() -> None:
        rr = _redis.Redis.from_url(settings.redis_url)
        agent = AnalysisProposerAgent()
        try:
            for idx, topic in enumerate(topics):  # topics[0] = 추천 → 제일 먼저
                try:
                    cur = rr.hget(ck, topic)
                    if cur:
                        try:
                            if _json.loads(cur).get("status") == "done":
                                continue  # 이미 생성됨 — skip
                        except Exception:  # noqa: BLE001
                            pass
                    rr.hset(ck, topic, _json.dumps({"status": "pending", "topic": topic}, ensure_ascii=False))
                    proposals = await agent.propose_directions_with_topic(state, topic)
                    rr.hset(
                        ck,
                        topic,
                        _json.dumps(
                            {"status": "done", "topic": topic, "proposals": proposals},
                            ensure_ascii=False,
                            default=str,
                        ),
                    )
                    log.info("g2_prefetch_done", topic=topic[:60])
                except Exception as e:  # noqa: BLE001
                    log.warning("g2_prefetch_topic_failed", topic=topic[:60], error=str(e))
                    try:
                        rr.hset(ck, topic, _json.dumps({"status": "error", "topic": topic}, ensure_ascii=False))
                    except Exception:  # noqa: BLE001
                        pass
                # HJ 2026-06-12 — C′-1·C′-2: 추천 주제 directions 직후 EDA·방법론 선계산(resume-임계 최우선).
                if idx == 0:
                    try:
                        await _prefetch_eda_insights(state)
                    except Exception as e:  # noqa: BLE001
                        log.warning("g2_eda_prefetch_failed", error=str(e))
                    try:
                        await _prefetch_methodology(state, ck, topic)
                    except Exception as e:  # noqa: BLE001
                        log.warning("g2_method_prefetch_failed", error=str(e))
            try:
                rr.expire(ck, _G2_DIRCACHE_TTL)
            except Exception:  # noqa: BLE001
                pass
        finally:
            try:
                rr.delete(lock_key)
            except Exception:  # noqa: BLE001
                pass

    _asyncio.create_task(_runner())
    return {"status": "prefetching", "count": len(topics)}
