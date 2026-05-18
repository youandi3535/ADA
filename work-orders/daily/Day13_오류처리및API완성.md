# Day 13 — 오류 처리 + FastAPI 나머지 엔드포인트 완성
> 프로젝트: Adaptive AutoAI Pipeline Agent | 2주 스프린트 Day 13/14

---

## 📋 오늘의 목표

파이프라인의 신뢰성을 보장하는 **오류 처리 시스템**을 완성하고,
사용자와 시스템이 상호작용하는 **FastAPI 나머지 8개 엔드포인트**를 구현한다.
오류 복구 에이전트가 실패를 분류하고 복구 전략을 결정하며,
지수 백오프 데코레이터가 LLM API 오류를 자동으로 재시도한다.

- ErrorRecoveryAgent: Claude Opus 4.7 기반 5개 오류 카테고리 분류 + 복구 전략
- shared/error_handler.py: 지수 백오프, Rate Limit 처리, 모델 다운그레이드
- Fallback 매트릭스 6종 구현
- FastAPI 8개 엔드포인트: 결과 조회, 파일 다운로드, 예측, 헬스체크, WebSocket

---

## 👤 담당자

- **A**: ErrorRecoveryAgent, shared/error_handler.py, Fallback 전략
- **C**: FastAPI 나머지 8개 엔드포인트

---

## ✅ 작업 목록

### 1. ErrorRecoveryAgent 구현 (A)

- [ ] `agents/error_recovery.py` 파일 생성
  - `ErrorRecoveryAgent(BaseAgent)` 클래스 정의
  - LLM 사용: Claude Opus 4.7
  - **ERROR_RECOVERY_PROMPT 정의:**
    ```
    당신은 AI 파이프라인 오류 복구 전문가입니다.
    아래 오류 정보를 분석하여 반드시 JSON 형식으로만 응답하세요:
    {
      "error_category": "오류 카테고리 (data_error/model_error/code_error/llm_api_error/validation_error 중 하나)",
      "root_cause": "오류의 근본 원인 (구체적으로)",
      "recovery_strategy": "복구 전략 (retry/fallback/abort 중 하나)",
      "recovery_detail": "구체적인 복구 방법",
      "proposed_rule": "향후 동일 오류 방지를 위한 규칙",
      "applies_to_agents": ["적용 대상 에이전트 리스트"]
    }

    오류 카테고리 기준:
    - data_error: 데이터 형식/품질 문제
    - model_error: 학습 실패/발산/OOM
    - code_error: 코드 버그/예외
    - llm_api_error: LLM API Rate Limit/타임아웃
    - validation_error: 평가 임계치 미달

    오류 정보:
    {error_info}
    ```

  - **`run(state: PipelineState) -> PipelineState` 구현:**
    - `state.error_info` 딕셔너리로 오류 정보 수집
    - LLM 호출로 오류 분류 및 복구 전략 결정
    - 결과를 `state.recovery_result` 에 저장
    - `rules_manager.add_rule(proposed_rule)` 호출 (AGENTS.md 자동 업데이트)

  - **복구 전략별 후속 처리:**
    - `retry`: `state.retry_count` 초기화 후 지정 에이전트로 재라우팅
    - `fallback`: 대체 전략 설정 후 파이프라인 계속 진행
    - `abort`: 사용자 친화적 오류 메시지 생성 후 파이프라인 종료

  - **5개 오류 카테고리 처리 로직:**
    - `data_error`: 오류 메시지 + 데이터 수정 가이드 반환, 파이프라인 중단
    - `model_error`: OOM → batch_size 절반, 발산 → lr 1/10 축소 후 재시도
    - `code_error`: 스택 트레이스 기반 근본 원인 분석, abort
    - `llm_api_error`: `with_backoff` 재시도, 4회 실패 시 Opus → Sonnet 다운그레이드
    - `validation_error`: retry_count 초기화 후 training_executor 재루프

### 2. error_handler.py 구현 (A)

- [ ] `shared/error_handler.py` 파일 생성
  - **`with_backoff(max_retries=4, base_delay=1.0)` 데코레이터 구현:**
    ```python
    def with_backoff(max_retries: int = 4, base_delay: float = 1.0):
        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                for attempt in range(max_retries):
                    try:
                        return func(*args, **kwargs)
                    except anthropic.RateLimitError as e:
                        if attempt == max_retries - 1:
                            raise
                        delay = base_delay * (2 ** attempt)  # 1s, 2s, 4s, 8s
                        logger.warning(f"Rate limit hit, retrying in {delay}s... (attempt {attempt+1})")
                        time.sleep(delay)
                    except json.JSONDecodeError as e:
                        if attempt == max_retries - 1:
                            raise
                        logger.warning(f"JSON decode error, adding format instruction...")
                        # 다음 시도에서 "반드시 valid JSON으로만 응답하세요" 강조 추가
                        kwargs['force_json'] = True
                    except Exception as e:
                        raise
            return wrapper
        return decorator
    ```

  - **지수 백오프 지연 패턴:** `1s → 2s → 4s → 8s` (base_delay * 2^attempt)
  - **RateLimitError 처리:** 백오프 후 재시도, 로그 기록
  - **4회 실패 시 모델 다운그레이드:**
    - `anthropic.RateLimitError` 4회 → `claude-opus-4-7` → `claude-sonnet-4-6` 전환
    - `llm_client.set_model('claude-sonnet-4-6')` 호출
    - `state.model_downgraded = True` 플래그 설정
    - 다운그레이드 이력 로그 기록
  - **JSONDecodeError 처리:**
    - "반드시 valid JSON only로만 응답하세요. 다른 텍스트 없이 JSON만 출력하세요." 강조 메시지 추가
    - 재호출 (최대 2회)
    - 2회 실패 시 `error_recovery` 에이전트 라우팅

  - **`handle_oom_error(agent_name: str, current_batch_size: int) -> int` 구현:**
    - `current_batch_size // 2` 반환 (최소 8)
    - OOM 발생 에이전트명과 새 배치 크기 로그 기록

  - **`handle_divergence(current_lr: float) -> float` 구현:**
    - `current_lr / 10` 반환 (최소 1e-6)
    - 발산 감지 후 학습률 감소 로그 기록

### 3. Fallback 전략 구현 (A)

- [ ] **오류 분류 매트릭스 6종 구현 (`shared/fallback_strategies.py`):**

  **1. 데이터 오류 (data_error):**
  ```python
  def handle_data_error(state: PipelineState, error: Exception) -> PipelineState:
      state.status = 'aborted'
      state.error_message = f"데이터 오류: {str(error)}\n수정 가이드: {_generate_data_fix_guide(error)}"
      return state  # 파이프라인 중단
  ```

  **2. OOM 오류 (model_error/oom):**
  ```python
  def handle_oom_error(state: PipelineState, error: Exception) -> PipelineState:
      if state.oom_retry_count < 3:
          state.batch_size //= 2
          state.oom_retry_count += 1
          state.next_agent = 'training_executor'  # 재시도
      else:
          # 더 작은 모델로 대체
          state.model_candidates = [_get_fallback_model(state.category)]
          state.next_agent = 'training_executor'
      return state
  ```

  **3. 학습 발산 (model_error/divergence):**
  ```python
  def handle_divergence_error(state: PipelineState) -> PipelineState:
      if state.divergence_retry_count < 2:
          state.override_params = {'learning_rate': state.best_params.get('learning_rate', 0.01) / 10}
          state.divergence_retry_count += 1
          state.next_agent = 'training_executor'
      else:
          state.model_candidates = [_get_simpler_model(state.category)]
          state.next_agent = 'hyperparameter_tuner'
      return state
  ```

  **4. LLM Rate Limit (llm_api_error):**
  - `@with_backoff(max_retries=4, base_delay=1.0)` 데코레이터 적용
  - 4회 실패 시 Opus → Sonnet 모델 다운그레이드

  **5. JSONDecodeError:**
  ```python
  def handle_json_error(llm_call_func, *args, **kwargs):
      for attempt in range(2):
          try:
              return llm_call_func(*args, **kwargs)
          except json.JSONDecodeError:
              kwargs['system_append'] = "반드시 valid JSON only로만 응답하세요."
      # 2회 실패 → error_recovery 라우팅
      raise JSONParsingFailed("LLM JSON 파싱 2회 실패")
  ```

  **6. 검증 실패 (validation_error):**
  ```python
  def handle_validation_failure(state: PipelineState) -> PipelineState:
      if state.retry_count < state.max_retries:
          state.retry_count += 1
          state.next_agent = 'training_executor'
      else:
          state.status = 'aborted'
          state.error_message = f"최대 재시도 {state.max_retries}회 초과. 파이프라인 중단."
      return state
  ```

### 4. FastAPI 나머지 8개 엔드포인트 구현 (C)

- [ ] **`GET /results/{job_id}`** 구현
  ```python
  @router.get("/results/{job_id}", response_model=ResultResponse)
  async def get_results(job_id: str):
      state = await state_store.load(job_id)
      return {
          "job_id": job_id,
          "status": state.status,
          "insights": state.insights,
          "model_metrics": state.best_model['metrics'],
          "chart_paths": state.eda_charts,
          "download_urls": {
              "ppt": f"/download/{job_id}/ppt",
              "pdf": f"/download/{job_id}/pdf",
              "model": f"/download/{job_id}/model",
              "script": f"/download/{job_id}/script",
          }
      }
  ```

- [ ] **`GET /download/{job_id}/{type}`** 구현
  ```python
  @router.get("/download/{job_id}/{type}")
  async def download_file(job_id: str, type: str):
      type_map = {
          'ppt':    (f"reports/{job_id}/report.pptx", 'application/vnd.openxmlformats-officedocument.presentationml.presentation'),
          'pdf':    (f"reports/{job_id}/report.pdf",  'application/pdf'),
          'model':  (f"models/{job_id}/best_model.pkl", 'application/octet-stream'),
          'script': (f"reports/{job_id}/script.txt", 'text/plain; charset=utf-8'),
      }
      if type not in type_map:
          raise HTTPException(status_code=400, detail=f"Unknown type: {type}")
      minio_path, media_type = type_map[type]
      file_bytes = minio_tool.load_bytes(minio_path)
      return StreamingResponse(
          io.BytesIO(file_bytes),
          media_type=media_type,
          headers={"Content-Disposition": f"attachment; filename={Path(minio_path).name}"}
      )
  ```

- [ ] **`POST /predict/{model_id}`** 구현
  ```python
  class PredictRequest(BaseModel):
      features: dict[str, Any]

  @router.post("/predict/{model_id}", response_model=PredictResponse)
  async def predict(model_id: str, request: PredictRequest):
      model = model_cache.get(model_id) or minio_tool.load_model(f"models/{model_id}/best_model.pkl")
      model_cache[model_id] = model
      df = pd.DataFrame([request.features])
      prediction = model.predict(df)[0]
      confidence = float(model.predict_proba(df).max()) if hasattr(model, 'predict_proba') else None
      return {"model_id": model_id, "prediction": prediction, "confidence": confidence}
  ```

- [ ] **`GET /models`** 구현
  ```python
  @router.get("/models", response_model=list[ModelInfo])
  async def list_models():
      models = db.query("SELECT * FROM trained_models ORDER BY created_at DESC")
      return [ModelInfo(**m) for m in models]
  ```

- [ ] **`GET /health`** 구현
  ```python
  @router.get("/health", response_model=HealthResponse)
  async def health_check():
      results = {}
      # PostgreSQL
      try:
          db.execute("SELECT 1")
          results['postgres'] = 'ok'
      except Exception:
          results['postgres'] = 'fail'
      # Redis
      try:
          redis_client.ping()
          results['redis'] = 'ok'
      except Exception:
          results['redis'] = 'fail'
      # MinIO
      try:
          minio_client.list_buckets()
          results['minio'] = 'ok'
      except Exception:
          results['minio'] = 'fail'
      # LLM API
      try:
          anthropic_client.messages.create(
              model="claude-sonnet-4-6", max_tokens=1,
              messages=[{"role": "user", "content": "ping"}]
          )
          results['llm'] = 'ok'
      except Exception:
          results['llm'] = 'fail'
      status_code = 200 if all(v == 'ok' for v in results.values()) else 503
      return JSONResponse(content=results, status_code=status_code)
  ```

- [ ] **`GET /rules`** 구현
  ```python
  @router.get("/rules", response_model=list[RuleInfo])
  async def get_rules(category: Optional[str] = None, is_active: bool = True):
      rules = rules_manager.load_active_rules(category=category) if is_active else db.query(...)
      return [RuleInfo(**r) for r in rules]
  ```

- [ ] **`GET /telemetry/stats`** 구현
  ```python
  @router.get("/telemetry/stats", response_model=TelemetryStats)
  async def get_telemetry_stats(agent_name: Optional[str] = None):
      query = """
          SELECT agent_name,
                 COUNT(*) FILTER (WHERE status='success') * 100.0 / COUNT(*) AS success_rate,
                 AVG(input_tokens)  AS avg_input_tokens,
                 AVG(output_tokens) AS avg_output_tokens,
                 AVG(duration_ms)   AS avg_duration_ms
          FROM agent_runs
          {where}
          GROUP BY agent_name
          ORDER BY agent_name
      """
      where = f"WHERE agent_name = '{agent_name}'" if agent_name else ""
      rows = db.query(query.format(where=where))
      return {"stats": rows}
  ```

- [ ] **`WebSocket /pipeline/ws/{job_id}`** 구현
  ```python
  @router.websocket("/pipeline/ws/{job_id}")
  async def pipeline_websocket(websocket: WebSocket, job_id: str):
      await websocket.accept()
      pubsub = redis_client.pubsub()
      pubsub.subscribe(f"pipeline:{job_id}:progress")
      try:
          for message in pubsub.listen():
              if message['type'] == 'message':
                  data = json.loads(message['data'])
                  await websocket.send_json(data)
                  if data.get('status') in ('completed', 'aborted', 'failed'):
                      break
      except WebSocketDisconnect:
          pass
      finally:
          pubsub.unsubscribe()
          await websocket.close()
  ```
  - **Redis 메시지 형식:**
    ```json
    {
      "current_agent": "training_executor",
      "progress_pct": 65,
      "status": "running",
      "message": "XGBoost 모델 학습 중..."
    }
    ```
  - 각 에이전트 완료 시 `redis_client.publish(f"pipeline:{job_id}:progress", json.dumps(progress_data))`

---

## 🏗️ 구현 명세

### ErrorRecoveryAgent 전체 구조

```python
class ErrorRecoveryAgent(BaseAgent):
    llm_model = "claude-opus-4-7"

    ERROR_RECOVERY_PROMPT = """
당신은 AI 파이프라인 오류 복구 전문가입니다.
반드시 JSON 형식으로만 응답하세요:
{
  "error_category": "data_error/model_error/code_error/llm_api_error/validation_error",
  "root_cause": "근본 원인",
  "recovery_strategy": "retry/fallback/abort",
  "recovery_detail": "구체적 복구 방법",
  "proposed_rule": "방지 규칙",
  "applies_to_agents": ["에이전트 리스트"]
}

오류 정보:
{error_info}
"""

    def run(self, state: PipelineState) -> PipelineState:
        error_info = json.dumps(state.error_info, ensure_ascii=False, indent=2)
        prompt = self.ERROR_RECOVERY_PROMPT.format(error_info=error_info)
        response = llm_client.invoke(prompt, model=self.llm_model)
        recovery = json.loads(response.content)
        state.recovery_result = recovery
        # AGENTS.md 자동 업데이트
        rules_manager.add_rule({
            'category': state.category,
            'root_cause': recovery['root_cause'],
            'proposed_rule': recovery['proposed_rule'],
            'confidence': 0.7,
            'applies_to_agents': recovery['applies_to_agents'],
        })
        # 복구 전략 적용
        if recovery['recovery_strategy'] == 'abort':
            state.status = 'aborted'
            state.error_message = self._generate_user_message(recovery)
        elif recovery['recovery_strategy'] == 'retry':
            state.retry_count = 0
            state.next_agent = self._determine_retry_agent(recovery, state)
        elif recovery['recovery_strategy'] == 'fallback':
            state = fallback_strategies.apply(state, recovery)
        return state
```

### with_backoff 데코레이터 전체 구조

```python
import functools
import time
import json
import anthropic

def with_backoff(max_retries: int = 4, base_delay: float = 1.0):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except anthropic.RateLimitError as e:
                    last_exception = e
                    if attempt == max_retries - 1:
                        # 4회 실패 시 모델 다운그레이드 시도
                        try:
                            kwargs['model'] = 'claude-sonnet-4-6'
                            logger.warning("Downgrading LLM: Opus → Sonnet due to rate limit")
                            return func(*args, **kwargs)
                        except Exception:
                            raise last_exception
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"Rate limit (attempt {attempt+1}/{max_retries}), sleeping {delay}s")
                    time.sleep(delay)
                except json.JSONDecodeError as e:
                    last_exception = e
                    if attempt >= 1:
                        raise JSONParsingFailed(f"JSON 파싱 {attempt+1}회 실패") from e
                    if 'system_append' not in kwargs:
                        kwargs['system_append'] = "반드시 valid JSON only로만 응답하세요. JSON 외 텍스트 없이 순수 JSON만 출력하세요."
            raise last_exception
        return wrapper
    return decorator
```

### WebSocket 진행 상황 발행 구조

```python
# 각 에이전트 BaseAgent.run() 진입/종료 시 호출
def publish_progress(job_id: str, agent_name: str, progress_pct: int, status: str = 'running'):
    message = {
        "current_agent": agent_name,
        "progress_pct": progress_pct,
        "status": status,
        "message": AGENT_MESSAGES.get(agent_name, f"{agent_name} 실행 중..."),
        "timestamp": datetime.utcnow().isoformat(),
    }
    redis_client.publish(f"pipeline:{job_id}:progress", json.dumps(message))

AGENT_MESSAGES = {
    'supervisor':                 '입력 검증 중...',
    'data_profiler':              '데이터 프로파일링 중...',
    'schema_validator':           '스키마 검증 중...',
    'preprocessing_strategist':   '전처리 전략 수립 중...',
    'feature_engineer':           '피처 엔지니어링 실행 중...',
    'eda_agent':                  'EDA 시각화 생성 중...',
    'hyperparameter_tuner':       '하이퍼파라미터 탐색 중...',
    'training_executor':          '모델 학습 중...',
    'training_monitor':           '학습 상태 모니터링 중...',
    'metrics_aggregator':         '메트릭 집계 중...',
    'eval_agent':                 '모델 평가 중...',
    'explainability':             'AI 해석 분석 중...',
    'insight':                    '비즈니스 인사이트 생성 중...',
    'report_composer':            '보고서 생성 중...',
    'error_recovery':             '오류 복구 중...',
}
```

---

## 📁 생성/수정 파일 목록

| 경로 | 작업 | 설명 |
|------|------|------|
| `agents/error_recovery.py` | 신규 생성 | Opus 기반 오류 분류/복구 에이전트 |
| `shared/error_handler.py` | 신규 생성 | with_backoff 데코레이터, OOM/발산 처리 |
| `shared/fallback_strategies.py` | 신규 생성 | 6종 폴백 전략 구현 |
| `api/routers/results.py` | 신규 생성 | GET /results/{job_id} |
| `api/routers/download.py` | 신규 생성 | GET /download/{job_id}/{type} |
| `api/routers/predict.py` | 신규 생성 | POST /predict/{model_id} |
| `api/routers/models.py` | 신규 생성 | GET /models |
| `api/routers/health.py` | 신규 생성 | GET /health |
| `api/routers/rules.py` | 신규 생성 | GET /rules |
| `api/routers/telemetry.py` | 신규 생성 | GET /telemetry/stats |
| `api/routers/websocket.py` | 신규 생성 | WebSocket /pipeline/ws/{job_id} |
| `api/main.py` | 수정 | 새 라우터 등록 |
| `shared/progress_publisher.py` | 신규 생성 | Redis publish 헬퍼 |
| `core/state.py` | 수정 | error_info, recovery_result, error_message 필드 추가 |
| `tests/test_api/test_endpoints.py` | 신규 생성 | 12개 엔드포인트 통합 테스트 |

---

## 🔗 의존성 & 선행 조건

### Day 12까지 완료되어야 하는 항목

- `RulesManager` (`harness/rules_manager.py`) 구현 완료
- `state.ppt_path`, `state.pdf_path` MinIO 경로 설정 완료
- `state.best_model['minio_path']` 설정 완료
- Redis 연결 (`shared/redis_client.py`) 구현 완료
- MinIO `load_bytes`, `load_model` 메서드 구현 완료
- FastAPI 기본 구조 (`api/main.py`, Day 1~7 엔드포인트) 구현 완료

### Python 패키지 의존성

```
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
websockets>=12.0
redis>=5.0.4
anthropic>=0.28.0
psycopg2-binary>=2.9.9
```

### API Pydantic 모델

```python
class ResultResponse(BaseModel):
    job_id: str
    status: str
    insights: Optional[str]
    model_metrics: Optional[dict]
    chart_paths: list[str]
    download_urls: dict[str, str]

class PredictRequest(BaseModel):
    features: dict[str, Any]

class PredictResponse(BaseModel):
    model_id: str
    prediction: Any
    confidence: Optional[float]

class HealthResponse(BaseModel):
    postgres: str
    redis: str
    minio: str
    llm: str

class ModelInfo(BaseModel):
    model_id: str
    model_name: str
    category: str
    primary_metric: float
    created_at: datetime

class TelemetryStats(BaseModel):
    stats: list[dict]
```

---

## ✔️ 완료 기준 (Done Criteria)

- [ ] `GET /health`: 4개 서비스(postgres/redis/minio/llm) 모두 `"ok"` 반환 확인
- [ ] `GET /download/{job_id}/ppt`: PPT 파일 StreamingResponse 정상 반환 확인
- [ ] `GET /download/{job_id}/pdf`: PDF 파일 StreamingResponse 정상 반환 확인
- [ ] `WebSocket /pipeline/ws/{job_id}`: 메시지 수신 및 `progress_pct` 증가 확인
- [ ] `POST /predict/{model_id}`: `features` dict 입력 → `prediction` 반환 확인
- [ ] `GET /telemetry/stats`: `success_rate`, `avg_input_tokens`, `avg_duration_ms` 포함 응답 확인
- [ ] `ErrorRecoveryAgent`: 5개 오류 카테고리(`data_error`, `model_error`, `code_error`, `llm_api_error`, `validation_error`) 각각 올바른 `recovery_strategy` 반환 단위 테스트 통과
- [ ] `with_backoff`: Rate Limit 모의 시 1s→2s→4s→8s 대기 후 재시도 확인
- [ ] `with_backoff`: 4회 Rate Limit 시 Sonnet 다운그레이드 시도 확인
- [ ] `with_backoff`: JSONDecodeError 2회 → `JSONParsingFailed` 예외 발생 확인

---

## ⚠️ 주의사항 & 제약

1. **WebSocket Redis pub/sub 스레드**: FastAPI의 비동기 이벤트 루프와 Redis pub/sub 동기 코드 충돌 주의. `asyncio.get_event_loop().run_in_executor()`로 비동기 처리.
2. **StreamingResponse 와 MinIO**: 대용량 파일(PPT, 모델)은 청크 단위 스트리밍 (`iter_content` 활용) 권장.
3. **`/predict` 모델 캐시**: 동일 model_id 반복 요청 시 MinIO 재로드 방지. `functools.lru_cache` 또는 인메모리 캐시 `model_cache: dict`.
4. **`/health` 타임아웃**: 각 서비스 헬스체크에 3초 타임아웃 설정 (`asyncio.wait_for(check(), timeout=3.0)`).
5. **`/health` LLM 비용**: 헬스체크 시마다 LLM API 호출은 비용 발생. `max_tokens=1` 최소화 필수.
6. **ErrorRecoveryAgent JSON 실패**: ErrorRecovery도 JSON 파싱 실패 가능. 폴백: `{'error_category': 'code_error', 'recovery_strategy': 'abort'}` 하드코딩 기본값.
7. **WebSocket 클라이언트 연결 끊김**: Streamlit UI가 페이지 이탈 시 WebSocket 연결이 비정상 종료될 수 있음. `except WebSocketDisconnect` 항상 처리.
8. **`GET /rules` 페이지네이션**: 규칙 누적 시 응답 크기 제한 필요. `limit=50, offset=0` 파라미터 추가 권장.
9. **동시 요청 격리**: 여러 job_id의 WebSocket이 동시에 연결될 경우, Redis topic을 job_id로 분리하여 메시지 혼선 방지.
10. **Celery 태스크 상태**: FastAPI `/results/{job_id}` 조회 시 Celery 태스크 상태도 함께 확인 (`celery_app.AsyncResult(job_id).state`).

---

## 🆕 v2 확장 작업 (마스터 설계서 §3 · §6 인터페이스)

> v2 에서는 ErrorRecoveryAgent 가 **최후의 보루**로 한 단계 뒤로 물러나고, **AutoErrorHandlerAgent (Day16)** 가 1차 처리한다. Day13에서는 ErrorRecovery를 AutoErrorHandler의 폴백으로 재배치하고 API에 v2 엔드포인트들을 추가한다.

### 1. ErrorRecovery 위치 변경

- [ ] BaseAgent의 try/except 훅 흐름: `exception → AutoErrorHandlerAgent.handle → (실패 시) ErrorRecoveryAgent`
- [ ] ErrorRecovery는 더이상 LangGraph 1차 에이전트가 아닌 폴백 노드

### 2. v2 API 엔드포인트 추가

기존 12개에 더해:
- [ ] `POST /pipeline/{job_id}/decision` (Day6에서 시작했으나 여기서 완성)
- [ ] `GET /pipeline/{job_id}/awaiting`
- [ ] `GET /dashboard/agents` — agent_registry 라이브 상태
- [ ] `GET /dashboard/learning` — self_learning_kb 통계
- [ ] `GET /dashboard/errors` — error_kb 통계 + 최근 24h 발생
- [ ] `GET /dashboard/alarms` — security_audit_log 최근 24h
- [ ] `POST /admin/rules/{rule_id}/approve` — `rules` 테이블의 pending rules (confidence < 0.8) 승인 (admin 전용)
- [ ] `POST /admin/patches/{patch_id}/approve` — `pending_patches` 테이블의 AutoErrorHandler 코드 패치 승인 (admin 전용, 별개 엔드포인트)
- [ ] `POST /admin/patches/{patch_id}/reject` — 패치 거부
- [ ] `GET /outputs/{job_id}` — 생성된 산출물 목록 + 프리사인드 URL

### 3. JWT 인증 미들웨어 통합 (Day17에서 본격화, 인터페이스만)

- [ ] `api/middleware/auth.py` — Bearer token 파싱, `app.current_user_id` Postgres SET
- [ ] 모든 보호 엔드포인트에 `Depends(get_current_user)` 추가

### 4. Rate limit 통합

- [ ] `security/rate_limit.py` 데코레이터 적용:
  - POST /upload: 20/min/user
  - POST /pipeline/start: 5/min/user
  - POST /pipeline/.../decision: 60/min/user (게이트 응답)
  - POST /predict/*: 100/min/user

### 5. with_backoff + AutoErrorHandler 연계

- [ ] LLM 호출은 with_backoff 가 우선 (Rate limit/JSON 실패)
- [ ] BaseAgent 일반 예외는 AutoErrorHandler 진입
- [ ] 두 경로 모두 동일한 audit_log 에 기록 (`event_type='llm_backoff'` vs `'auto_error_handler'`)

### 6. 완료 기준 (v2 추가)

- [ ] /pipeline/{job_id}/decision 엔드포인트 G1~G5 모두 지원 통과
- [ ] /dashboard/* 엔드포인트 5종 통합 테스트 통과
- [ ] Rate limit 발동 시 429 응답 + X-RateLimit-Reset 헤더 확인
