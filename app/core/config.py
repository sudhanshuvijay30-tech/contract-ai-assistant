from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="Contract AI Assistant", validation_alias="APP_NAME")
    environment: str = Field(default="production", validation_alias="ENVIRONMENT")

    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-5", validation_alias="OPENAI_MODEL")
    openai_embedding_model: str = Field(
        default="text-embedding-3-large",
        validation_alias="OPENAI_EMBEDDING_MODEL",
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

    max_upload_mb: int = Field(default=25, ge=1, validation_alias="MAX_UPLOAD_MB")
    max_analysis_chars: int = Field(
        default=120_000,
        ge=10_000,
        validation_alias="MAX_ANALYSIS_CHARS",
    )
    llm_timeout_seconds: int = Field(default=60, ge=5, validation_alias="LLM_TIMEOUT_SECONDS")
    llm_max_retries: int = Field(default=2, ge=0, validation_alias="LLM_MAX_RETRIES")
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:8000"],
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
    def openai_api_key_value(self) -> str | None:
        if self.openai_api_key is None:
            return None
        value = self.openai_api_key.get_secret_value().strip()
        return value or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
