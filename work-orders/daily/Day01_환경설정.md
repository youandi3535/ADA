# Day 1 — Docker 환경 설정
> 프로젝트: Adaptive AutoAI Pipeline Agent | 2주 스프린트 Day 1/14

---

## 📋 오늘의 목표

Docker Compose 기반으로 8개 서비스(frontend, api, worker, redis, postgres, mlflow, serving, minio)를 정의하고 전부 기동시킨다. 각 서비스별 Dockerfile을 작성하고, 환경 변수 템플릿(.env.example)과 DB 초기화 스크립트(docker/init.sql)를 완비한다. 스프린트 종료 시점에 `docker compose ps` 실행 결과 8개 컨테이너가 모두 Up/healthy 상태여야 한다.

---

## 👤 담당자

- **전체 팀 (A / B / C / D)** 공동 작업
- docker-compose.yml, .env.example: A 주도
- Dockerfile.api, Dockerfile.worker: B 주도
- Dockerfile.frontend, Dockerfile.serving: C 주도
- docker/init.sql, 헬스체크 검증: D 주도

---

## ✅ 작업 목록

### 1. docker-compose.yml 작성

- [ ] `version: "3.9"` 선언, `networks: ada-net` (bridge) 정의
- [ ] **frontend** 서비스 정의
  - build: `./Dockerfile.frontend`
  - ports: `8501:8501`
  - depends_on: api
  - healthcheck: `curl -f http://localhost:8501/_stcore/health`
- [ ] **api** 서비스 정의
  - build: `./Dockerfile.api`
  - ports: `8000:8000`
  - depends_on: postgres, redis, minio
  - env_file: `.env`
  - healthcheck: `curl -f http://localhost:8000/health`
- [ ] **worker** 서비스 정의
  - build: `./Dockerfile.worker`
  - command: `celery -A orchestrator.runner worker --loglevel=info --concurrency=4`
  - depends_on: redis, postgres, minio
  - env_file: `.env`
- [ ] **redis** 서비스 정의
  - image: `redis:7-alpine`
  - ports: `6379:6379`
  - healthcheck: `redis-cli ping`
- [ ] **postgres** 서비스 정의
  - image: `postgres:16-alpine`
  - ports: `5432:5432`
  - environment: POSTGRES_PASSWORD, POSTGRES_USER=autoai, POSTGRES_DB=autoai
  - volumes: `./docker/init.sql:/docker-entrypoint-initdb.d/init.sql`
  - healthcheck: `pg_isready -U autoai`
- [ ] **mlflow** 서비스 정의
  - image: `ghcr.io/mlflow/mlflow:v2.13.0`
  - ports: `5000:5000`
  - command: `mlflow server --backend-store-uri postgresql://autoai:${POSTGRES_PASSWORD}@postgres:5432/mlflow --default-artifact-root s3://autoai-artifacts/mlflow --host 0.0.0.0`
  - depends_on: postgres, minio
  - env_file: `.env`
- [ ] **serving** 서비스 정의
  - build: `./Dockerfile.serving`
  - ports: `8080:8080`
  - depends_on: minio, mlflow
  - env_file: `.env`
  - healthcheck: `curl -f http://localhost:8080/health`
- [ ] **minio** 서비스 정의
  - image: `minio/minio:RELEASE.2024-04-06T05-26-02Z`
  - ports: `9000:9000`, `9001:9001` (console)
  - command: `server /data --console-address ":9001"`
  - environment: MINIO_ROOT_USER, MINIO_ROOT_PASSWORD
  - healthcheck: `curl -f http://localhost:9000/minio/health/live`
- [ ] volumes 선언: postgres_data, minio_data, mlflow_data

### 2. Dockerfile.api 작성

- [ ] `FROM python:3.11-slim` 베이스 이미지
- [ ] `WORKDIR /app` 설정
- [ ] `COPY requirements/api.txt ./requirements.txt` 후 `pip install --no-cache-dir -r requirements.txt`
- [ ] `COPY . .` 전체 소스 복사
- [ ] `EXPOSE 8000`
- [ ] `CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--loop", "uvloop"]`
- [ ] 빌드 캐시 최적화: requirements 먼저 COPY 후 나머지 소스 COPY

### 3. Dockerfile.worker 작성

- [ ] `FROM python:3.11-slim` 베이스 이미지
- [ ] 시스템 패키지 설치: `libgomp1` (LightGBM 의존), `libpq-dev`
- [ ] `COPY requirements/worker.txt` 후 pip install
- [ ] GPU 지원 옵션: CUDA 런타임 여부에 따라 torch CPU/GPU 버전 선택
- [ ] `CMD ["celery", "-A", "orchestrator.runner", "worker", "--loglevel=info", "--concurrency=4", "-Q", "pipeline,default"]`
- [ ] `HEALTHCHECK`: `celery -A orchestrator.runner inspect ping`

### 4. Dockerfile.frontend 작성

- [ ] `FROM python:3.11-slim`
- [ ] `COPY requirements/frontend.txt` 후 pip install
- [ ] `EXPOSE 8501`
- [ ] `CMD ["streamlit", "run", "frontend/app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]`
- [ ] `.streamlit/config.toml` 복사 (테마, maxUploadSize=100)

### 5. Dockerfile.serving 작성

- [ ] `FROM python:3.11-slim`
- [ ] FastAPI + uvicorn 기반 모델 서빙 서버
- [ ] mlflow 모델 로딩: `mlflow.pyfunc.load_model()` 방식 사용
- [ ] `EXPOSE 8080`
- [ ] `CMD ["uvicorn", "serving.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]`

### 6. .env.example 작성

- [ ] 아래 모든 변수 포함 및 각 변수에 한국어 주석으로 용도 설명:
  ```
  # Anthropic Claude API 키
  ANTHROPIC_API_KEY=sk-ant-...

  # LangSmith 트레이싱 API 키
  LANGSMITH_API_KEY=ls__...

  # PostgreSQL 설정
  POSTGRES_PASSWORD=changeme
  POSTGRES_USER=autoai
  POSTGRES_DB=autoai
  DATABASE_URL=postgresql://autoai:password@postgres:5432/autoai

  # Redis 브로커/캐시 URL
  REDIS_URL=redis://redis:6379/0

  # MinIO 오브젝트 스토리지 설정
  MINIO_ENDPOINT=minio:9000
  MINIO_ACCESS_KEY=minioadmin
  MINIO_SECRET_KEY=minioadmin
  MINIO_BUCKET=autoai-artifacts

  # MLflow 실험 추적 설정
  MLFLOW_TRACKING_URI=http://mlflow:5000
  MLFLOW_S3_ENDPOINT_URL=http://minio:9000
  AWS_ACCESS_KEY_ID=minioadmin
  AWS_SECRET_ACCESS_KEY=minioadmin

  # 애플리케이션 설정
  LOG_LEVEL=INFO
  MAX_UPLOAD_SIZE_MB=100
  PIPELINE_TIMEOUT_MIN=30
  CUDA_VISIBLE_DEVICES=0
  ENVIRONMENT=development
  SECRET_KEY=super-secret-key-change-in-prod
  ```

### 7. docker/init.sql 작성

- [ ] `CREATE DATABASE mlflow;` — MLflow 백엔드 전용 DB 생성
- [ ] `CREATE DATABASE autoai;` — 메인 애플리케이션 DB 생성 (postgres 기본 DB로 시작 시 불필요할 수 있으니 조건부 처리)
- [ ] `GRANT ALL PRIVILEGES ON DATABASE autoai TO autoai;`
- [ ] `GRANT ALL PRIVILEGES ON DATABASE mlflow TO autoai;`
- [ ] `\c autoai` 후 `CREATE EXTENSION IF NOT EXISTS "uuid-ossp";`
- [ ] `CREATE EXTENSION IF NOT EXISTS "pg_trgm";` (텍스트 검색 최적화)
- [ ] `\c mlflow` 후 동일 익스텐션 설치

### 8. 컨테이너 기동 및 검증

- [ ] `docker compose build --no-cache` 실행 후 8개 이미지 빌드 성공 확인
- [ ] `docker compose up -d` 실행
- [ ] `docker compose ps` 결과에서 8개 컨테이너 모두 `Up (healthy)` 상태 확인
- [ ] MinIO 콘솔(http://localhost:9001) 접속 및 로그인 확인
- [ ] MLflow UI(http://localhost:5000) 페이지 로드 확인
- [ ] FastAPI Swagger docs(http://localhost:8000/docs) 접속 확인
- [ ] Streamlit(http://localhost:8501) 접속 확인
- [ ] `docker compose logs --tail=50` 에서 오류 없음 확인

---

## 🏗️ 구현 명세

### docker-compose.yml 서비스별 핵심 설정값

```yaml
# 서비스별 리소스 제한 및 재시작 정책
services:
  api:
    restart: unless-stopped
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    deploy:
      resources:
        limits:
          memory: 2G

  worker:
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 4G  # ML 학습 작업 메모리 여유 확보

  postgres:
    shm_size: '256mb'  # PostgreSQL 공유 메모리 설정
    command: >
      postgres
      -c max_connections=200
      -c shared_buffers=256MB
      -c work_mem=16MB
      -c maintenance_work_mem=64MB

  minio:
    environment:
      MINIO_ROOT_USER: ${MINIO_ACCESS_KEY}
      MINIO_ROOT_PASSWORD: ${MINIO_SECRET_KEY}
```

### requirements 파일 구조

```
requirements/
├── base.txt        # 공통 패키지 (pydantic, structlog, boto3)
├── api.txt         # FastAPI, uvicorn, sqlalchemy, asyncpg
├── worker.txt      # celery, langgraph, langchain, sklearn, xgboost 등 ML 패키지
├── frontend.txt    # streamlit, plotly, pandas, requests
└── serving.txt     # mlflow, fastapi, uvicorn, numpy
```

### 핵심 패키지 버전 고정 목록

```
# base.txt
pydantic==2.7.1
pydantic-settings==2.3.0
structlog==24.2.0
boto3==1.34.101
python-dotenv==1.0.1
httpx==0.27.0

# api.txt
fastapi==0.111.0
uvicorn[standard]==0.29.0
uvloop==0.19.0
sqlalchemy==2.0.30
asyncpg==0.29.0
alembic==1.13.1
python-multipart==0.0.9
aiofiles==23.2.1

# worker.txt (ML 관련)
scikit-learn==1.5.0
xgboost==2.0.3
lightgbm==4.3.0
catboost==1.2.5
torch==2.3.0
optuna==3.6.1
shap==0.45.1
mlflow==2.13.0
langgraph==0.1.5
langchain==0.2.3
langchain-anthropic==0.1.13
celery==5.4.0
redis==5.0.4
pandas==2.2.2
numpy==1.26.4
scipy==1.13.0
statsmodels==0.14.2

# frontend.txt
streamlit==1.35.0
plotly==5.22.0
pandas==2.2.2
requests==2.32.2
altair==5.3.0

# serving.txt
mlflow==2.13.0
fastapi==0.111.0
uvicorn[standard]==0.29.0
numpy==1.26.4
```

### 네트워크 및 볼륨 설계

```
ada-net (bridge driver)
├── frontend  →  api (내부 DNS: api:8000)
├── api       →  postgres:5432, redis:6379, minio:9000
├── worker    →  postgres:5432, redis:6379, minio:9000, mlflow:5000
├── mlflow    →  postgres:5432, minio:9000
└── serving   →  minio:9000, mlflow:5000

Named Volumes:
  postgres_data  →  /var/lib/postgresql/data  (PostgreSQL 데이터 영속성)
  minio_data     →  /data                     (MinIO 오브젝트 영속성)
```

### Healthcheck 설정 상세

```yaml
# 각 서비스 healthcheck 표준 설정
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:{PORT}/health"]
  interval: 30s       # 30초마다 체크
  timeout: 10s        # 10초 내 응답 없으면 실패
  retries: 3          # 3회 연속 실패 시 unhealthy
  start_period: 40s   # 컨테이너 시작 후 40초 대기 (초기화 시간)
```

### docker/init.sql 전체 구조

```sql
-- 1. mlflow 전용 데이터베이스 생성
CREATE DATABASE mlflow;

-- 2. 권한 부여
GRANT ALL PRIVILEGES ON DATABASE autoai TO autoai;
GRANT ALL PRIVILEGES ON DATABASE mlflow TO autoai;

-- 3. autoai DB 초기화
\c autoai

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";   -- UUID 생성 함수
CREATE EXTENSION IF NOT EXISTS "pg_trgm";     -- 트라이그램 텍스트 검색
CREATE EXTENSION IF NOT EXISTS "btree_gin";   -- GIN 인덱스 확장

-- 4. mlflow DB 초기화
\c mlflow

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
```

---

## 📁 생성/수정 파일 목록

```
프로젝트 루트/
├── docker-compose.yml              # 8개 서비스 오케스트레이션
├── .env.example                    # 환경 변수 템플릿 (커밋 O)
├── .env                            # 실제 시크릿 (커밋 X, .gitignore에 포함)
├── .gitignore                      # .env 포함 확인
├── Dockerfile.api                  # FastAPI 서버 이미지
├── Dockerfile.worker               # Celery 워커 이미지
├── Dockerfile.frontend             # Streamlit 프론트엔드 이미지
├── Dockerfile.serving              # 모델 서빙 이미지
├── docker/
│   └── init.sql                    # PostgreSQL 초기화 스크립트
├── requirements/
│   ├── base.txt
│   ├── api.txt
│   ├── worker.txt
│   ├── frontend.txt
│   └── serving.txt
└── .streamlit/
    └── config.toml                 # Streamlit 서버 설정
```

---

## 🔗 의존성 & 선행 조건

- Docker Desktop 4.29+ 또는 Docker Engine 26+ 설치 완료
- Docker Compose v2.27+ 설치 완료 (`docker compose version` 확인)
- 최소 16GB RAM, 50GB 디스크 여유 공간 확보
- 포트 5000, 5432, 6379, 8000, 8080, 8501, 9000, 9001 사용 가능 상태 확인
- ANTHROPIC_API_KEY 발급 완료 (https://console.anthropic.com)
- LANGSMITH_API_KEY 발급 완료 (https://smith.langchain.com)
- GPU 사용 시: NVIDIA Driver 535+, nvidia-container-toolkit 설치 완료

---

## ✔️ 완료 기준 (Done Criteria)

- [ ] `docker compose ps` 출력에서 8개 서비스 모두 `Up (healthy)` 상태 확인
- [ ] `docker compose logs api | grep "Application startup complete"` 로그 확인
- [ ] `docker compose logs worker | grep "celery@worker ready"` 로그 확인
- [ ] `curl http://localhost:8000/health` 응답: `{"status": "ok"}`
- [ ] `curl http://localhost:8501/_stcore/health` 응답: HTTP 200
- [ ] MinIO 콘솔(http://localhost:9001) 로그인 성공 (minioadmin/minioadmin)
- [ ] MLflow UI(http://localhost:5000) 페이지 로드 성공
- [ ] `docker exec postgres psql -U autoai -c "\l"` 에서 `autoai`, `mlflow` DB 확인
- [ ] `.env` 파일이 `.gitignore`에 포함되어 있음 (`git status`에 .env 미표시)
- [ ] `docker compose down && docker compose up -d` 재기동 후에도 postgres 데이터 유지

---

## ⚠️ 주의사항 & 제약

### AGENTS.md 룰 (Day 1 적용)

- **R-001**: 모든 시크릿(API Key, DB 패스워드 등)은 `.env` 파일로만 관리. 코드 내 하드코딩 절대 금지
- **R-002**: `.env` 파일은 절대 Git에 커밋하지 않는다. `.gitignore`에 명시 필수
- **R-003**: 각 서비스 컨테이너는 최소 권한 원칙 적용 (Dockerfile에 `USER` 지시어로 비루트 실행)

### 아키텍처 제약

- PostgreSQL은 단일 인스턴스 사용 (Day 2까지), 추후 스케일 아웃 고려 시 별도 설계 논의
- Redis는 캐시 + Celery 브로커 + pub/sub 겸용 (단일 인스턴스, 개발환경 한정)
- MinIO는 로컬 개발 환경용. 프로덕션에서는 AWS S3로 교체 예정 (환경 변수만 변경)
- MLflow 버전은 `v2.13.0`으로 고정 (API 호환성 보장, 임의 업그레이드 금지)
- Python 버전은 `3.11`로 통일 (3.12는 일부 ML 패키지 미지원 확인됨)

### 네트워크 주의사항

- 컨테이너 간 통신은 서비스명(Docker 내부 DNS)으로 참조 (`postgres:5432`, `redis:6379`)
- 호스트에서 접근 시에는 `localhost:{포트번호}` 사용
- `DATABASE_URL`에서 호스트는 `postgres` (컨테이너 서비스명), 외부 접근 시는 `localhost`

### 리소스 제약

- worker 컨테이너 메모리 리밋: 4GB (ML 학습 중 OOM 방지)
- api 컨테이너 메모리 리밋: 2GB
- postgres `max_connections=200` (커넥션 풀 고려, pool_size=20 × 10 워커 = 200)
- 개발 환경 GPU 미사용 시 `CUDA_VISIBLE_DEVICES=""` 설정하여 CUDA 초기화 비용 제거

### 팀 협업 규칙

- docker-compose.yml 변경 시 반드시 팀 전체 Slack 공지 후 반영
- Dockerfile 변경 후 `docker compose build` 재실행 필수 (이미지 캐시 무효화)
- 포트 충돌 발생 시 팀 내 조율 후 `.env`에서 포트 오버라이드 (docker-compose.yml 직접 수정 지양)
- `docker compose down -v` 는 볼륨도 삭제하므로 데이터 손실 주의. 반드시 팀 공지 후 실행

---

## 🆕 v2 확장 작업 (마스터 설계서 §2 · §10 참조)

> 본 절은 21일 스프린트 v2에서 Day1이 추가로 책임지는 작업이다. 위 v1 작업이 완료된 뒤 동일한 날 안에서 처리한다.

### 1. `claude-cli-sidecar` 컨테이너 추가 (Day16 사전 준비)

- [ ] `docker/claude-cli-sidecar.Dockerfile` 작성:
  ```dockerfile
  FROM node:20-slim
  RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
   && rm -rf /var/lib/apt/lists/*
  RUN npm install -g @anthropic-ai/claude-code
  RUN useradd -m -u 1001 claude
  USER claude
  WORKDIR /workspace
  ENTRYPOINT ["claude"]
  ```
- [ ] `docker-compose.yml` 의 services에 추가:
  ```yaml
  claude-cli-sidecar:
    build:
      context: .
      dockerfile: docker/claude-cli-sidecar.Dockerfile
    image: ada/claude-cli-sidecar:latest
    volumes:
      - .:/workspace:ro
      - ./error_handler/patches:/error_handler/patches:rw
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    networks:
      - ada-net
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
  ```
- [ ] 컨테이너 기동 후 헬스체크: `docker exec claude-cli-sidecar claude --version` → 정상 응답
- [ ] R-602 룰 추가: `--allowed-tools=Read,Grep,Glob` 호출 시 강제

### 2. `vault` (HashiCorp Vault dev 모드) 컨테이너 추가

- [ ] `docker-compose.yml` services 추가:
  ```yaml
  vault:
    image: hashicorp/vault:1.16
    ports: ["8200:8200"]
    environment:
      VAULT_DEV_ROOT_TOKEN_ID: ${VAULT_DEV_TOKEN}
      VAULT_DEV_LISTEN_ADDRESS: "0.0.0.0:8200"
    cap_add: [IPC_LOCK]
    networks: [ada-net]
  ```
- [ ] `.env.example` 추가: `VAULT_DEV_TOKEN=ada-dev-root`
- [ ] `scripts/vault_seed.sh` 작성: KV v2 mount 후 `ANTHROPIC_API_KEY` / `POSTGRES_PASSWORD` 시드
- [ ] api, worker 컨테이너에 환경변수 `VAULT_ADDR=http://vault:8200` 주입

### 3. pgvector 확장 사전 준비

- [ ] `docker/init.sql` 에 추가: `CREATE EXTENSION IF NOT EXISTS vector;` (autoai DB 안)
- [ ] PostgreSQL 이미지를 `pgvector/pgvector:pg16` 으로 변경:
  ```yaml
  postgres:
    image: pgvector/pgvector:pg16
  ```

### 4. Celery 큐 토폴로지 분리

- [ ] worker 컨테이너를 큐별로 분리:
  ```yaml
  worker-pipeline:
    extends: { service: worker }
    command: celery -A orchestrator.runner worker -Q pipeline -c 4 -n pipeline@%h
  worker-training:
    extends: { service: worker }
    command: celery -A orchestrator.runner worker -Q training -c 2 -n training@%h
    deploy:
      resources:
        limits: { memory: 8G }
  worker-output:
    extends: { service: worker }
    command: celery -A orchestrator.runner worker -Q output -c 2 -n output@%h
  worker-harness:
    extends: { service: worker }
    command: celery -A orchestrator.runner worker -Q harness -c 1 -n harness@%h
  ```

### 5. 보안 베이스라인 (Day17 본격화 전 최소 가드)

- [ ] 모든 컨테이너 `security_opt: [no-new-privileges:true]`, 비루트 USER 지시어
- [ ] api/frontend 컨테이너에 `read_only: false` 유지하되 `tmpfs: /tmp`
- [ ] `.env.example`에 신규 키 추가: `JWT_SECRET`, `JWT_ALGO=HS256`, `VAULT_DEV_TOKEN`, `MAX_DAILY_LLM_USD=20`

### 6. 완료 기준 (v2 추가)

- [ ] `docker compose ps` 컨테이너 수 ≥ 11 (v1 8개 + claude-cli-sidecar + vault + worker 분리 추가본)
- [ ] `docker exec postgres psql -U autoai -d autoai -c "SELECT extversion FROM pg_extension WHERE extname='vector';"` 결과에 버전 출력
- [ ] `curl http://localhost:8200/v1/sys/health` → 200
- [ ] `docker exec claude-cli-sidecar claude --version` 정상

### 7. 주의사항 (v2)

- claude-cli-sidecar 가 코드 마운트를 **read-only** 로 잡았는지 docker inspect로 확인 (R-602)
- Vault는 dev 모드 (root token 노출). 프로덕션 배포 전 KV v2 + AppRole 인증으로 전환 필수
- pgvector 인덱스 빌드는 Day02 마이그레이션에서 수행 (여기서는 익스텐션 설치만)

