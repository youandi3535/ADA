"""ada.core.config — Settings (pydantic-settings).

.env 파일에서 자동 로딩. 코드 하드코딩 금지 (R-001).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ----- LLM -----
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    langsmith_api_key: str = Field(default="", validation_alias="LANGSMITH_API_KEY")
    langsmith_project: str = Field(default="ada-pipeline", validation_alias="LANGSMITH_PROJECT")

    # ----- Database -----
    database_url: str = Field(
        default="postgresql://autoai:changeme@postgres:5432/autoai",
        validation_alias="DATABASE_URL",
    )

    # ----- Redis -----
    redis_url: str = Field(default="redis://redis:6379/0", validation_alias="REDIS_URL")

    # ----- MinIO -----
    minio_endpoint: str = Field(default="minio:9000", validation_alias="MINIO_ENDPOINT")
    minio_access_key: str = Field(default="minioadmin", validation_alias="MINIO_ACCESS_KEY")
    minio_secret_key: str = Field(default="minioadmin", validation_alias="MINIO_SECRET_KEY")
    minio_bucket: str = Field(default="autoai-artifacts", validation_alias="MINIO_BUCKET")

    # ----- MLflow -----
    mlflow_tracking_uri: str = Field(default="http://mlflow:5000", validation_alias="MLFLOW_TRACKING_URI")
    mlflow_s3_endpoint_url: str = Field(default="http://minio:9000", validation_alias="MLFLOW_S3_ENDPOINT_URL")

    # ----- Vault -----
    vault_addr: str = Field(default="http://vault:8200", validation_alias="VAULT_ADDR")
    vault_dev_token: str = Field(default="", validation_alias="VAULT_DEV_TOKEN")

    # ----- Security -----
    secret_key: str = Field(default="dev-secret", validation_alias="SECRET_KEY")
    jwt_secret: str = Field(default="dev-jwt", validation_alias="JWT_SECRET")
    jwt_algo: str = Field(default="HS256", validation_alias="JWT_ALGO")
    jwt_expire_min: int = Field(default=60, validation_alias="JWT_EXPIRE_MIN")

    # ----- App -----
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    max_upload_size_mb: int = Field(default=100, validation_alias="MAX_UPLOAD_SIZE_MB")
    pipeline_timeout_min: int = Field(default=30, validation_alias="PIPELINE_TIMEOUT_MIN")
    # Heavy 모델(GPU 카테고리)을 학원 worker-training 에 위임할 때 sync wait 타임아웃.
    # 타임아웃 시 TrainingExecutorAgent 가 CPU 인라인 폴백.
    training_task_timeout_sec: int = Field(default=900, validation_alias="TRAINING_TASK_TIMEOUT_SEC")
    kpi_cache_ttl_seconds: int = Field(default=300, validation_alias="KPI_CACHE_TTL_SECONDS")
    kpi_prometheus_url: str = Field(default="", validation_alias="KPI_PROMETHEUS_URL")
    environment: str = Field(default="development", validation_alias="ENVIRONMENT")
    max_daily_llm_usd: float = Field(default=20.0, validation_alias="MAX_DAILY_LLM_USD")

    # ----- Langfuse (Day03 §1.1 v2.4) -----
    langfuse_host: str = Field(default="", validation_alias="LANGFUSE_HOST")
    langfuse_public_key: str = Field(default="", validation_alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str = Field(default="", validation_alias="LANGFUSE_SECRET_KEY")

    # ----- 팀 KB 수집 (내부망 API 키) -----
    kb_collect_secret: str = Field(default="", validation_alias="KB_COLLECT_SECRET")
    # 리눅스 서버 주소 (Stop 훅 → 직접 전송 시 사용, 미설정이면 웹서버로 전송)
    kb_linux_server_url: str = Field(default="", validation_alias="KB_LINUX_SERVER_URL")

    # ----- Ollama (로컬 LLM 폴백) -----
    # Docker API 컨테이너 → 호스트 Ollama 접근:  http://host.docker.internal:11434
    # 호스트 직접 실행 시:                        http://localhost:11434
    ollama_base_url: str = Field(default="http://localhost:11434", validation_alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="qwen2.5:7b", validation_alias="OLLAMA_MODEL")
    # 코드 오류 수정 전용 모델 (qwen2.5-coder 계열, diff 생성 특화)
    # GTX 1060 3GB 환경: num_gpu=0 CPU 전용, Ryzen 7 3800XT 16T → ~7 t/s
    ollama_coder_model: str = Field(default="qwen2.5-coder:7b", validation_alias="OLLAMA_CODER_MODEL")
    # ──────────────────────────────────────────────────────────
    # 분석 파이프라인 LLM 전환 토글 (G1~G6 + 산출물 전 과정)
    # ──────────────────────────────────────────────────────────
    # True 면 BaseAgent._call_llm 이 Anthropic 대신 Ollama 호출.
    # 에러 핸들러 (auto_error_handler / error_recovery) 의 3순위 Ollama 는
    # 별도 로직이므로 이 토글과 무관하게 유지.
    use_ollama_for_analysis: bool = Field(default=True, validation_alias="USE_OLLAMA_FOR_ANALYSIS")
    # 분석용 Ollama 모델 (Sonnet/Opus 대체) — qwen2.5:7b 고정 (서버·로컬 PC 성능 한계)
    # 14b 는 GTX 1060 3GB + Ryzen 7 환경에서 미지원. 변경 금지.
    ollama_model_analysis: str = Field(default="qwen2.5:7b", validation_alias="OLLAMA_MODEL_ANALYSIS")
    # ──────────────────────────────────────────────────────────
    # Ollama 추론 옵션 (속도 튜닝)
    # ──────────────────────────────────────────────────────────
    # GPU 레이어 수: 0=CPU 전용. GTX 1060 3GB 면 8~12 까지 시도 가능 (7b 32레이어 중 일부).
    ollama_num_gpu: int = Field(default=0, validation_alias="OLLAMA_NUM_GPU")
    # CPU 스레드 수: 순수 CPU 추론은 SMT 포함 가능한 한 많은 스레드가 효율적.
    # Ryzen 7 3800XT = 8C/16T → 14 (시스템용 2 여유).
    ollama_num_thread: int = Field(default=14, validation_alias="OLLAMA_NUM_THREAD")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
