from functools import lru_cache
from secrets import compare_digest

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.core.errors import AuthenticationError, RateLimitError
from app.core.rate_limit import rate_limiter
from app.schemas.contracts import AuditEvent
from app.services.ai import ContractAIService
from app.services.clause_parser import ClauseParser
from app.services.contracts import ContractService
from app.services.jobs import JobService
from app.services.metadata import ContractMetadataExtractor
from app.services.pdf import PDFTextExtractor
from app.storage.contract_store import ContractStore, JsonContractStore
from app.storage.vector_store import ContractVectorRepository

bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache
def get_contract_store() -> ContractStore:
    settings = get_settings()
    if settings.storage_backend == "postgres":
        from app.storage.postgres_store import PostgresContractStore

        return PostgresContractStore(
            database_url=settings.database_url,
            auto_create=settings.database_auto_create,
        )
    return JsonContractStore(settings.contracts_directory)


@lru_cache
def get_vector_repository() -> ContractVectorRepository:
    settings = get_settings()
    return ContractVectorRepository(settings)


@lru_cache
def get_ai_service() -> ContractAIService:
    return ContractAIService(get_settings())


@lru_cache
def get_clause_parser() -> ClauseParser:
    return ClauseParser()


@lru_cache
def get_pdf_extractor() -> PDFTextExtractor:
    return PDFTextExtractor()


@lru_cache
def get_metadata_extractor() -> ContractMetadataExtractor:
    return ContractMetadataExtractor()


def get_contract_service() -> ContractService:
    settings: Settings = get_settings()
    return ContractService(
        settings=settings,
        store=get_contract_store(),
        vector_repository=get_vector_repository(),
        ai_service=get_ai_service(),
        clause_parser=get_clause_parser(),
        pdf_extractor=get_pdf_extractor(),
        metadata_extractor=get_metadata_extractor(),
    )


def get_job_service() -> JobService:
    return JobService(
        settings=get_settings(),
        store=get_contract_store(),
        contract_service=get_contract_service(),
    )


def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    settings = get_settings()
    if not settings.auth_enabled:
        return "anonymous"
    expected = settings.api_auth_token_value
    supplied = credentials.credentials if credentials is not None else ""
    if not expected or not compare_digest(supplied, expected):
        _audit_auth_failure(request)
        raise AuthenticationError("Valid bearer authentication is required.")
    return "api-token"


def rate_limited(request: Request) -> None:
    settings = get_settings()
    actor_key = (
        request.headers.get("Authorization")
        or (request.client.host if request.client else "unknown")
    )
    key = f"{request.method}:{request.url.path}:{actor_key}"
    if not rate_limiter.allow(key, settings.rate_limit_per_minute):
        raise RateLimitError("Rate limit exceeded. Please retry later.")


def _audit_auth_failure(request: Request) -> None:
    try:
        get_contract_store().save_audit_event(
            AuditEvent(
                action="auth.failed",
                actor=request.client.host if request.client else "unknown",
                metadata={"path": request.url.path, "method": request.method},
            )
        )
    except Exception:
        return
