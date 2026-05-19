# ADA — Docker 환경 설치 인벤토리

> 프로젝트 ADA가 Docker로 동작하기 위해 **설치·정의해야 할 모든 것**을 한 문서에 정리.
> 기반: 작업지시서 Day01·Day02·Day03·Day04 + 마스터설계서 §2/§4
> Python 버전: **3.10** (프로젝트 결정. Day01 문서의 3.11 표기는 무시)
> 서버 사양: Ryzen 7 3800XT / 16GB RAM / GTX 1060 3GB / 144GB 여유

---

## 0. 한 장 요약

| 카테고리 | 개수 | 비고 |
|---|---|---|
| 외부 Docker 이미지 (그대로 사용) | 5종 | postgres·redis·minio·mlflow·vault |
| 직접 빌드하는 Docker 이미지 | 5종 | api·worker·frontend·serving·claude-cli-sidecar |
| 시스템 패키지 (apt) | 약 15종 | 워커 컨테이너에 ML 의존성 집중 |
| Python 패키지 (4 파일 합산) | 약 70종 | base/api/worker/frontend/serving |
| NPM 패키지 | 1종 | @anthropic-ai/claude-code |
| 환경 변수 (.env) | 약 25개 | LLM·DB·MinIO·MLflow·보안·Vault |
| 초기화 스크립트 | 6종 | init.sql, migrations 5개, minio/mlflow 부트스트랩 |

---

## 1. Docker 이미지 — 외부에서 가져오는 5종

이 다섯 개는 직접 빌드하지 않고 그대로 pull 합니다.

| 서비스 | 이미지 태그 | 역할 | 비고 |
|---|---|---|---|
| **postgres** | `pgvector/pgvector:pg16` | RDBMS + 벡터 검색 | ⚠️ `postgres:16-alpine` 절대 X. pgvector 익스텐션 포함된 이미지 필수 |
| **redis** | `redis:7-alpine` | 브로커 + 캐시 + pub/sub | – |
| **minio** | `minio/minio:RELEASE.2024-04-06T05-26-02Z` | S3 호환 오브젝트 스토리지 | 버전 핀 고정 |
| **mlflow** | `ghcr.io/mlflow/mlflow:v2.13.0` | 실험 추적 | 버전 핀 고정 (Day01 R-202) |
| **vault** | `hashicorp/vault:1.16` | 시크릿 매니저 (dev 모드) | Day01 v2 확장 |

선택(나중에 추가하지 않음 기본):
- `qdrant/qdrant` — pgvector로 대체 가능. 보통 안 씀
- `prom/prometheus`, `grafana/grafana`, `otel/opentelemetry-collector-contrib` — Day20 옵저버빌리티에서만

---

## 2. Docker 이미지 — 직접 빌드 5종

### 2.1 `Dockerfile.api` — FastAPI 서버

```dockerfile
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements/base.txt requirements/api.txt /app/requirements/
RUN pip install -r /app/requirements/api.txt

COPY . /app

# 비루트 사용자 (Day01 R-003)
RUN useradd -m -u 1001 ada
USER ada

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=40s \
  CMD curl -fs http://localhost:8000/health || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--loop", "uvloop"]
```

### 2.2 `Dockerfile.worker` — Celery 워커 (가장 무거움)

```dockerfile
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:128

# ML 의존성: LightGBM/XGBoost/torch/pillow/audio/pdf 등이 요구하는 시스템 라이브러리
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential gcc g++ \
        libgomp1 libpq-dev libpq5 \
        libsndfile1 libgl1 libglib2.0-0 \
        libmagic1 poppler-utils \
        ffmpeg \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements/base.txt requirements/worker.txt /app/requirements/
RUN pip install -r /app/requirements/worker.txt

COPY . /app
RUN useradd -m -u 1001 ada
USER ada

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=60s \
  CMD celery -A orchestrator.runner inspect ping || exit 1

# 큐는 compose의 command로 오버라이드 (pipeline/training/output/harness 4종 분리)
CMD ["celery", "-A", "orchestrator.runner", "worker", \
     "--loglevel=info", "--concurrency=2", "-Q", "pipeline"]
```

### 2.3 `Dockerfile.frontend` — Streamlit

```dockerfile
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements/base.txt requirements/frontend.txt /app/requirements/
RUN pip install -r /app/requirements/frontend.txt

COPY . /app
COPY .streamlit /app/.streamlit
RUN useradd -m -u 1001 ada
USER ada

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=40s \
  CMD curl -fs http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "frontend/app.py", \
     "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
```

### 2.4 `Dockerfile.serving` — 모델 서빙

```dockerfile
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements/base.txt requirements/serving.txt /app/requirements/
RUN pip install -r /app/requirements/serving.txt

COPY . /app
RUN useradd -m -u 1001 ada
USER ada

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=40s \
  CMD curl -fs http://localhost:8080/health || exit 1

CMD ["uvicorn", "serving.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
```

### 2.5 `docker/claude-cli-sidecar.Dockerfile` — Day16용

```dockerfile
FROM node:20-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

RUN useradd -m -u 1001 claude
USER claude
WORKDIR /workspace

ENTRYPOINT ["claude"]
```

---

## 3. 시스템 패키지 (apt) 정리

컨테이너별로 들어가는 시스템 라이브러리 목록입니다. **워커가 가장 무겁습니다.**

| 패키지 | api | worker | frontend | serving | 용도 |
|---|---|---|---|---|---|
| `curl`, `ca-certificates` | ✅ | ✅ | ✅ | ✅ | 헬스체크·HTTPS |
| `libpq5` (런타임) | ✅ | ✅ | – | ✅ | psycopg2/asyncpg 런타임 |
| `libpq-dev` (빌드) | – | ✅ | – | – | 빌드 시 psycopg2 컴파일 |
| `build-essential`, `gcc`, `g++` | – | ✅ | – | – | C 확장 빌드 |
| `libgomp1` | – | ✅ | – | ✅ | LightGBM·XGBoost OpenMP |
| `libsndfile1` | – | ✅ | – | – | librosa·soundfile (wav, Day05) |
| `libgl1`, `libglib2.0-0` | – | ✅ | – | – | opencv·PIL (이미지, Day05/Day12) |
| `libmagic1` | – | ✅ | – | – | python-magic mime 감지 |
| `poppler-utils` | – | ✅ | – | – | pdf 텍스트 추출 (Day05) |
| `ffmpeg` | – | ✅ | – | – | 오디오/비디오 변환 (Day05/Day12) |
| `tesseract-ocr` (선택) | – | ⚠️ | – | – | 이미지 OCR — 필요해지면 추가 |

> 빌드 시 `--no-install-recommends`, `rm -rf /var/lib/apt/lists/*` 로 이미지 크기 최소화.

---

## 4. Python 패키지 — `requirements/` 5개 파일

### 4.1 `requirements/base.txt` — 공통

```
# 공통 (모든 컨테이너 공유)
pydantic==2.7.1
pydantic-settings==2.3.0
structlog==24.2.0
python-dotenv==1.0.1
httpx==0.27.0
boto3==1.34.101
tenacity==8.3.0          # 재시도 데코레이터
orjson==3.10.3           # 빠른 JSON
```

### 4.2 `requirements/api.txt` — FastAPI 서버

```
-r base.txt

# 웹 프레임워크
fastapi==0.111.0
uvicorn[standard]==0.29.0
uvloop==0.19.0
python-multipart==0.0.9
aiofiles==23.2.1
sse-starlette==2.1.0     # SSE (Day18 진행률)
websockets==12.0         # WebSocket (Day18 대시보드)

# DB
sqlalchemy==2.0.30
asyncpg==0.29.0
alembic==1.13.1
pgvector==0.2.5          # pgvector Python 클라이언트 (Day19 RAG)

# LLM
anthropic==0.28.0        # Claude API
langgraph==0.1.5         # 그래프 resume (Day04)
langchain==0.2.3
langchain-anthropic==0.1.13
langsmith==0.1.65        # 트레이싱

# 보안 (Day17)
python-jose[cryptography]==3.3.0   # JWT
passlib[bcrypt]==1.7.4              # 패스워드 해시
itsdangerous==2.2.0                 # 서명된 쿠키
hvac==2.3.0                         # Vault 클라이언트
slowapi==0.1.9                      # rate limit

# 보조
celery==5.4.0           # Celery 태스크 enqueue 용도
redis==5.0.4
```

### 4.3 `requirements/worker.txt` — Celery 워커 (가장 무거움)

```
-r base.txt

# 오케스트레이션
celery==5.4.0
redis==5.0.4

# DB
sqlalchemy==2.0.30
asyncpg==0.29.0
psycopg2-binary==2.9.9
pgvector==0.2.5

# LLM
anthropic==0.28.0
langgraph==0.1.5
langchain==0.2.3
langchain-anthropic==0.1.13
langsmith==0.1.65

# 정형 ML (Day07/Day08)
scikit-learn==1.5.0
xgboost==2.0.3
lightgbm==4.3.0
catboost==1.2.5
optuna==3.6.1
shap==0.45.1
imbalanced-learn==0.12.2

# 시계열 (Day07)
statsmodels==0.14.2
prophet==1.1.5

# 딥러닝 / 트랜스포머 (Day08/Day12)
--extra-index-url https://download.pytorch.org/whl/cu121
torch==2.3.0+cu121
torchvision==0.18.0+cu121
torchaudio==2.3.0+cu121
transformers==4.41.0
accelerate==0.30.1
peft==0.11.0             # LoRA (Day12)
datasets==2.19.1
sentence-transformers==2.7.0   # 임베딩 (Day19 RAG)
sentencepiece==0.2.0
tokenizers==0.19.1

# MLflow / 실험 추적
mlflow==2.13.0

# 데이터 처리 (Day05)
pandas==2.2.2
numpy==1.26.4
scipy==1.13.0
pyarrow==16.1.0          # parquet
openpyxl==3.1.2          # xlsx
xlrd==2.0.1              # 구형 xls
python-magic==0.4.27
pillow==10.3.0
pypdf==4.2.0             # pdf
pdfplumber==0.11.0
beautifulsoup4==4.12.3
lxml==5.2.2
librosa==0.10.2          # wav/오디오
soundfile==0.12.1

# 보안/PII (Day05/Day17)
presidio-analyzer==2.2.354
presidio-anonymizer==2.2.354
spacy==3.7.4
# 한국어 NER 모델은 시작 시 별도 다운로드:
#   python -m spacy download ko_core_news_sm

# 차트/EDA (Day10)
matplotlib==3.9.0
seaborn==0.13.2
plotly==5.22.0

# 산출물 생성 (Day12/Day15) — 13종 생성기
python-pptx==0.6.23      # PPT
reportlab==4.2.0         # PDF
jinja2==3.1.4            # 템플릿
markdown==3.6
weasyprint==62.2         # HTML→PDF (선택)
qrcode==7.4.2

# 보안 (Day17)
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
hvac==2.3.0

# 에러 처리 (Day16)
unidiff==0.7.5           # 패치 적용

# 옵저버빌리티 (Day20)
opentelemetry-api==1.25.0
opentelemetry-sdk==1.25.0
opentelemetry-instrumentation-celery==0.46b0
opentelemetry-instrumentation-sqlalchemy==0.46b0
opentelemetry-exporter-otlp==1.25.0
```

### 4.4 `requirements/frontend.txt` — Streamlit UI

```
-r base.txt

streamlit==1.35.0
streamlit-extras==0.4.3      # 보조 UI 컴포넌트
streamlit-aggrid==1.0.5      # 강력한 표 (G4 비교표)
streamlit-cookies-manager==0.2.0   # JWT 쿠키 처리

plotly==5.22.0
altair==5.3.0
pandas==2.2.2
numpy==1.26.4
requests==2.32.2
websocket-client==1.8.0      # WebSocket 클라이언트 (Day18)
```

### 4.5 `requirements/serving.txt` — 모델 서빙

```
-r base.txt

mlflow==2.13.0
fastapi==0.111.0
uvicorn[standard]==0.29.0

# 학습 시 사용한 프레임워크 (예측만 하므로 가벼움)
scikit-learn==1.5.0
xgboost==2.0.3
lightgbm==4.3.0
torch==2.3.0           # CPU 빌드 (서빙은 CPU)
numpy==1.26.4
pandas==2.2.2
```

### 4.6 `requirements/dev.txt` — 개발/테스트 (이미지에 포함 안 함)

```
-r base.txt
-r api.txt
-r worker.txt

pytest==8.2.1
pytest-asyncio==0.23.7
pytest-cov==5.0.0
pytest-mock==3.14.0
httpx==0.27.0
locust==2.27.0          # Day20 부하 테스트
ruff==0.4.5             # 린터
mypy==1.10.0
pre-commit==3.7.1
ipython==8.24.0
jupyterlab==4.2.1       # (선택) 로컬 노트북
```

---

## 5. NPM 패키지 (claude-cli-sidecar 한정)

```
@anthropic-ai/claude-code   # Claude Code CLI — Day16 AutoErrorHandler가 호출
```

---

## 6. 환경 변수 (`.env`) — 약 25개

`.env.example` 파일로 커밋, 실제 `.env` 는 `.gitignore` 에 포함(R-002).

```bash
# === LLM API ===
ANTHROPIC_API_KEY=sk-ant-...                # Claude API 키
LANGSMITH_API_KEY=ls__...                   # LangSmith 트레이싱 (선택)
LANGSMITH_PROJECT=ada-pipeline

# === PostgreSQL ===
POSTGRES_USER=autoai
POSTGRES_PASSWORD=<openssl rand -base64 24>
POSTGRES_DB=autoai
DATABASE_URL=postgresql://autoai:${POSTGRES_PASSWORD}@postgres:5432/autoai

# === Redis ===
REDIS_URL=redis://redis:6379/0

# === MinIO (S3 호환) ===
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=<openssl rand -base64 24>
MINIO_BUCKET=autoai-artifacts

# === MLflow ===
MLFLOW_TRACKING_URI=http://mlflow:5000
MLFLOW_S3_ENDPOINT_URL=http://minio:9000
AWS_ACCESS_KEY_ID=${MINIO_ACCESS_KEY}        # boto3가 환경변수로 인식
AWS_SECRET_ACCESS_KEY=${MINIO_SECRET_KEY}

# === Vault (Day17) ===
VAULT_DEV_TOKEN=<openssl rand -hex 16>
VAULT_ADDR=http://vault:8200

# === 보안 (Day17) ===
SECRET_KEY=<openssl rand -hex 32>            # 일반 시그니처 키
JWT_SECRET=<openssl rand -hex 32>            # JWT 서명 키
JWT_ALGO=HS256
JWT_EXPIRE_MIN=60

# === 애플리케이션 ===
LOG_LEVEL=INFO
MAX_UPLOAD_SIZE_MB=100
PIPELINE_TIMEOUT_MIN=30
ENVIRONMENT=development                      # development | production

# === GPU ===
CUDA_VISIBLE_DEVICES=0                       # 워커-training에만 적용
NVIDIA_VISIBLE_DEVICES=0

# === LLM 사용량 가드 (Day17) ===
MAX_DAILY_LLM_USD=20
```

---

## 7. 초기화 스크립트와 데이터 파일

이미지에는 포함되지 않고 호스트에서 마운트되거나 첫 기동 시 실행됩니다.

| 파일 | 위치 | 역할 | 작성 단계 |
|---|---|---|---|
| `docker/init.sql` | postgres 컨테이너 `/docker-entrypoint-initdb.d/` 마운트 | DB 생성 + 확장(uuid-ossp, pg_trgm, vector, pgcrypto) | Day01 |
| `migrations/001_initial.sql` | 수동 적용 | v1 10개 테이블 + 10개 인덱스 | Day02 |
| `migrations/002_v2_schema.sql` | 수동 적용 | v2 14개 신규 테이블 | Day02 |
| `migrations/003_pgvector_setup.sql` | 수동 적용 | IVFFlat 인덱스 | Day02 |
| `migrations/004_security_baseline.sql` | 수동 적용 | RLS + 컬럼 암호화 | Day02 |
| `migrations/005_seed_agent_registry.sql` | 수동 적용 | 27 에이전트 시드 | Day02 |
| `scripts/mlflow_init.py` | 호스트에서 실행 | 6개 실험(`ada-tabular-ml` 등) 생성 | Day02 |
| `tools/minio_setup.py` | 호스트에서 실행 | `autoai-artifacts` 버킷 생성 | Day02 |
| `scripts/vault_seed.sh` | 호스트에서 실행 | Vault KV v2 mount + 시크릿 시드 | Day01 v2 |
| `.streamlit/config.toml` | frontend 컨테이너에 COPY | Streamlit 테마, maxUploadSize=100 | Day01 |

### 7.1 `docker/init.sql`

```sql
-- 데이터베이스 생성
CREATE DATABASE mlflow;
GRANT ALL PRIVILEGES ON DATABASE autoai TO autoai;
GRANT ALL PRIVILEGES ON DATABASE mlflow TO autoai;

-- autoai DB에 확장
\c autoai
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "btree_gin";
CREATE EXTENSION IF NOT EXISTS vector;        -- pgvector (Day02 v2)
CREATE EXTENSION IF NOT EXISTS pgcrypto;      -- 컬럼 암호화 (Day17)

-- mlflow DB
\c mlflow
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
```

### 7.2 `.streamlit/config.toml`

```toml
[server]
maxUploadSize = 100
enableCORS = false
enableXsrfProtection = true
headless = true

[theme]
primaryColor = "#FF4B4B"
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "#F0F2F6"
textColor = "#262730"
```

---

## 8. 전체 파일 트리

```
ADA/
├── docker-compose.yml                  # 13~16 서비스 정의 + profile
├── .env.example                        # 환경변수 템플릿 (커밋 O)
├── .env                                # 실제 값 (커밋 X)
├── .gitignore                          # .env, __pycache__, .venv 등
│
├── Dockerfile.api                      # FastAPI 이미지
├── Dockerfile.worker                   # Celery 워커 이미지
├── Dockerfile.frontend                 # Streamlit 이미지
├── Dockerfile.serving                  # 모델 서빙 이미지
├── docker/
│   ├── init.sql                        # Postgres 부트스트랩
│   └── claude-cli-sidecar.Dockerfile   # Day16
│
├── requirements/
│   ├── base.txt
│   ├── api.txt
│   ├── worker.txt
│   ├── frontend.txt
│   ├── serving.txt
│   └── dev.txt                         # 이미지엔 포함 안 됨
│
├── migrations/
│   ├── 001_initial.sql                 # Day02 v1
│   ├── 002_v2_schema.sql               # Day02 v2 14테이블
│   ├── 003_pgvector_setup.sql          # IVFFlat 인덱스
│   ├── 004_security_baseline.sql       # RLS + 암호화
│   └── 005_seed_agent_registry.sql     # 27 에이전트 시드
│
├── scripts/
│   ├── mlflow_init.py
│   ├── vault_seed.sh
│   └── isolation_hook.sh               # Day03 pre-commit
│
├── tools/
│   └── minio_setup.py
│
├── .streamlit/
│   └── config.toml
│
├── shared/                             # Day03
│   ├── config.py
│   ├── state.py
│   ├── db.py
│   ├── models.py
│   ├── logger.py
│   └── security.py
│
├── agents/                             # Day03/Day06~Day11
│   ├── base.py
│   ├── personas.py
│   └── ... (27종)
│
├── orchestrator/                       # Day04
│   ├── graph.py
│   └── runner.py
│
├── pipelines/                          # Day07/Day12
│   ├── base.py
│   ├── factory.py
│   └── ... (정형/시계열/이미지/NLP/이상/생성)
│
├── api/                                # Day06/Day13/Day19
│   ├── main.py
│   ├── routes/
│   ├── middleware/
│   └── services/
│
├── frontend/                           # Day10/Day18
│   └── app.py
│
├── serving/                            # Day12
│   └── main.py
│
├── reports/                            # Day12/Day15
│   ├── presentation_generator.py
│   ├── pdf_generator.py
│   └── ... (13종)
│
├── error_handler/                      # Day16
│   ├── auto_handler.py
│   ├── cli_bridge.py
│   └── patches/                        # 마운트 대상
│
├── tests/
│   ├── agents/
│   ├── api/
│   └── integration/
│
├── alembic/                            # 선택
│   ├── env.py
│   ├── alembic.ini
│   └── versions/
│
├── .github/
│   └── workflows/
│       ├── test.yml                    # Day03 CI
│       └── isolation_check.yml         # Day03
│
└── .pre-commit-config.yaml
```

---

## 9. 빌드와 첫 기동 순서

```bash
# 1) 환경변수 채우기
cp .env.example .env
chmod 600 .env
# .env 편집하여 ANTHROPIC_API_KEY, POSTGRES_PASSWORD, JWT_SECRET 등 채움

# 2) Docker 이미지 빌드 (5종)
docker compose --profile core --profile sec build
# - api / worker / frontend / serving / claude-cli-sidecar
# - 외부 5종(postgres/redis/minio/mlflow/vault)은 pull로 처리됨

# 3) 인프라 컨테이너부터 단계 기동
docker compose --profile core up -d postgres redis minio
docker compose --profile core ps             # 모두 (healthy)일 때까지 대기

# 4) DB 마이그레이션 (Day02)
for f in migrations/0*.sql; do
  docker compose exec -T postgres psql -U autoai -d autoai < $f
done

# 5) MinIO 버킷 + MLflow 실험 초기화
docker compose run --rm api python tools/minio_setup.py
docker compose --profile core up -d mlflow
docker compose run --rm api python scripts/mlflow_init.py

# 6) Vault 시크릿 시드 (Day01 v2)
docker compose --profile sec up -d vault
docker compose exec vault sh /scripts/vault_seed.sh

# 7) 나머지 코어 서비스 (api, frontend, worker 4종)
docker compose --profile core up -d
docker compose --profile core ps

# 8) (학습 단계 진입 시) ml 프로파일 추가
docker compose --profile core --profile ml up -d worker-training worker-output

# 9) 검증
curl -fs http://localhost:8000/health
curl -fs http://localhost:8501/_stcore/health
curl -fs http://localhost:5000
curl -fs http://localhost:8200/v1/sys/health
docker compose exec postgres \
  psql -U autoai -d autoai -c "SELECT count(*) FROM agent_registry;"
# → 27 나와야 함
```

---

## 10. 16GB / GTX 1060 환경 핵심 제약 (재확인)

`LINUX_DOCKER_SETUP_GUIDE.md` 의 재설계판 사양을 그대로 적용:

- 모든 Dockerfile에서 `python:3.10-slim` 사용
- `worker.txt` 의 torch는 **`cu121` 빌드** (Pascal sm_61 지원)
- Compose 한도: api 1.5GB / worker-pipeline 2.5GB / worker-training 4GB / postgres 1.5GB
- Compose `profiles`: `core` / `ml` / `sec` / `obs`
- 학습 시 `CUDA_VISIBLE_DEVICES` 는 worker-training 에만, 다른 워커는 `""` 로 강제
- transformers 사용 시 `accelerate` + FP16 + gradient checkpointing 기본

---

## 11. 누락되면 안 되는 것 — 체크리스트

설치/세팅 후 다음을 확인해 주세요.

- [ ] `.env` 의 25개 키가 모두 실제 값으로 채워져 있다
- [ ] `python:3.10-slim` 베이스 (5종 Dockerfile 전부)
- [ ] postgres 이미지는 `pgvector/pgvector:pg16` (절대 `postgres:16-alpine` X)
- [ ] worker 컨테이너에 `libgomp1`, `libsndfile1`, `libgl1`, `ffmpeg`, `poppler-utils` apt 설치 완료
- [ ] torch 휠이 `+cu121` (Pascal GTX 1060 호환)
- [ ] `requirements/worker.txt` 에 transformers/accelerate/peft 포함
- [ ] `requirements/api.txt` 에 hvac, python-jose, passlib 포함 (Day17 보안)
- [ ] `requirements/frontend.txt` 에 streamlit-aggrid 포함 (G4 비교표)
- [ ] `docker/init.sql` 에 `CREATE EXTENSION vector;` 포함
- [ ] migrations 5개 파일 모두 적용 완료, `\dt` 시 24개 이상 테이블
- [ ] `agent_registry` 27행
- [ ] MinIO 콘솔에 `autoai-artifacts` 버킷
- [ ] MLflow UI 에 6개 실험(`ada-tabular-ml`, `ada-tabular-dl`, `ada-timeseries`, `ada-image`, `ada-nlp`, `ada-anomaly`)
- [ ] `.env` 가 `git status` 에 안 보임 (`.gitignore` 동작)
- [ ] `docker compose down && docker compose up -d` 재기동 후 DB 데이터 유지
- [ ] 비루트 사용자(USER 1001)로 컨테이너 실행 (R-003)

---

## 12. 한 줄 요약

> **외부 이미지 5종 + 자체 이미지 5종 + apt 15개 + Python 70여 패키지 + .env 25개 + 마이그레이션 5개 + 초기화 스크립트 3개.** 베이스는 전부 `python:3.10-slim`, Postgres는 `pgvector/pgvector:pg16`, torch는 cu121, 워커에 transformers+peft 포함, 보안 패키지(hvac/jose/passlib)는 api에 포함.

이 인벤토리대로 채우면 Day01 + Day02 v2 + Day03 + Day04 + Day17 보안 베이스라인까지 한 번에 만족하는 컨테이너 환경이 완성됩니다.
