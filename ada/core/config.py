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
    mlflow_tracking_uri: str = Field(default="http://mlflow:5000",
                                     validation_alias="MLFLOW_TRACKING_URI")
    mlflow_s3_endpoint_url: str = Field(default="http://minio:9000",
                                        validation_alias="MLFLOW_S3_ENDPOINT_URL")

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
    environment: str = Field(default="development", validation_alias="ENVIRONMENT")
    max_daily_llm_usd: float = Field(default=20.0, validation_alias="MAX_DAILY_LLM_USD")

    # ----- Langfuse (Day03 §1.1 v2.4) -----
    langfuse_host: str = Field(default="", validation_alias="LANGFUSE_HOST")
    langfuse_public_key: str = Field(default="", validation_alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str = Field(default="", validation_alias="LANGFUSE_SECRET_KEY")

    @property
    def database_url_async(self) -> str:
        if self.database_url.startswith("postgresql://"):
            return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return self.database_url

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in ("production", "prod")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """모듈 레벨 싱글턴 캐시. 테스트에서는 lru_cache.cache_clear() 사용."""
    return Settings()


settings = get_settings()
