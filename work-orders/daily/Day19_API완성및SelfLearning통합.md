# Day 19 — FastAPI 완성 + SelfLearningAgent 본격화 + WebSocket
> 프로젝트: Adaptive AutoAI Pipeline Agent | 3주 스프린트 Day 19/21
> 본 문서는 v2 신규 작업이다. 마스터 설계서 §5 후속·§4-G 참조.

---

## 📋 오늘의 목표

전체 FastAPI 엔드포인트 (v1 12개 + v2 신규 ~13개, 총 **~25개**) 를 마무리하고, **SelfLearningAgent의 3-Stack 학습 사이클 (`distill_job`)** 을 완성한다. WebSocket 메시지 라우팅 강화, 캐시 정책, API 문서화까지 포함. v2.1 스코프 축소로 산출물 다운로드 엔드포인트는 5종에 한정.

---

## 👤 담당자

- **C** 주도 (API 마무리)
- **A** 협업 (SelfLearningAgent)
- **D** 협업 (WebSocket + observability)

---

## ✅ 작업 목록

### 1. `agents/self_learning.py` — SelfLearningAgent 본격 구현

```python
class SelfLearningAgent:
    """잡 종료 후 호출되어 3-Stack KB에 지식을 증류한다."""
    use_llm = False  # 임베딩만 사용

    def __init__(self):
        self.embedder = SentenceTransformer("sentence-transformers/all-mpnet-base-v2")

    @celery_app.task(name="distill_job", queue="harness")
    def distill(self, job_id: str):
        # 1. 잡 메타 수집
        state, runs, models, evals = self._load_job(job_id)
        category = state["category"]
        is_success = state["status"] == "completed" and (state.get("eval_result") or {}).get("passed")

        # 2. Layer1 — 구조화 KB
        if is_success:
            self._upsert_success_pattern(state, models)
            self._upsert_model_recipe(state, models[0])  # best_model
            self._upsert_eda_template(state, runs)
            self._upsert_hpo_warm_start(state, models)
        else:
            self._upsert_failure_lesson(state, runs, evals)

        # 3. Layer2 — 원시 아티팩트 (MinIO 영구화)
        self._archive_data_profile(job_id, state["data_profile"])
        self._archive_shap_values(job_id, state.get("explanations"))
        self._archive_learning_curves(job_id, models)
        self._archive_prompts_responses(job_id, runs)

        # 4. Layer3 — 의미 검색 임베딩
        self._embed_and_store_dataset(job_id, state)
        self._embed_and_store_intent(job_id, state)
        if not is_success:
            self._embed_and_store_lesson(job_id, runs, evals)

        # 5. distillation 로그
        self._log_distillation(job_id, is_success)
```

#### 1.1 `_upsert_success_pattern`

```python
def _upsert_success_pattern(self, state, models):
    config_snapshot = {
        "preprocessing_plan": state.get("preprocessing_plan"),
        "model_candidates": state.get("model_candidates"),
        "best_model_name": state["best_model"]["model_name"],
        "best_params": state["best_model"].get("hyperparameters"),
        "metrics": state["best_model"]["metrics"],
    }
    h = hashlib.sha256(json.dumps(config_snapshot, sort_keys=True).encode()).hexdigest()
    payload = config_snapshot
    emb = self.embedder.encode(self._summary_text(state, models)).tolist()
    # ON CONFLICT (hash) DO UPDATE
    db.execute(text("""
        INSERT INTO self_learning_kb (kb_type, category, hash, payload, embedding, source_job_ids)
        VALUES ('success_pattern', :cat, :hash, :payload, :emb, ARRAY[:jid]::uuid[])
        ON CONFLICT (hash) DO UPDATE
        SET success_count = self_learning_kb.success_count + 1,
            source_job_ids = self_learning_kb.source_job_ids || EXCLUDED.source_job_ids,
            updated_at = NOW()
    """), {"cat": state["category"], "hash": h, "payload": json.dumps(payload),
           "emb": emb, "jid": state["job_id"]})
```

#### 1.2 `_upsert_model_recipe`

- [ ] kb_type='recipe', payload에 모델명·하이퍼파라·전처리 핵심
- [ ] confidence는 메트릭에 비례 (val_f1≥0.85 → 0.9, ≥0.75 → 0.7, etc.)

#### 1.3 `_upsert_eda_template`

- [ ] EDA에서 생성된 차트 종류 + 어떤 차트가 인사이트에 활용됐는지
- [ ] kb_type='eda_template'

#### 1.4 `_upsert_hpo_warm_start`

- [ ] Optuna best_params 직접 저장. kb_type='hpo_warm_start'
- [ ] 다음 분석에서 `study.enqueue_trial(...)` 의 시드로 사용

#### 1.5 `_upsert_failure_lesson`

- [ ] 실패 분석. 어떤 단계에서 어떤 이유로 실패했는지 자연어 요약
- [ ] kb_type='failure_lesson', confidence 0.5 시작

#### 1.6 MinIO 아카이브 (Layer2)

- [ ] `self_learning/data_profiles/{job_id}.json` — profile dict 그대로
- [ ] `self_learning/shap_values/{job_id}.npy` — numpy 배열
- [ ] `self_learning/learning_curves/{job_id}.csv` — train/val loss/metric × epoch
- [ ] `self_learning/prompts/{job_id}/{agent_name}_{ts}.json` — 프롬프트-응답 페어 (LLM 미세조정용)

#### 1.7 임베딩 (Layer3)

- [ ] `dataset_embeddings`, `intent_embeddings`, `lesson_embeddings` 테이블 INSERT
- [ ] PII 마스킹된 텍스트만 임베딩 (R-502)

### 2. SelfLearningClient (Day3에서 정의, 여기서 완성)

```python
class SelfLearningClient:
    def fetch_similar_cases(self, intent_text, profile_summary, top_k=5):
        intent_emb = self.embedder.encode(intent_text).tolist()
        # 두 임베딩의 평균 (또는 concat)
        rows = db.execute(text("""
            SELECT dataset_embeddings.job_id, summary,
                   1 - (embedding <=> :emb) AS sim
            FROM dataset_embeddings
            WHERE 1 - (embedding <=> :emb) >= 0.75
            ORDER BY embedding <=> :emb
            LIMIT :k
        """), {"emb": intent_emb, "k": top_k}).fetchall()
        return [{"job_id": r.job_id, "summary": r.summary, "similarity": r.sim} for r in rows]

    def fetch_recipes(self, category, kb_types, top_k=10):
        rows = db.execute(text("""
            SELECT payload, confidence, success_count
            FROM self_learning_kb
            WHERE category = :cat AND kb_type = ANY(:types)
            ORDER BY confidence * LOG(success_count + 1) DESC
            LIMIT :k
        """), {"cat": category, "types": kb_types, "k": top_k}).fetchall()
        return [dict(r) for r in rows]

    def fetch_hpo_warm_start(self, category, model_name):
        ... # 상위 1건
```

### 3. FastAPI 엔드포인트 마무리

#### 3.1 v1 12개 (Day13에서 완성)
   `/upload`, `/profile`, `/pipeline/start`, `/pipeline/status`, `/results`, `/download`,
   `/predict`, `/models`, `/health`, `/rules`, `/telemetry/stats`, WebSocket

#### 3.2 v2 추가

- [ ] `POST /auth/*` (Day17)
- [ ] `POST /pipeline/{job_id}/decision`
- [ ] `GET /pipeline/{job_id}/awaiting`
- [ ] `GET /pipeline/{job_id}/checkpoints` — LangGraph 체크포인트 이력
- [ ] `POST /pipeline/{job_id}/resume` — 수동 재개
- [ ] `POST /pipeline/{job_id}/cancel`
- [ ] `GET /dashboard/agents`, `/jobs`, `/learning`, `/alarms`
- [ ] `GET /outputs/{job_id}`, `/outputs/{job_id}/{code}` (5종: OUT-01/02/03/04/07)
- [ ] `POST /admin/rules/{id}/approve`, `/admin/patches/{id}/approve`
- [ ] `GET /admin/users` (admin)
- [ ] `POST /admin/users/{id}/role` (admin)
- [ ] `GET /self_learning/cases/similar?intent=...&category=...` — RAG 테스트용
- [ ] `GET /error_kb/stats` (admin)

### 4. Pydantic 스키마 일괄 정의 (`api/schemas/v2.py`)

- [ ] `DecisionRequest`, `DecisionAck`, `AwaitingResponse`
- [ ] `AgentRegistryItem`, `AgentMatrixResponse`
- [ ] `LearningStatsResponse`, `AlarmItem`, `AlarmsResponse`
- [ ] `OutputItem`, `OutputsListResponse`
- [ ] `SimilarCaseItem`, `SimilarCasesResponse`

### 5. WebSocket 정리 (`api/routes/websocket.py`)

- [ ] Topic 구조:
  ```
  pipeline:{job_id}:progress    # 진행률
  pipeline:{job_id}:interrupt   # 게이트 인터럽트
  pipeline:{job_id}:complete    # 완료
  dashboard:agents               # 에이전트 매트릭스 실시간 (옵션)
  ```
- [ ] WS 연결 인증: 첫 메시지로 JWT 전송
- [ ] 클라이언트 끊김 처리, 30초 ping/pong

### 6. API 문서화 (Swagger / Redoc)

- [ ] FastAPI `tags_metadata` 작성 (Auth, Upload, Pipeline, Decision, Dashboard, Outputs, Admin, ErrorKB, Health)
- [ ] 각 엔드포인트에 `summary`, `description`, `response_model`, `responses` (예시 응답 포함)
- [ ] OpenAPI 스키마에 보안 정의 추가:
  ```python
  app.swagger_ui_oauth2_redirect_url = "/docs/oauth2-redirect"
  ```

### 7. 캐시 정책

- [ ] `/dashboard/*` 5초 cache (Redis)
- [ ] `/models` 30초 cache
- [ ] `/health` no-cache
- [ ] `/outputs/{job_id}` 60초 cache (산출물은 변하지 않음)

### 8. 비동기 잡 큐 모니터링

- [ ] `/admin/celery/queues` — 큐별 깊이 (pipeline/training/output/harness)
- [ ] `/admin/celery/workers` — 워커 상태 (`celery_app.control.inspect()`)

### 9. observability (옵션)

- [ ] OpenTelemetry traces → otel-collector (Day1 옵션 컨테이너)
- [ ] Prometheus metrics 노출: `/metrics` (FastAPI `prometheus-fastapi-instrumentator`)

### 10. 단위·통합 테스트

- [ ] `tests/test_api/test_v2_endpoints.py` — 신규 ~15개 엔드포인트 인증 + 권한 + 응답 스키마
- [ ] `tests/test_agents/test_self_learning.py`:
  - distill 호출 후 4개 kb_type 모두 INSERT 확인
  - 동일 잡 2회 distill 시 hash 충돌 → success_count 증가만
  - dataset_embedding pgvector 유사 검색 정확도
- [ ] `tests/integration/test_self_learning_cycle.py`:
  - 잡A 완료 → distill
  - 잡B (유사 데이터셋) 시작 → G1 응답에 `referenced_past_jobs: [잡A.id]` 포함

---

## 📁 생성/수정 파일 목록

| 경로 | 작업 |
|---|---|
| `agents/self_learning.py` | 완성 |
| `harness/self_learning_client.py` | 완성 (Day3 베이스 기반) |
| `api/routes/auth.py`, `decision.py`, `dashboard.py`, `outputs.py`, `admin.py`, `self_learning_test.py` | 완성 |
| `api/schemas/v2.py` | 신규 |
| `api/routes/websocket.py` | 강화 |
| `api/main.py` | tags_metadata + 미들웨어 등록 |
| `tests/test_agents/test_self_learning.py` | 신규 |
| `tests/integration/test_self_learning_cycle.py` | 신규 |
| `tests/test_api/test_v2_endpoints.py` | 신규 |

---

## 🔗 의존성 & 선행 조건

- Day2 KB 테이블 + pgvector
- Day3 SelfLearningClient 스텁
- Day14 EvalAgent에서 distill 큐 발행 훅
- Day17 인증 미들웨어
- 패키지: `sentence-transformers`, `pgvector`

---

## ✔️ 완료 기준

- [ ] distill_job 호출 → 4개 kb_type 모두 self_learning_kb INSERT 확인
- [ ] dataset_embeddings 누적 ≥ 5 (테스트 잡 5건 후)
- [ ] `GET /self_learning/cases/similar?intent=고객이탈예측` → 유사도 ≥ 0.75 결과 N건
- [ ] 잡A → 잡B (유사) 시 G1 응답의 `referenced_past_jobs` 비어있지 않음
- [ ] 동일 데이터셋 2회 실행 시 Optuna trial 수 ≥ 30% 감소 (KP7)
- [ ] FastAPI Swagger `/docs` 에서 ~25개 엔드포인트 모두 설명 + 예시 노출
- [ ] WebSocket 연결 후 게이트 인터럽트 메시지 정상 수신 (단위 테스트)

---

## ⚠️ 주의사항

- pgvector 임베딩 차원은 768d 고정. 모델 변경 시 데이터 마이그레이션 필요
- `sentence-transformers` 모델은 GPU 권장. CPU에서도 동작 (잡당 ~3초 추가)
- PII 마스킹 누락된 텍스트가 임베딩에 들어가지 않도록 R-502 강제 (입력 직전 한 번 더 마스킹 확인)
- harness 큐 워커가 1개만 있으면 distill 적체 가능 — 모니터링 후 증설 결정
- distill 실패해도 잡 자체는 success/fail 상태 보존 (학습 실패는 사용자 경험에 영향 X)

---

## 🆕 v2.2 보강 (감사 보고서 2026-05-19 반영)

> 출처: `ADA_v2_감사보고서.docx`. 본 섹션이 v2.1 본문과 충돌 시 **v2.2가 우선**한다.

### 1) KB → 코드 인용 위치 명시 (Day-B 연계)
- 5개 kb_type 의 인용 위치를 `docs/architecture/kb_consumption_map.md` 단일 권위로 명시.
- G1·ModelSelection·HPO·EDA·전처리 5개 위치에서 SelfLearningClient.fetch_recipes() 호출 강제 (R-501).

### 2) record_outcome 의무 (R-503)
- SelfLearningAgent.distill() 직전에 cited KB IDs 수집 + record_outcome 호출.

### 3) 삭제 권리 엔드포인트 (PIPA)
- /admin/users/{id}/purge — 사용자 데이터·임베딩·산출물·세션·결정 일괄 삭제. audit_log 만 보존.

### 4) job_cost_metrics 테이블
- 잡별 Anthropic API 토큰·달러·CPU/GPU 시간 집계. /admin/cost 대시보드.

### 5) PII 임베딩 사전 검증 (R-502 강제)
- distill_job 이 임베딩 전 데이터에 PII 패턴 매칭 시 raise.

### 6) Day-B 와 인터페이스 매핑
- gate_recommendation_shadow 테이블 INSERT 위치는 /decision/{job_id} 엔드포인트.

### 완료 기준 추가
- [ ] kb_consumption_map.md 5개 매핑 단위 테스트
- [ ] /admin/users/{id}/purge → 관련 모든 테이블 0 rows
- [ ] job_cost_metrics 집계 정확도

---

## 🧰 v2.3 도구 보강 (도구 카탈로그 2026-05-19 반영)

> 출처: `TOOL_CATALOG_2026.md`. 본 섹션은 Day-D / Day-E / v3_backlog 의 도구를 본 Day 의 코드 위치에 매핑한다.

### 적용 도구
- **Arize Phoenix** (🟢 v3 백로그 A.4) — pgvector 임베딩 분포·드리프트 자동 시각화. R-1104 백로그.
- **Galileo** (⚪ v3 백로그 B.5) — InsightAgent 출력 품질·할루시네이션 감시.
- **Qdrant** (⚪ v3 백로그 B.1) — pgvector 한계 도달 시 마이그레이션.

### v2.3 (현재)
- SelfLearningAgent 가 임베딩 export 인터페이스(`distill_to_phoenix()`)만 노출 — 실제 Phoenix 연동은 v3.0.
- KB → 코드 인용 매핑(Day-B)에 추가하여 도구별 적용 위치 명시.

---

# 📦 통합본 (v2.4) — 원래 Day-B: 자가학습 사이클 폐쇄 + Stage 1

> 통합일: 2026-05-19 (v2.4)
> 원래 `Day-B_자가학습폐쇄.md` 의 본문 전체. 신설 Day-B 파일은 v2.4 부터 본 Day19 안의 § 섹션으로 흡수되었다.
> 자가학습 사이클 폐쇄는 본 Day19 (API + SelfLearning 통합) 의 자연스러운 확장으로 단일 권위.

