# Day 6 — Supervisor 에이전트 + FastAPI 기본 엔드포인트
> 프로젝트: Adaptive AutoAI Pipeline Agent | 2주 스프린트 Day 6/14

---

## 📋 오늘의 목표

파이프라인의 진입점 역할을 하는 `SupervisorAgent`를 구현하고, 사용자가 파일을 업로드·파이프라인을 실행·진행 상황을 조회할 수 있는 FastAPI 기본 엔드포인트를 완성한다. `SupervisorAgent`는 Claude Sonnet 4.6을 사용하여 입력 유효성을 검증하며, HITL(Human-in-the-Loop) 게이트 로직을 포함한다. FastAPI 라우터(`/upload`, `/pipeline/*`)는 Celery 태스크 큐와 연동되어야 한다.

---

## 👤 담당자

- **A** — agents/supervisor.py 구현
- **C** — api/main.py, api/schemas/, api/routes/ 구현
- 코드 리뷰: B (FastAPI 설계), D (통합 테스트)

---

## ✅ 작업 목록

### [A] agents/supervisor.py 구현

- [ ] `SupervisorAgent(BaseAgent)` 클래스 작성
- [ ] `model_name = "claude-sonnet-4-6"` 설정
- [ ] `VALID_CATEGORIES = ['tabular_ml', 'tabular_dl', 'timeseries', 'anomaly_detection']` 클래스 상수 정의
- [ ] `__call__(self, state: PipelineState) -> PipelineState` 구현:
  1. `_validate_input(state)` 호출 — 룰 기반 검증
  2. 검증 실패 시 즉시 `error_recovery` 라우팅
  3. `retry_count >= 2` 시 HITL 게이트: `waiting_for_human=True` 플래그 설정
  4. LLM 호출하여 task 유형 자동 분류 (classification/regression/clustering/anomaly_detection)
  5. 성공 시 `next_agent="data_profiler"` 설정

- [ ] `_validate_input(self, state: PipelineState) -> tuple[bool, list[str]]` 구현:
  ```python
  def _validate_input(self, state):
      errors = []
      # file_id 존재 여부 확인 (MinIO 오브젝트 조회)
      # category 유효성 확인
      if state.category not in self.VALID_CATEGORIES:
          errors.append(f"유효하지 않은 카테고리: {state.category}")
      # timeseries: target_column 필수
      if state.category == "timeseries" and not state.target_column:
          errors.append("timeseries 카테고리는 target_column 필수")
      # anomaly_detection: target_column 선택 (경고)
      return len(errors) == 0, errors
  ```

- [ ] HITL 게이트 구현:
  ```python
  # retry_count >= 2 시 인간 개입 필요 플래그 설정
  if state.retry_count >= 2:
      return state.model_copy(update={
          "error": "최대 자동 재시도 횟수 초과. 인간 검토 필요.",
          "next_agent": "error_recovery",
          # HITL 플래그는 별도 Redis key에 저장:
          # redis.set(f"ada:hitl:{state.job_id}", "1", ex=86400)
      })
  ```

- [ ] LLM 태스크 분류 시스템 프롬프트:
  ```
  당신은 데이터 분석 파이프라인 입력 검증 전문가입니다.
  사용자가 제공한 데이터 카테고리, 타겟 컬럼, 질문을 분석하여
  task 유형(classification/regression/clustering/anomaly_detection)을
  JSON 형식으로만 응답하세요.
  
  응답 형식:
  {
    "task": "classification",
    "reason": "타겟 컬럼이 이진 분류(0/1) 형태",
    "confidence": 0.95
  }
  ```

- [ ] 성공 패턴 DB 조회: `success_patterns` 테이블에서 동일 category + 과거 성공 config 조회하여 참고

### [C] api/main.py 작성

- [ ] `FastAPI(title="ADA API", version="0.1.0", description="Adaptive AutoAI Pipeline Agent")` 앱 초기화
- [ ] **CORS 미들웨어** 설정:
  ```python
  app.add_middleware(
      CORSMiddleware,
      allow_origins=["http://localhost:8501"],  # Streamlit
      allow_credentials=True,
      allow_methods=["*"],
      allow_headers=["*"],
  )
  ```
- [ ] **GZip 미들웨어** 추가 (응답 압축)
- [ ] **요청 ID 미들웨어** 추가 (`X-Request-ID` 헤더 자동 부여)
- [ ] 라우터 등록:
  - `app.include_router(upload_router, prefix="/upload", tags=["Upload"])`
  - `app.include_router(pipeline_router, prefix="/pipeline", tags=["Pipeline"])`
- [ ] `GET /health` 엔드포인트: `{"status": "ok", "version": "0.1.0"}`
- [ ] `GET /` 엔드포인트: API 정보 반환
- [ ] `@app.on_event("startup")` 에서 `init_db()`, `ensure_bucket_exists()` 호출
- [ ] 전역 예외 핸들러 등록:
  - `RequestValidationError` → 422 + 상세 오류
  - `Exception` → 500 + 오류 ID (structlog에 기록)

### [C] api/schemas/ 작성

- [ ] `api/schemas/__init__.py` — 전체 스키마 재익스포트
- [ ] `api/schemas/upload.py`:
  ```python
  class UploadResponse(BaseModel):
      file_id: str
      filename: str
      size_bytes: int
      sha256: str
      created_at: datetime
      minio_path: str

  class ProfileResponse(BaseModel):
      file_id: str
      profile: dict
      created_at: datetime
  ```
- [ ] `api/schemas/pipeline.py`:
  ```python
  class PipelineStartRequest(BaseModel):
      file_id: str
      category: str = Field(..., pattern="^(tabular_ml|tabular_dl|timeseries|anomaly_detection)$")
      target_column: Optional[str] = None
      user_question: Optional[str] = None
      max_retries: int = Field(default=3, ge=1, le=10)

  class PipelineStartResponse(BaseModel):
      job_id: str
      status: str = "pending"
      created_at: datetime
      estimated_duration_min: Optional[int] = None

  class PipelineStatusResponse(BaseModel):
      job_id: str
      status: str               # pending | running | completed | failed
      current_agent: Optional[str] = None
      progress_pct: int = 0
      error: Optional[str] = None
      created_at: datetime
      updated_at: datetime
  ```

### [C] api/routes/upload.py 구현

- [ ] `POST /upload` 엔드포인트:
  1. `UploadFile` 수신
  2. 파일 타입 검증: `content_type` 또는 확장자 기반
     - 허용: `text/csv`, `application/octet-stream`(parquet), `application/zip`, `text/plain`
     - 거부: 그 외 → 422 오류
  3. 파일 크기 검증: `MAX_UPLOAD_SIZE_MB` (기본 100MB) 초과 시 413 오류
  4. SHA256 해시 계산: `hashlib.sha256(content).hexdigest()`
  5. 중복 파일 확인: `uploads` 테이블에서 `sha256` 조회 → 기존 `file_id` 반환
  6. MinIO 저장: `minio.upload_file(tmp_path, f"uploads/{uuid4()}/{filename}")`
  7. DB 기록: `uploads` 테이블 INSERT
  8. `UploadResponse` 반환

- [ ] `GET /profile/{file_id}` 엔드포인트:
  1. `uploads` 테이블에서 `file_id` 조회
  2. `jobs` 테이블에서 해당 파일의 최근 완료 job 조회
  3. `agent_runs` 테이블에서 `data_profiler` 결과 조회
  4. `ProfileResponse` 반환

- [ ] 파일 타입 검증 헬퍼:
  ```python
  ALLOWED_EXTENSIONS = {".csv", ".parquet", ".zip", ".txt", ".tsv"}
  ALLOWED_MIME_TYPES = {"text/csv", "application/octet-stream",
                        "application/zip", "text/plain", "text/tab-separated-values"}
  ```

### [C] api/routes/pipeline.py 구현

- [ ] `POST /pipeline/start` 엔드포인트:
  1. `PipelineStartRequest` 수신 및 Pydantic 검증
  2. `file_id` 존재 여부 DB 확인 (404 처리)
  3. 동일 `file_id` 실행 중인 job 중복 확인 (409 처리)
  4. `jobs` 테이블 INSERT (status=pending)
  5. `PipelineState` dict 구성
  6. `celery_app.delay(job_id, initial_state_dict)` Celery 태스크 발행
  7. `PipelineStartResponse` 반환

- [ ] `GET /pipeline/status/{job_id}` 엔드포인트:
  1. `jobs` 테이블에서 `job_id` 조회 (404 처리)
  2. Redis `ada:pipeline:{job_id}` 채널에서 최신 진행률 조회 (`redis.get(f"ada:pipeline:{job_id}:latest")`)
  3. `PipelineStatusResponse` 반환

- [ ] `GET /pipeline/result/{job_id}` 엔드포인트 (보너스):
  1. `artifacts` 테이블에서 job_id 관련 아티팩트 조회
  2. 각 아티팩트에 presigned URL 생성
  3. `{ppt_url, pdf_url, script_url, model_url}` dict 반환

- [ ] `POST /pipeline/cancel/{job_id}` 엔드포인트 (보너스):
  1. `celery_app.control.revoke(task_id, terminate=True)` 호출
  2. DB status → `cancelled` 업데이트

---

## 🏗️ 구현 명세

### agents/supervisor.py 전체 구조

```python
# agents/supervisor.py
from agents.base import BaseAgent
from shared.state import PipelineState
from shared.config import settings
from tools.minio_tool import MinIOClient
import json

VALID_CATEGORIES = ["tabular_ml", "tabular_dl", "timeseries", "anomaly_detection"]

SYSTEM_PROMPT = """
당신은 데이터 분석 파이프라인 입력 검증 전문가입니다.
사용자 입력(카테고리, 타겟 컬럼, 질문)을 분석하여
적합한 task 유형을 결정하고 JSON만 응답하세요.

응답 형식:
{
  "task": "classification" | "regression" | "clustering" | "anomaly_detection",
  "reason": "결정 근거",
  "confidence": 0.0~1.0
}
"""


class SupervisorAgent(BaseAgent):
    model_name = "claude-sonnet-4-6"
    VALID_CATEGORIES = VALID_CATEGORIES

    def __call__(self, state: PipelineState) -> PipelineState:
        # 1. 룰 기반 검증
        is_valid, errors = self._validate_input(state)
        if not is_valid:
            return state.model_copy(update={
                "error": "; ".join(errors),
                "next_agent": "error_recovery",
            })

        # 2. HITL 게이트
        if state.retry_count >= 2:
            return state.model_copy(update={
                "error": "자동 재시도 한도 초과. 인간 검토 필요.",
                "next_agent": "error_recovery",
            })

        # 3. LLM task 분류
        user_prompt = f"""
        카테고리: {state.category}
        타겟 컬럼: {state.target_column or "없음"}
        사용자 질문: {state.user_question or "없음"}
        """
        response_text = self._call_llm(SYSTEM_PROMPT, user_prompt)
        parsed = self._parse_json(response_text)

        return state.model_copy(update={
            "task": parsed.get("task", "classification"),
            "next_agent": "data_profiler",
            "error": None,
        })

    def _validate_input(self, state: PipelineState) -> tuple[bool, list[str]]:
        errors = []
        if state.category not in self.VALID_CATEGORIES:
            errors.append(f"유효하지 않은 카테고리: {state.category}")
        if state.category == "timeseries" and not state.target_column:
            errors.append("timeseries 카테고리는 target_column 필수")
        # MinIO file_id 존재 여부 확인
        try:
            minio = MinIOClient()
            minio.s3.head_object(Bucket=settings.minio_bucket, Key=state.file_id)
        except Exception:
            errors.append(f"file_id '{state.file_id}' 를 MinIO에서 찾을 수 없음")
        return len(errors) == 0, errors
```

### api/main.py 전체 구조

```python
# api/main.py
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
import uuid
from shared.db import init_db
from tools.minio_setup import ensure_bucket_exists
from api.routes.upload import router as upload_router
from api.routes.pipeline import router as pipeline_router

app = FastAPI(
    title="ADA API",
    version="0.1.0",
    description="Adaptive AutoAI Pipeline Agent REST API",
)

app.add_middleware(CORSMiddleware,
    allow_origins=["http://localhost:8501"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.include_router(upload_router, prefix="/upload", tags=["Upload"])
app.include_router(pipeline_router, prefix="/pipeline", tags=["Pipeline"])


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.on_event("startup")
async def startup():
    await init_db()
    ensure_bucket_exists()


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}
```

### api/routes/upload.py POST /upload 핵심 로직

```python
@router.post("/", response_model=UploadResponse, status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    # 1. 파일 타입 검증
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=422, detail=f"허용되지 않는 파일 형식: {suffix}")

    # 2. 내용 읽기 + 크기 검증
    content = await file.read()
    size_mb = len(content) / 1024**2
    if size_mb > settings.max_upload_size_mb:
        raise HTTPException(status_code=413, detail=f"파일 크기 초과: {size_mb:.1f}MB")

    # 3. SHA256 해시
    sha256 = hashlib.sha256(content).hexdigest()

    # 4. 중복 확인
    existing = await db.execute(select(Upload).where(Upload.sha256 == sha256))
    if existing := existing.scalar_one_or_none():
        return UploadResponse.model_validate(existing)

    # 5. MinIO 저장
    file_id = str(uuid4())
    object_name = f"uploads/{file_id}/{file.filename}"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    minio_path = MinIOClient().upload_file(tmp_path, object_name)
    Path(tmp_path).unlink()

    # 6. DB 기록
    upload = Upload(file_id=file_id, filename=file.filename,
                    sha256=sha256, size_bytes=len(content),
                    minio_path=minio_path)
    db.add(upload)
    await db.commit()
    await db.refresh(upload)

    return UploadResponse.model_validate(upload)
```

### Celery 태스크 발행 코드 (pipeline.py)

```python
@router.post("/start", response_model=PipelineStartResponse, status_code=202)
async def start_pipeline(
    req: PipelineStartRequest,
    db: AsyncSession = Depends(get_db),
):
    # 1. file_id 확인
    upload = await db.get(Upload, req.file_id)  # file_id가 PK인 경우
    if not upload:
        raise HTTPException(status_code=404, detail="file_id 없음")

    # 2. 중복 실행 확인
    running_job = await db.execute(
        select(Job).where(Job.file_id == req.file_id, Job.status == "running")
    )
    if running_job.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="이미 실행 중인 파이프라인 있음")

    # 3. Job 생성
    job = Job(file_id=req.file_id, category=req.category,
              target_column=req.target_column, user_question=req.user_question,
              status="pending")
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # 4. Celery 태스크 발행
    initial_state = PipelineState(
        job_id=str(job.id),
        file_id=req.file_id,
        category=req.category,
        task="classification",  # Supervisor가 재분류
        target_column=req.target_column,
        user_question=req.user_question,
    ).to_dict()

    celery_app.send_task("run_pipeline", args=[str(job.id), initial_state],
                         queue="pipeline")

    return PipelineStartResponse(job_id=str(job.id), created_at=job.created_at)
```

---

## 📁 생성/수정 파일 목록

```
프로젝트 루트/
├── agents/
│   └── supervisor.py                   # [A] SupervisorAgent (Claude Sonnet 4.6)
├── api/
│   ├── __init__.py
│   ├── main.py                         # [C] FastAPI 앱 초기화
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── upload.py                   # [C] UploadResponse, ProfileResponse
│   │   └── pipeline.py                 # [C] PipelineStartRequest/Response, StatusResponse
│   └── routes/
│       ├── __init__.py
│       ├── upload.py                   # [C] POST /upload, GET /profile/{file_id}
│       └── pipeline.py                 # [C] POST /start, GET /status/{job_id}
└── tests/
    ├── agents/
    │   └── test_supervisor.py          # [A+D] SupervisorAgent 단위 테스트
    └── api/
        ├── test_upload.py              # [C+D] 업로드 엔드포인트 통합 테스트
        └── test_pipeline.py            # [C+D] 파이프라인 엔드포인트 통합 테스트
```

---

## 🔗 의존성 & 선행 조건

- **Day 3 완료 필수**: `agents/base.py`, `shared/state.py`, `shared/config.py`
- **Day 4 완료 필수**: `orchestrator/runner.py` (Celery `celery_app` 임포트)
- **Day 5 완료 필수**: `tools/minio_tool.py` (MinIOClient)
- FastAPI 설치 확인 (`pip show fastapi`)
- python-multipart 설치 확인 (`pip show python-multipart`)
- httpx 설치 확인 (`pip show httpx`) — TestClient 사용
- Redis 컨테이너 healthy, `REDIS_URL` 환경변수 확인

---

## ✔️ 완료 기준 (Done Criteria)

- [ ] `uvicorn api.main:app --reload` 정상 시작, Swagger UI(http://localhost:8000/docs) 접속 성공
- [ ] `curl -X POST http://localhost:8000/upload -F "file=@titanic.csv"` → 201 응답, `file_id` 반환
- [ ] `curl http://localhost:8000/health` → `{"status": "ok"}` 응답
- [ ] `curl -X POST http://localhost:8000/pipeline/start -H "Content-Type: application/json" -d '{"file_id":"...","category":"tabular_ml","target_column":"Survived"}'` → 202 응답, `job_id` 반환
- [ ] Celery 큐에서 `run_pipeline` 태스크 수신 확인 (`celery -A orchestrator.runner inspect active`)
- [ ] `curl http://localhost:8000/pipeline/status/{job_id}` → 상태 정보 반환
- [ ] 동일 파일 재업로드 시 기존 `file_id` 반환 (SHA256 중복 처리 확인)
- [ ] 100MB 초과 파일 업로드 시 413 오류 반환 확인
- [ ] `SupervisorAgent` 단위 테스트 전체 통과
- [ ] FastAPI TestClient 통합 테스트 전체 통과

---

## ⚠️ 주의사항 & 제약

### AGENTS.md 룰 (Day 6 적용)

- **R-003**: SupervisorAgent는 반드시 BaseAgent 상속. LLM 호출은 `_call_llm()` 헬퍼 사용
- **R-004**: SupervisorAgent LLM 응답은 JSON만 허용. 마크다운 또는 자유 텍스트 응답 시 `_parse_json()` 재시도 로직 적용
- **R-005**: `state.model_copy(update={...})` 패턴 사용. state 직접 수정 금지

### FastAPI 설계 원칙

- 모든 엔드포인트는 Pydantic 스키마로 request/response 타입 지정
- DB 세션은 `Depends(get_db)` 패턴으로만 주입 (직접 생성 금지)
- 예외는 `HTTPException` 으로 처리. 내부 오류는 500 + 오류 ID 반환 (stack trace 노출 금지)
- 파일 업로드는 반드시 임시 파일 사용 후 삭제 (`tempfile.NamedTemporaryFile`)

### 보안 주의사항

- 업로드 파일명에 경로 순회 공격 방어: `Path(filename).name` 으로 파일명만 추출
- SHA256 중복 검사로 동일 파일 중복 저장 방지 (스토리지 절약)
- `content_type` 검증만으로 불충분 — 파일 내용(magic bytes) 검사 추가 권장 (Day 8 이후)

### HITL 게이트 구현 상세

- `retry_count >= 2` 조건에서 Redis에 HITL 플래그 저장: `redis.setex(f"ada:hitl:{job_id}", 86400, "1")`
- Streamlit 프론트엔드에서 HITL 상태 폴링하여 인간 개입 UI 표시 (Day 11에 구현)
- HITL 승인 시 `retry_count` 리셋 후 파이프라인 재시작

### Celery 연동 주의사항

- `celery_app.send_task()` 에서 `queue="pipeline"` 명시 필수
- Celery worker가 미기동 상태여도 `send_task()`는 성공 (큐에 쌓임)
- 태스크 발행 후 즉시 `PipelineStartResponse` 반환 (비동기 처리, 결과 대기 없음)

---

## 🆕 v2 확장 작업 (마스터 설계서 §3 · §4)

> Day6 의 v2 핵심은 **IntentElicitorAgent (G0)** 와 **AnalysisProposerAgent (G1)** 를 완성하고, FastAPI 에 **interactive decision 엔드포인트**를 추가하는 것이다.

### 1. `agents/intent_elicitor.py` — IntentElicitorAgent (G0)

- [ ] BaseAgent 상속, Claude Sonnet 4.6 사용
- [ ] 사용자가 입력한 자유 텍스트(`state.user_intent`)를 받아 구조화 dict 반환
- [ ] 시스템 프롬프트:
  ```
  당신은 데이터 분석 의도를 구조화하는 전문가입니다.
  사용자의 자유 서술을 받아 다음 JSON 스키마로만 응답하세요.
  {
    "primary_goal": "예측 | 분류 | 군집화 | 이상탐지 | 예측+해석 | 의사결정지원 | 기타",
    "audience": "임원 | 분석가 | 일반대중 | 운영",
    "deliverable_hint": ["ppt","pdf","dashboard","script","insight_md"],
    "business_context": "1~2 문장 요약",
    "constraints": ["시간","해석가능성","비용","규제"],
    "success_criteria": "사용자가 명시한 성공 기준 (없으면 추정)"
  }
  ```
- [ ] 응답을 `state.user_intent_structured` 에 저장
- [ ] 반드시 `sanitize_user_input(state.user_intent)` 통과 후 LLM 호출 (R-401)
- [ ] 임베딩 생성 후 `intent_embeddings` 테이블에 저장

### 2. `agents/proposers/analysis_proposer.py` — AnalysisProposerAgent (G1)

- [ ] BaseGateAgent 상속, gate_code='G1', Claude Opus 4.7 (3안 품질 우선)
- [ ] `build_proposals(state)` 구현:
  1. `SelfLearningClient.fetch_similar_cases(intent_emb + profile_emb)` 로 과거 사례 5건 조회
  2. `SelfLearningClient.fetch_recipes(category, kb_types=['success_pattern','recipe'])` 로 레시피 10건 조회
  3. LLM 호출, system prompt:
     ```
     당신은 AutoAI 분석 전략가입니다.
     데이터 프로파일, 사용자 의도, 과거 성공 사례를 참고하여
     서로 명확히 구분되는 3개의 분석 방향을 제시하세요.
     반드시 다음 JSON으로만 응답:
     [
       {
         "title": "방향 제목 (15자 내외)",
         "why": "왜 이 방향이 적합한가 (2~3 문장)",
         "plan_outline": ["단계1","단계2","단계3"],
         "est_metrics": {"primary": "val_f1≈0.82", "interpretability": "high"},
         "est_duration_min": 15,
         "transformer_used": true,
         "referenced_past_jobs": ["job_id1","job_id2"]
       }, ... (총 3개)
     ]
     ```
  4. 응답 검증: 길이 == 3, transformer_used 가 true 인 안 최소 1개 (R-403)
- [ ] G1 노드는 마지막에 BaseGateAgent.__call__이 awaiting_decision='G1' 설정 후 그래프 일시정지

### 3. SupervisorAgent v2 확장

- [ ] v1 의 `_validate_input` 유지 + 신규:
  - actor_user_id, actor_role 검증 (Day17 인증과 연동)
  - PII 스캔 결과 확인
- [ ] LLM 으로 task 분류 후 → `intent_elicitor` 로 라우팅 (이전엔 `data_profiler` 직행)

### 4. FastAPI 신규 엔드포인트

- [ ] `POST /pipeline/{job_id}/decision` — 게이트 응답 수신
  ```python
  class DecisionRequest(BaseModel):
      gate: Literal["G0","G0_PII","G1","G2","G3","G4","G5"]
      choice: dict   # 게이트별 다른 구조
      rationale: Optional[str] = None

  @router.post("/{job_id}/decision", status_code=202)
  async def submit_decision(job_id: UUID, req: DecisionRequest, ...):
      # 1. 보안: actor_user_id == job.owner 확인 (RLS + 코드 가드)
      # 2. sanitize choice
      # 3. checkpointer에서 state 로드, state.user_choice_gX 주입
      # 4. interactive_sessions / decisions 테이블 기록
      # 5. Celery resume_pipeline 발행
      return DecisionAck(...)
  ```

- [ ] `GET /pipeline/{job_id}/awaiting` — 현재 대기 중인 게이트와 제안 조회
  ```python
  @router.get("/{job_id}/awaiting")
  async def get_awaiting(job_id: UUID, ...):
      # LangGraph snapshot에서 state 조회 후 awaiting_decision + proposals 반환
      ...
  ```

### 5. WebSocket — 게이트 인터럽트 알림 추가

- [ ] `ws /pipeline/{job_id}` 메시지 형식 확장:
  ```json
  {"type": "interrupt", "gate": "G1", "proposals": [...]}
  {"type": "progress", "agent": "eda_agent", "progress_pct": 18}
  {"type": "completed", "outputs": [...]}
  ```

### 6. 완료 기준 (v2 추가)

- [ ] `pytest tests/agents/test_intent_elicitor.py` 통과 — 5종 사용자 의도 모두 구조화 성공
- [ ] `pytest tests/agents/test_analysis_proposer.py` — 3개 안 반환, 그 중 1개 이상 transformer_used=true
- [ ] E2E 테스트: POST /pipeline/start → 약 5초 내 awaiting_decision='G1' 상태 → POST /pipeline/{job_id}/decision → G2 진입 확인

### 7. 주의사항 (v2)

- IntentElicitor LLM 응답이 JSON 실패하면 폴백: `primary_goal="예측"`, `audience="분석가"`, deliverable_hint=["ppt","pdf"]
- AnalysisProposer 가 3안을 못 만들면 (LLM 실패) → 카테고리별 기본 3안 하드코딩 폴백
- decision 엔드포인트는 idempotent 하지 않음 — 동일 게이트 2회 호출 시 두 번째는 409 반환
