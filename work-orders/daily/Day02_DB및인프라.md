# Day 2 — PostgreSQL DB + 인프라 완성
> 프로젝트: Adaptive AutoAI Pipeline Agent | 2주 스프린트 Day 2/14

---

## 📋 오늘의 목표

Day 1에서 기동된 PostgreSQL 컨테이너 위에 10개 핵심 테이블 DDL과 10개 인덱스를 포함한 마이그레이션 스크립트를 완성한다. SQLAlchemy 비동기 엔진(AsyncSession)을 포함한 `shared/db.py`를 작성하여 API/Worker에서 공통으로 사용할 DB 레이어를 구축한다. MinIO 버킷(`autoai-artifacts`) 생성과 MLflow 실험 초기화까지 완료하여 Day 3 공통 모듈 작업의 기반을 마련한다.

---

## 👤 담당자

- **C** 주도 (전체 작업)
- 코드 리뷰: A (shared/db.py 비동기 패턴 검토)
- MinIO/MLflow 초기화 검증: D

---

## ✅ 작업 목록

### 1. migrations/001_initial.sql 작성 — 10개 테이블 DDL

- [ ] **users** 테이블 생성
  - `id UUID PRIMARY KEY DEFAULT uuid_generate_v4()`
  - `email VARCHAR(255) UNIQUE NOT NULL`
  - `created_at TIMESTAMPTZ DEFAULT NOW()`

- [ ] **uploads** 테이블 생성
  - `id UUID PRIMARY KEY DEFAULT uuid_generate_v4()`
  - `user_id UUID REFERENCES users(id) ON DELETE SET NULL`
  - `file_id VARCHAR(64) UNIQUE NOT NULL` — MinIO 오브젝트 키
  - `filename VARCHAR(512) NOT NULL`
  - `sha256 CHAR(64) NOT NULL` — 파일 중복 탐지
  - `size_bytes BIGINT NOT NULL`
  - `minio_path VARCHAR(1024) NOT NULL`
  - `category VARCHAR(64)` — tabular_ml / tabular_dl / timeseries / anomaly_detection
  - `status VARCHAR(32) DEFAULT 'uploaded'`
  - `created_at TIMESTAMPTZ DEFAULT NOW()`

- [ ] **jobs** 테이블 생성
  - `id UUID PRIMARY KEY DEFAULT uuid_generate_v4()`
  - `user_id UUID REFERENCES users(id) ON DELETE SET NULL`
  - `file_id VARCHAR(64) NOT NULL`
  - `category VARCHAR(64) NOT NULL`
  - `target_column VARCHAR(255)`
  - `user_question TEXT`
  - `status VARCHAR(32) DEFAULT 'pending'` — pending/running/completed/failed
  - `retry_count INT DEFAULT 0`
  - `error_message TEXT`
  - `created_at TIMESTAMPTZ DEFAULT NOW()`
  - `updated_at TIMESTAMPTZ DEFAULT NOW()`

- [ ] **agent_runs** 테이블 생성
  - `id UUID PRIMARY KEY DEFAULT uuid_generate_v4()`
  - `job_id UUID REFERENCES jobs(id) ON DELETE CASCADE`
  - `agent_name VARCHAR(128) NOT NULL`
  - `status VARCHAR(32) NOT NULL` — running/completed/failed
  - `input_tokens INT DEFAULT 0`
  - `output_tokens INT DEFAULT 0`
  - `duration_ms INT`
  - `error TEXT`
  - `created_at TIMESTAMPTZ DEFAULT NOW()`

- [ ] **models** 테이블 생성
  - `id UUID PRIMARY KEY DEFAULT uuid_generate_v4()`
  - `job_id UUID REFERENCES jobs(id) ON DELETE CASCADE`
  - `model_name VARCHAR(128) NOT NULL` — RandomForest / XGBoost 등
  - `framework VARCHAR(64) NOT NULL` — sklearn / xgboost / pytorch
  - `metrics JSONB` — {val_accuracy, val_f1, val_rmse 등}
  - `minio_path VARCHAR(1024)`
  - `mlflow_run_id VARCHAR(64)`
  - `is_best BOOLEAN DEFAULT FALSE`
  - `created_at TIMESTAMPTZ DEFAULT NOW()`

- [ ] **experiments** 테이블 생성
  - `id UUID PRIMARY KEY DEFAULT uuid_generate_v4()`
  - `job_id UUID REFERENCES jobs(id) ON DELETE CASCADE`
  - `mlflow_experiment_id VARCHAR(64)`
  - `category VARCHAR(64) NOT NULL`
  - `status VARCHAR(32) DEFAULT 'created'`
  - `created_at TIMESTAMPTZ DEFAULT NOW()`

- [ ] **artifacts** 테이블 생성
  - `id UUID PRIMARY KEY DEFAULT uuid_generate_v4()`
  - `job_id UUID REFERENCES jobs(id) ON DELETE CASCADE`
  - `artifact_type VARCHAR(64) NOT NULL` — ppt / pdf / chart / script
  - `minio_path VARCHAR(1024) NOT NULL`
  - `created_at TIMESTAMPTZ DEFAULT NOW()`

- [ ] **failure_logs** 테이블 생성
  - `id UUID PRIMARY KEY DEFAULT uuid_generate_v4()`
  - `job_id UUID REFERENCES jobs(id) ON DELETE CASCADE`
  - `error_hash VARCHAR(64) NOT NULL` — 동일 오류 그룹핑용 SHA256
  - `error_category VARCHAR(64)` — data_quality / model_error / timeout 등
  - `error_message TEXT`
  - `stack_trace TEXT`
  - `proposed_rule TEXT` — LLM이 제안한 룰 텍스트
  - `confidence FLOAT` — 제안 신뢰도 0.0~1.0
  - `created_at TIMESTAMPTZ DEFAULT NOW()`

- [ ] **success_patterns** 테이블 생성
  - `id UUID PRIMARY KEY DEFAULT uuid_generate_v4()`
  - `category VARCHAR(64) NOT NULL`
  - `pattern_hash VARCHAR(64) UNIQUE NOT NULL`
  - `description TEXT`
  - `config JSONB` — 성공한 파이프라인 설정 스냅샷
  - `success_count INT DEFAULT 1`
  - `created_at TIMESTAMPTZ DEFAULT NOW()`

- [ ] **rules** 테이블 생성
  - `id UUID PRIMARY KEY DEFAULT uuid_generate_v4()`
  - `rule_code VARCHAR(16) UNIQUE NOT NULL` — R-001, R-101 등
  - `title VARCHAR(255) NOT NULL`
  - `description TEXT`
  - `category VARCHAR(64)` — data / model / training / harness
  - `confidence FLOAT DEFAULT 1.0`
  - `is_active BOOLEAN DEFAULT TRUE`
  - `author VARCHAR(128)` — human / llm / system
  - `created_at TIMESTAMPTZ DEFAULT NOW()`

### 2. 10개 인덱스 생성

- [ ] `idx_uploads_user` — `uploads(user_id)` B-Tree
- [ ] `idx_uploads_sha256` — `uploads(sha256)` B-Tree (중복 파일 탐지)
- [ ] `idx_jobs_user` — `jobs(user_id)` B-Tree
- [ ] `idx_jobs_status` — `jobs(status)` B-Tree (상태별 조회)
- [ ] `idx_agent_runs_job` — `agent_runs(job_id)` B-Tree
- [ ] `idx_agent_runs_agent` — `agent_runs(agent_name)` B-Tree
- [ ] `idx_models_job` — `models(job_id)` B-Tree
- [ ] `idx_failure_logs_hash` — `failure_logs(error_hash)` B-Tree
- [ ] `idx_success_patterns_hash` — `success_patterns(pattern_hash)` B-Tree (UNIQUE)
- [ ] `idx_rules_active` — `rules(is_active, category)` 복합 B-Tree

### 3. shared/db.py 작성

- [ ] `create_async_engine` 설정
  - `DATABASE_URL`에서 `postgresql://` → `postgresql+asyncpg://` 자동 변환
  - `pool_size=20`, `max_overflow=10`, `pool_timeout=30`, `pool_pre_ping=True`
- [ ] `AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)`
- [ ] `get_db()` 비동기 제너레이터 구현 (FastAPI Depends 사용용)
- [ ] `Base = declarative_base()` 선언
- [ ] `init_db()` 비동기 함수: 테이블 존재 여부 확인 후 마이그레이션 실행

### 4. SQLAlchemy ORM 모델 작성 (shared/models.py)

- [ ] `Upload`, `Job`, `AgentRun`, `Model`, `Experiment`, `Artifact`, `FailureLog`, `SuccessPattern`, `Rule` ORM 클래스 작성
- [ ] 각 모델에 `__tablename__` 및 컬럼 타입 매핑
- [ ] `Job` 모델에 `@property` 로 `is_running` / `is_terminal` 헬퍼 추가
- [ ] `updated_at` 컬럼에 `onupdate=datetime.utcnow` 설정

### 5. MinIO 버킷 생성 확인

- [ ] `docker exec minio mc alias set local http://minio:9000 minioadmin minioadmin`
- [ ] `mc mb local/autoai-artifacts` 버킷 생성
- [ ] 버킷 정책 설정: 내부 서비스만 읽기/쓰기 가능 (퍼블릭 접근 차단)
- [ ] `mc ls local/autoai-artifacts` 로 버킷 존재 확인
- [ ] `tools/minio_setup.py` 스크립트 작성: 앱 시작 시 버킷 자동 생성 보장

### 6. MLflow Experiment 초기화

- [ ] `mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)` 설정
- [ ] Default Experiment 외 카테고리별 실험 사전 생성:
  - `ada-tabular-ml`, `ada-tabular-dl`, `ada-timeseries`, `ada-anomaly`
- [ ] `scripts/mlflow_init.py` 스크립트 작성 (실험 초기화 자동화)
- [ ] MLflow UI(http://localhost:5000)에서 4개 실험 목록 확인

### 7. Alembic 마이그레이션 설정 (선택, Day 3 이전 완료 권장)

- [ ] `alembic init alembic` 실행
- [ ] `alembic/env.py` — 비동기 엔진 연동 설정
- [ ] `alembic/versions/001_initial.py` — 001_initial.sql 내용을 Alembic 버전으로 변환
- [ ] `alembic upgrade head` 실행 성공 확인

---

## 🏗️ 구현 명세

### shared/db.py 핵심 구조

```python
# shared/db.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from shared.config import settings

# postgresql:// → postgresql+asyncpg:// 자동 변환
_url = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

engine = create_async_engine(
    _url,
    pool_size=20,
    max_overflow=10,
    pool_timeout=30,
    pool_pre_ping=True,
    echo=settings.LOG_LEVEL == "DEBUG",
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


async def get_db():
    """FastAPI Depends 전용 비동기 세션 제너레이터"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """애플리케이션 시작 시 DB 테이블 초기화"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

### migrations/001_initial.sql 전체 구조 예시 (users + jobs)

```sql
-- migrations/001_initial.sql
-- 실행 전 extensions 확인
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- 1. users
CREATE TABLE IF NOT EXISTS users (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email       VARCHAR(255) UNIQUE NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 2. uploads
CREATE TABLE IF NOT EXISTS uploads (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
    file_id     VARCHAR(64) UNIQUE NOT NULL,
    filename    VARCHAR(512) NOT NULL,
    sha256      CHAR(64) NOT NULL,
    size_bytes  BIGINT NOT NULL,
    minio_path  VARCHAR(1024) NOT NULL,
    category    VARCHAR(64),
    status      VARCHAR(32) DEFAULT 'uploaded',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- (이하 8개 테이블 동일 패턴으로 작성)

-- 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_uploads_user    ON uploads(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_uploads_sha256 ON uploads(sha256);
CREATE INDEX IF NOT EXISTS idx_jobs_user       ON jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status     ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_agent_runs_job  ON agent_runs(job_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_agent ON agent_runs(agent_name);
CREATE INDEX IF NOT EXISTS idx_models_job      ON models(job_id);
CREATE INDEX IF NOT EXISTS idx_failure_logs_hash ON failure_logs(error_hash);
CREATE UNIQUE INDEX IF NOT EXISTS idx_success_patterns_hash ON success_patterns(pattern_hash);
CREATE INDEX IF NOT EXISTS idx_rules_active    ON rules(is_active, category);
```

### shared/models.py ORM 클래스 시그니처

```python
class Job(Base):
    __tablename__ = "jobs"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id       = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    file_id       = Column(String(64), nullable=False)
    category      = Column(String(64), nullable=False)
    target_column = Column(String(255))
    user_question = Column(Text)
    status        = Column(String(32), default="pending")
    retry_count   = Column(Integer, default=0)
    error_message = Column(Text)
    created_at    = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)
    updated_at    = Column(TIMESTAMP(timezone=True), default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    agent_runs = relationship("AgentRun", back_populates="job", cascade="all, delete")
    models     = relationship("Model", back_populates="job", cascade="all, delete")

    @property
    def is_running(self) -> bool:
        return self.status == "running"

    @property
    def is_terminal(self) -> bool:
        return self.status in ("completed", "failed")
```

### tools/minio_setup.py 버킷 초기화 스크립트

```python
# tools/minio_setup.py
import boto3
from botocore.exceptions import ClientError
from shared.config import settings

def ensure_bucket_exists(bucket_name: str = settings.MINIO_BUCKET) -> None:
    s3 = boto3.client(
        "s3",
        endpoint_url=f"http://{settings.MINIO_ENDPOINT}",
        aws_access_key_id=settings.MINIO_ACCESS_KEY,
        aws_secret_access_key=settings.MINIO_SECRET_KEY,
    )
    try:
        s3.head_bucket(Bucket=bucket_name)
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            s3.create_bucket(Bucket=bucket_name)
```

### scripts/mlflow_init.py 실험 초기화

```python
# scripts/mlflow_init.py
import mlflow
from shared.config import settings

CATEGORIES = ["tabular-ml", "tabular-dl", "timeseries", "anomaly"]

def init_experiments():
    mlflow.set_tracking_uri(settings.MLFLOW_TRACKING_URI)
    for cat in CATEGORIES:
        exp_name = f"ada-{cat}"
        exp = mlflow.get_experiment_by_name(exp_name)
        if exp is None:
            mlflow.create_experiment(
                exp_name,
                artifact_location=f"s3://{settings.MINIO_BUCKET}/mlflow/{cat}",
            )
            print(f"Created experiment: {exp_name}")
        else:
            print(f"Experiment already exists: {exp_name}")

if __name__ == "__main__":
    init_experiments()
```

---

## 📁 생성/수정 파일 목록

```
프로젝트 루트/
├── migrations/
│   └── 001_initial.sql             # 10개 테이블 DDL + 10개 인덱스
├── shared/
│   ├── db.py                       # SQLAlchemy 비동기 엔진 및 세션
│   └── models.py                   # ORM 클래스 (10개 테이블 매핑)
├── tools/
│   └── minio_setup.py              # MinIO 버킷 초기화 스크립트
├── scripts/
│   └── mlflow_init.py              # MLflow 실험 초기화 스크립트
└── alembic/                        # (선택) Alembic 마이그레이션
    ├── env.py
    ├── alembic.ini
    └── versions/
        └── 001_initial.py
```

---

## 🔗 의존성 & 선행 조건

- **Day 1 완료 필수**: docker compose ps 에서 postgres, minio, mlflow 컨테이너 healthy 상태
- `uuid-ossp` 익스텐션이 autoai DB에 설치되어 있어야 함 (docker/init.sql에서 처리)
- asyncpg 드라이버 설치 확인 (`pip show asyncpg`)
- boto3 설치 확인 (`pip show boto3`)
- mlflow 패키지 설치 확인 (`pip show mlflow`)
- MinIO 서비스 정상 기동 및 콘솔 접근 가능 상태

---

## ✔️ 완료 기준 (Done Criteria)

- [ ] `psql -U autoai -d autoai -c "\dt"` 실행 결과 10개 테이블 목록 확인
- [ ] `psql -U autoai -d autoai -c "\di"` 실행 결과 10개 인덱스 목록 확인
- [ ] `python -c "from shared.db import engine; print('DB OK')"` 성공
- [ ] `python -c "from shared.models import Job; print(Job.__tablename__)"` 성공
- [ ] `python tools/minio_setup.py` 실행 후 MinIO 콘솔에서 `autoai-artifacts` 버킷 확인
- [ ] `python scripts/mlflow_init.py` 실행 후 MLflow UI에서 4개 실험 목록 확인
- [ ] `psql -U autoai -d mlflow -c "\dt"` 에서 MLflow 내부 테이블 생성 확인
- [ ] 비동기 세션 테스트: `async with AsyncSessionLocal() as s: print(await s.execute(text("SELECT 1")))`

---

## ⚠️ 주의사항 & 제약

### AGENTS.md 룰 (Day 2 적용)

- **R-101**: DB 스키마 변경(컬럼 추가/삭제/타입 변경)은 반드시 마이그레이션 파일로 관리. 직접 DDL 실행 금지
- **R-102**: `models.metrics` JSONB 컬럼은 구조를 자유롭게 사용하되, 반드시 `shared/schemas/metrics.py`에 Pydantic 검증 모델 정의 필요
- **R-103**: 민감 데이터(이메일 등)는 로그에 절대 출력하지 않음

### 아키텍처 제약

- ORM 모델(`shared/models.py`)은 공통 패키지. 개인 작업 폴더에 복사본 생성 금지
- `get_db()` 제너레이터는 FastAPI 라우터에서만 사용. Celery 태스크에서는 `AsyncSessionLocal()` 직접 사용
- `pool_size=20`은 `max_connections=200` 기준 API 10개 인스턴스 기준 설정. 스케일 시 재검토 필요
- MLflow 실험 이름 형식은 `ada-{category}` 고정. 임의 변경 금지
- MinIO 버킷명 `autoai-artifacts` 고정. 서브 디렉토리 구조는 `{category}/{job_id}/{파일명}` 형식 사용

### 성능 주의사항

- `pool_pre_ping=True` 설정으로 끊어진 커넥션 자동 재연결 보장
- JSONB 컬럼(`metrics`, `config`) 에 대한 GIN 인덱스는 필요 시 추가 (현재 미포함, 조회 패턴 확인 후 결정)
- `pg_trgm` 익스텐션은 `failure_logs.error_message` 유사 오류 검색을 위해 설치. 이후 활용 예정

### 마이그레이션 주의사항

- `001_initial.sql` 은 `IF NOT EXISTS` 절 포함하여 멱등성(idempotency) 보장
- Alembic 사용 시 `alembic downgrade` 는 개발 환경에서만 허용. 스테이징/프로덕션 적용 금지
- 스키마 변경 PR은 반드시 C와 A 양쪽의 리뷰 승인 필요

---

## 🆕 v2 확장 작업 (마스터 설계서 §11 참조)

> Day2는 v2의 **DB 골격 전체**를 한 번에 깔아둔다. v1의 10테이블에 더해 14개 신규 테이블과 pgvector 인덱스, RLS 정책까지 일괄 도입.

### 1. `migrations/002_v2_schema.sql` — 신규 15개 테이블 + ALTER

> 마스터 §11.1 의 테이블 권위 목록과 동일하게 만든다. 자체학습 KB 는 **단일 `self_learning_kb`** 로 통합 (kb_type 컬럼으로 5개 유형 구분). 별도의 `success_patterns_v2 / model_recipes / eda_templates / hpo_warm_starts / failure_lessons` 테이블은 만들지 **않는다** — 그것들은 모두 `self_learning_kb.kb_type` 의 값 partition 일 뿐이다.

- [ ] **`agent_registry`** (마스터 §4.2 명세) — v2에서 신규 컬럼 추가:
  ```sql
  -- §4.2 기본 컬럼에 더해:
  persona       TEXT NOT NULL DEFAULT '',         -- 마스터 §4.3 의 1줄 페르소나 (한국어, ≤200자)
  persona_version VARCHAR(16) DEFAULT 'v2.0',     -- 페르소나 변경 이력 추적
  CONSTRAINT chk_persona_len CHECK (char_length(persona) <= 200)
  ```
  - `persona` 는 시드 시점에 `agents/personas.py` 의 PERSONAS 딕셔너리에서 채운다 (Day03 §1.5 참조)
  - 변경 시 `persona_version` 도 함께 bump (R-007)
- [ ] **`interactive_sessions`** — HITL 게이트 응답 이력
  ```sql
  CREATE TABLE interactive_sessions (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id      UUID REFERENCES jobs(id) ON DELETE CASCADE,
    gate        VARCHAR(8) NOT NULL,          -- 'G0'..'G5'
    proposals   JSONB,                         -- 시스템이 제시한 안들
    user_choice JSONB,                         -- 사용자가 선택한 안
    auto_resolved BOOLEAN DEFAULT FALSE,
    response_latency_sec INTEGER,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
  );
  CREATE INDEX idx_isession_job_gate ON interactive_sessions(job_id, gate);
  ```
- [ ] **`decisions`** — 채택된 안의 메타 (KP11 측정용)
  ```sql
  CREATE TABLE decisions (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id   UUID REFERENCES interactive_sessions(id) ON DELETE CASCADE,
    adopted_rank INTEGER,                   -- 사용자가 몇 순위 안을 골랐나
    rationale    TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
  );
  ```
- [ ] **`self_learning_kb`** — 5종 KB 유형 통합 단일 테이블 (마스터 §11.1 권위)
  ```sql
  CREATE TABLE self_learning_kb (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    kb_type     VARCHAR(32) NOT NULL,    -- 'success_pattern'|'recipe'|'eda_template'|'hpo_warm_start'|'failure_lesson'
    category    VARCHAR(64),
    hash        CHAR(64) UNIQUE,
    payload     JSONB NOT NULL,
    embedding   VECTOR(768),              -- pgvector
    success_count INT DEFAULT 1,
    confidence  FLOAT DEFAULT 0.5,
    source_job_ids UUID[],
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
  );
  CREATE INDEX idx_kb_type_cat ON self_learning_kb(kb_type, category);
  CREATE INDEX idx_kb_emb ON self_learning_kb USING ivfflat (embedding vector_cosine_ops) WITH (lists=100);
  ```
- [ ] **`dataset_embeddings`** (§11.3 명세)
- [ ] **`intent_embeddings`** 동형 구조 (target은 사용자 의도 텍스트)
- [ ] **`lesson_embeddings`** 동형 구조 (target은 failure_lessons 텍스트)
- [ ] **`error_kb`** (§6.4 명세)
- [ ] **`security_audit_log`** (§10.6 명세)
- [ ] **`outputs`** — 산출물 인벤토리
  ```sql
  CREATE TABLE outputs (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id      UUID REFERENCES jobs(id) ON DELETE CASCADE,
    output_code VARCHAR(16) NOT NULL,        -- 'OUT-01'..'OUT-04' | 'OUT-07'
    minio_path  VARCHAR(1024) NOT NULL,
    file_size_bytes BIGINT,
    generation_ms INTEGER,
    status      VARCHAR(16) DEFAULT 'completed',
    created_at  TIMESTAMPTZ DEFAULT NOW()
  );
  CREATE INDEX idx_outputs_job ON outputs(job_id);
  ```
- [ ] **`pending_patches`** — AutoErrorHandler 가 만든 미적용 패치 큐
  ```sql
  CREATE TABLE pending_patches (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    error_kb_id UUID REFERENCES error_kb(id),
    patch_diff  TEXT,
    test_plan   TEXT,
    confidence  FLOAT,
    review_status VARCHAR(16) DEFAULT 'pending',  -- pending|approved|rejected
    reviewer    VARCHAR(128),
    created_at  TIMESTAMPTZ DEFAULT NOW()
  );
  ```
- [ ] **`job_distillation_log`** — Self-learning 실행 로그
- [ ] **`output_recipes`** — 사용자 의도 ↔ 추천 산출물 매핑 학습용
- [ ] **`gate_decision_metrics`** — KP11 계산용 집계 뷰

### 2. 기존 테이블 ALTER

- [ ] `users` 추가 컬럼: `role VARCHAR(16) DEFAULT 'analyst'`, `password_hash VARCHAR(128)`, `last_login_at TIMESTAMPTZ`, `is_active BOOLEAN DEFAULT TRUE`, `mfa_secret TEXT`
- [ ] `uploads` 추가: `original_mime`, `pii_scan_status`, `pii_columns JSONB`
- [ ] `jobs` 추가: `current_gate VARCHAR(8)`, `auto_resolved BOOLEAN DEFAULT FALSE`, `requested_outputs JSONB`, `user_intent TEXT`
- [ ] `agent_runs` 추가: `gate VARCHAR(8)`, `was_re_loop BOOLEAN DEFAULT FALSE`
- [ ] `rules` 추가: `pgvector_embedding VECTOR(768)`, `version VARCHAR(16) DEFAULT '1.0.0'`, `superseded_by UUID REFERENCES rules(id)`
- [ ] `failure_logs` 추가: `auto_handled_by_kb BOOLEAN DEFAULT FALSE`, `error_kb_id UUID REFERENCES error_kb(id)`

### 3. `migrations/003_pgvector_setup.sql`

- [ ] `CREATE EXTENSION IF NOT EXISTS vector;` (Day01에서 이미 처리, 멱등)
- [ ] 위 임베딩 컬럼들 IVFFlat 인덱스 추가
- [ ] `lists` 파라미터: 데이터 1만 미만 50, 10만 미만 100, 그 이상 sqrt(N)

### 4. `migrations/004_security_baseline.sql` — RLS + 컬럼 암호화

- [ ] `CREATE EXTENSION IF NOT EXISTS pgcrypto;`
- [ ] `users.email` 암호화 컬럼 패턴 적용 (애플리케이션 레벨에서 `pgp_sym_encrypt/decrypt`)
- [ ] `jobs` 테이블 RLS:
  ```sql
  ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
  CREATE POLICY jobs_owner_select ON jobs FOR SELECT
    USING (user_id = current_setting('app.current_user_id')::UUID);
  ```
- [ ] `app.current_user_id` 는 API 진입 시 SQLAlchemy 미들웨어가 설정

### 5. `migrations/005_seed_agent_registry.sql`

- [ ] **정확히 26개** 에이전트 메타데이터 INSERT (마스터 §4.1 합계표 권위)
  - 출력 생성기(`PresentationGenerator`/`PDFGenerator`/`DashboardArtifactGenerator` 등 13종)는 **유틸리티 클래스이며 등록하지 않는다**
  - `DashboardOrchestratorAgent` 라는 이름은 사용하지 않는다 — 대시보드는 `api/services/dashboard.py` 서비스 레이어가 제공하므로 등록 대상 아님
  - 시드 SQL은 `scripts/seed_agent_registry.py` 로 작성. 페르소나는 `agents.personas.PERSONAS` 에서 임포트하여 INSERT 시 함께 채움
  ```sql
  INSERT INTO agent_registry (agent_name, role, description, llm_model, persona, inputs, outputs, capabilities) VALUES
    -- I 슈퍼바이저 (1)
    ('SupervisorAgent', 'supervisor', '입력 검증 및 task 분류', 'claude-sonnet-4-6',
     '["file_id","category","user_intent"]'::jsonb,
     '["task","next_agent"]'::jsonb,
     '["intent_classification"]'::jsonb),
    -- A 입력·검증 (3)
    ('IntentElicitorAgent','gate','G0 — 자유 의도 텍스트를 구조화','claude-sonnet-4-6',...),
    ('DataProfilerAgent','data','데이터 프로파일링','none',...),
    ('SchemaValidatorAgent','data','스키마 검증','none',...),
    -- B 의사결정 제안 (5 게이트)
    ('AnalysisProposerAgent','gate','G1 — 3안 제시','claude-opus-4-7',...),
    ('MethodologyProposerAgent','gate','G2 — 방법론 제안','claude-sonnet-4-6',...),
    ('ModelStrategyProposerAgent','gate','G3 — 모델 전략 제안','claude-opus-4-7',...),
    ('ModelComparisonReporterAgent','gate','G4 — Top-3 비교','none',...),
    ('OutputTypeSelectorAgent','gate','G5 — 산출물 추천','claude-sonnet-4-6',...),
    -- C 전처리·EDA (3) + preprocessing_choice 미니
    ('PreprocessingStrategistAgent','data','전처리 계획','claude-sonnet-4-6',...),
    ('FeatureEngineerAgent','data','피처 엔지니어링','none',...),
    ('EDAAgent','data','EDA 시각화','none',...),
    ('PreprocessingChoiceAgent','gate','전처리 미니 게이트','none',...),
    -- D 모델링 (5) + fine_tune_executor
    ('ModelSelectionAgent','modeling','Top-3 후보 선정','claude-sonnet-4-6',...),
    ('HyperparameterTunerAgent','modeling','Optuna 탐색','none',...),
    ('TrainingExecutorAgent','modeling','학습 실행','none',...),
    ('TrainingMonitorAgent','modeling','학습 모니터링','none',...),
    ('MetricsAggregatorAgent','modeling','메트릭 집계','none',...),
    ('FineTuneExecutorAgent','modeling','트랜스포머 최종 튜닝','none',...),
    -- E 평가·해석 (3)
    ('EvalAgent','eval','품질 평가','claude-opus-4-7',...),
    ('ExplainabilityAgent','eval','SHAP / 시계열 분해','none',...),
    ('InsightAgent','eval','비즈니스 인사이트','claude-opus-4-7',...),
    -- F 산출물 오케스트레이터 (1)
    ('ReportComposerAgent','output','산출물 fan-out','none',...),
    -- G 메타 (3)
    ('SelfLearningAgent','meta','KB 증류','none',...),
    ('AutoErrorHandlerAgent','meta','자동 오류 처리','none',...),
    ('SecurityGuardAgent','meta','보안 가드','none',...),
    -- H 회복 (1)
    ('ErrorRecoveryAgent','recovery','최후 회복','claude-opus-4-7',...);
  -- TOTAL: 1+3+5+4+6+3+1+3+1 = 27 행
  ```
  *(주: 위 시드는 27 행이다. `preprocessing_choice` 와 `fine_tune_executor` 를 등록하면 27, 등록하지 않으면 25. 마스터 §4.1 의 합계표 "26 + preprocessing_choice 또는 fine_tune_executor" 와 일치하도록 한 쪽만 시드. 본 스프린트는 둘 다 시드 → 27 행. Day14 v2 done criteria 와 Day18 매트릭스도 "27" 로 정정.)*

### 6. ORM 모델 v2 (`shared/models_v2.py`)

- [ ] 신규 클래스: `AgentRegistry`, `InteractiveSession`, `Decision`, `SelfLearningKB`, `DatasetEmbedding`, `IntentEmbedding`, `LessonEmbedding`, `ErrorKB`, `SecurityAuditLog`, `Output`, `PendingPatch`, `JobDistillationLog`
- [ ] pgvector 컬럼은 `pgvector.sqlalchemy.Vector(768)` 타입 사용 (의존성: `pgvector` Python 패키지)

### 7. MinIO 버킷 구조 v2

- [ ] 기존 `autoai-artifacts` 안에 신규 prefix 추가:
  ```
  ada-artifacts/
    uploads/{file_id}/...
    profiles/{job_id}.json
    eda/{job_id}/*.png
    models/{job_id}/...
    explanations/{job_id}/...
    outputs/{job_id}/{output_code}/...
    self_learning/
        data_profiles/{job_id}.json
        shap_values/{job_id}.npy
        learning_curves/{job_id}.csv
        prompts/{job_id}/...
    patches/{patch_id}/...   # claude-cli 응답 산출 패치
  ```

### 8. 완료 기준 (v2 추가)

- [ ] `\dt` 결과 테이블 수 ≥ 24 (v1 10 + v2 14)
- [ ] `SELECT count(*) FROM agent_registry;` = 31
- [ ] `\d+ jobs` 출력에 신규 컬럼 5개 포함
- [ ] `EXPLAIN ANALYZE` 로 IVFFlat 인덱스 사용 확인
- [ ] RLS 테스트: 다른 user_id 로 SET 후 다른 사용자 job 조회 시 0행 반환

### 9. 주의사항 (v2)

- pgvector IVFFlat 인덱스는 데이터가 일정 수준 누적된 뒤 `REINDEX` 필요 (운영 중 cron)
- `self_learning_kb.hash` 충돌 시 INSERT … ON CONFLICT (hash) DO UPDATE SET success_count=success_count+1 패턴 사용
- security_audit_log 는 별도 파티셔닝 검토 (월 단위, Day17 결정)
- RLS는 슈퍼유저(`autoai`) 제외. 워커에서 슈퍼유저로 접근 시 RLS 우회됨 — Day17에서 워커 전용 role 분리
