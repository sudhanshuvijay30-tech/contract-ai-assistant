from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="Contract AI Assistant", validation_alias="APP_NAME")
    environment: str = Field(default="development", validation_alias="ENVIRONMENT")

    auth_enabled: bool = Field(default=False, validation_alias="AUTH_ENABLED")
    api_auth_token: SecretStr | None = Field(default=None, validation_alias="API_AUTH_TOKEN")
    rate_limit_per_minute: int = Field(
        default=60,
        ge=0,
        validation_alias="RATE_LIMIT_PER_MINUTE",
    )

    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-5", validation_alias="OPENAI_MODEL")
    openai_embedding_model: str = Field(
        default="text-embedding-3-large",
        validation_alias="OPENAI_EMBEDDING_MODEL",
    )
    llm_provider: Literal["ollama", "openai"] = Field(
        default="ollama",
        validation_alias="LLM_PROVIDER",
    )
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        validation_alias="OLLAMA_BASE_URL",
    )
    ollama_chat_model: str = Field(
        default="llama3.1:8b",
        validation_alias="OLLAMA_CHAT_MODEL",
    )
    embedding_provider: Literal["local", "openai"] = Field(
        default="local",
        validation_alias="EMBEDDING_PROVIDER",
    )
    local_embedding_dimensions: int = Field(
        default=384,
        ge=64,
        le=2048,
        validation_alias="LOCAL_EMBEDDING_DIMENSIONS",
    )

    chroma_persist_directory: Path = Field(
        default=Path("data/chroma"),
        validation_alias="CHROMA_PERSIST_DIRECTORY",
    )
    chroma_collection_name: str = Field(
        default="contract_clauses",
        validation_alias="CHROMA_COLLECTION_NAME",
    )
    contracts_directory: Path = Field(
        default=Path("data/contracts"),
        validation_alias="CONTRACTS_DIRECTORY",
    )
    uploads_directory: Path = Field(
        default=Path("data/uploads"),
        validation_alias="UPLOADS_DIRECTORY",
    )
    storage_backend: Literal["json", "postgres"] = Field(
        default="json",
        validation_alias="STORAGE_BACKEND",
    )
    database_url: str = Field(
        default="sqlite:///data/contracts.db",
        validation_alias="DATABASE_URL",
    )
    database_auto_create: bool = Field(
        default=True,
        validation_alias="DATABASE_AUTO_CREATE",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias="REDIS_URL",
    )
    job_backend: Literal["inline", "rq"] = Field(
        default="inline",
        validation_alias="JOB_BACKEND",
    )
    rq_queue_name: str = Field(
        default="contract-ai-assistant",
        validation_alias="RQ_QUEUE_NAME",
    )

    max_upload_mb: int = Field(default=25, ge=1, validation_alias="MAX_UPLOAD_MB")
    allowed_pdf_content_types: list[str] = Field(
        default_factory=lambda: [
            "application/pdf",
            "application/x-pdf",
            "application/octet-stream",
        ],
        validation_alias="ALLOWED_PDF_CONTENT_TYPES",
    )
    max_analysis_chars: int = Field(
        default=120_000,
        ge=10_000,
        validation_alias="MAX_ANALYSIS_CHARS",
    )
    llm_timeout_seconds: int = Field(default=60, ge=5, validation_alias="LLM_TIMEOUT_SECONDS")
    llm_max_retries: int = Field(default=2, ge=0, validation_alias="LLM_MAX_RETRIES")
    allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:8000",
            "http://localhost:8501",
        ],
        validation_alias="ALLOWED_ORIGINS",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def api_auth_token_value(self) -> str | None:
        if self.api_auth_token is None:
            return None
        value = self.api_auth_token.get_secret_value().strip()
        return value or None

    @property
    def openai_api_key_value(self) -> str | None:
        if self.openai_api_key is None:
            return None
        value = self.openai_api_key.get_secret_value().strip()
        return value or None

    @property
    def active_chat_model(self) -> str:
        if self.llm_provider == "ollama":
            return self.ollama_chat_model
        return self.openai_model

    @field_validator("allowed_origins", "allowed_pdf_content_types", mode="before")
    @classmethod
    def _split_env_list(cls, value: object) -> object:
        if isinstance(value, str) and value and not value.strip().startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    def validate_runtime(self) -> None:
        production = self.environment.lower() in {"prod", "production"}
        if production and self.auth_enabled and not self.api_auth_token_value:
            raise RuntimeError(
                "API_AUTH_TOKEN must be configured when AUTH_ENABLED=true in production."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
