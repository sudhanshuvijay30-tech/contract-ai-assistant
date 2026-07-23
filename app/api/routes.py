from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Query, UploadFile, status
from fastapi.responses import PlainTextResponse

from app import __version__
from app.api.deps import get_contract_service, get_job_service, rate_limited, require_auth
from app.core.config import get_settings
from app.core.metrics import metrics_registry
from app.schemas.contracts import (
    AIProvider,
    AskContractRequest,
    AskContractResponse,
    AsyncUploadResponse,
    ClauseComparisonRequest,
    ClauseComparisonResponse,
    ClauseListResponse,
    ContractMetadata,
    ContractRecord,
    ContractUploadResponse,
    HealthResponse,
    JobResponse,
    RiskAnalysisRequest,
    RiskAnalysisResponse,
)
from app.services.contracts import ContractService
from app.services.jobs import JobService

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        version=__version__,
        environment=settings.environment,
        model=settings.active_chat_model,
        llm_provider=settings.llm_provider,
        embedding_provider=settings.embedding_provider,
        auth_enabled=settings.auth_enabled,
        storage_backend=settings.storage_backend,
        job_backend=settings.job_backend,
    )


@router.get("/metrics", response_class=PlainTextResponse, tags=["system"])
def metrics(
    _actor: str = Depends(require_auth),
    _rate_limit: None = Depends(rate_limited),
) -> str:
    return metrics_registry.render_prometheus()


@router.post(
    "/contracts/upload",
    response_model=ContractUploadResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["contracts"],
)
async def upload_contract(
    file: UploadFile = File(...),
    use_ai: bool = Query(False, description="Use AI to refine deterministic clause extraction."),
    llm_provider: AIProvider | None = Query(
        None,
        description="Override the configured LLM provider for this upload refinement.",
    ),
    llm_model: str | None = Query(
        None,
        description="Override the configured LLM model for this upload refinement.",
    ),
    contract_type: str | None = Query(None),
    jurisdiction: str | None = Query(None),
    governing_law: str | None = Query(None),
    effective_date: str | None = Query(None),
    renewal_term: str | None = Query(None),
    customer: str | None = Query(None),
    supplier: str | None = Query(None),
    actor: str = Depends(require_auth),
    _rate_limit: None = Depends(rate_limited),
    service: ContractService = Depends(get_contract_service),
) -> ContractUploadResponse:
    content = await file.read()
    return await service.ingest_pdf(
        filename=file.filename or "contract.pdf",
        content_type=file.content_type or "application/pdf",
        content=content,
        use_ai=use_ai,
        llm_provider=llm_provider,
        llm_model=llm_model,
        metadata=_metadata(
            contract_type,
            jurisdiction,
            governing_law,
            effective_date,
            renewal_term,
            customer,
            supplier,
        ),
        actor=actor,
    )


@router.post(
    "/contracts/upload-async",
    response_model=AsyncUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["contracts"],
)
async def upload_contract_async(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    use_ai: bool = Query(False, description="Use AI to refine deterministic clause extraction."),
    llm_provider: AIProvider | None = Query(None),
    llm_model: str | None = Query(None),
    contract_type: str | None = Query(None),
    jurisdiction: str | None = Query(None),
    governing_law: str | None = Query(None),
    effective_date: str | None = Query(None),
    renewal_term: str | None = Query(None),
    customer: str | None = Query(None),
    supplier: str | None = Query(None),
    actor: str = Depends(require_auth),
    _rate_limit: None = Depends(rate_limited),
    jobs: JobService = Depends(get_job_service),
) -> AsyncUploadResponse:
    content = await file.read()
    job = jobs.enqueue_contract_ingestion(
        background_tasks=background_tasks,
        filename=file.filename or "contract.pdf",
        content_type=file.content_type or "application/pdf",
        content=content,
        use_ai=use_ai,
        llm_provider=llm_provider,
        llm_model=llm_model,
        metadata=_metadata(
            contract_type,
            jurisdiction,
            governing_law,
            effective_date,
            renewal_term,
            customer,
            supplier,
        ),
        actor=actor,
    )
    return AsyncUploadResponse(job=job)


@router.get("/jobs/{job_id}", response_model=JobResponse, tags=["contracts"])
def get_job(
    job_id: str,
    _actor: str = Depends(require_auth),
    _rate_limit: None = Depends(rate_limited),
    jobs: JobService = Depends(get_job_service),
) -> JobResponse:
    return JobResponse(job=jobs.get_job(job_id))


@router.get("/contracts/{contract_id}", response_model=ContractRecord, tags=["contracts"])
def get_contract(
    contract_id: str,
    _actor: str = Depends(require_auth),
    _rate_limit: None = Depends(rate_limited),
    service: ContractService = Depends(get_contract_service),
) -> ContractRecord:
    return service.get_contract(contract_id)


@router.get(
    "/contracts/{contract_id}/clauses",
    response_model=ClauseListResponse,
    tags=["contracts"],
)
def list_clauses(
    contract_id: str,
    _actor: str = Depends(require_auth),
    _rate_limit: None = Depends(rate_limited),
    service: ContractService = Depends(get_contract_service),
) -> ClauseListResponse:
    return service.list_clauses(contract_id)


@router.post(
    "/contracts/{contract_id}/risks",
    response_model=RiskAnalysisResponse,
    tags=["analysis"],
)
async def analyze_risks(
    contract_id: str,
    request: RiskAnalysisRequest = Body(default_factory=RiskAnalysisRequest),
    _actor: str = Depends(require_auth),
    _rate_limit: None = Depends(rate_limited),
    service: ContractService = Depends(get_contract_service),
) -> RiskAnalysisResponse:
    return await service.analyze_risks(contract_id, request)


@router.post(
    "/compare",
    response_model=ClauseComparisonResponse,
    tags=["analysis"],
)
async def compare_clauses(
    request: ClauseComparisonRequest,
    _actor: str = Depends(require_auth),
    _rate_limit: None = Depends(rate_limited),
    service: ContractService = Depends(get_contract_service),
) -> ClauseComparisonResponse:
    return await service.compare_clauses(request)


@router.post(
    "/contracts/{contract_id}/ask",
    response_model=AskContractResponse,
    tags=["assistant"],
)
async def ask_contract(
    contract_id: str,
    request: AskContractRequest,
    _actor: str = Depends(require_auth),
    _rate_limit: None = Depends(rate_limited),
    service: ContractService = Depends(get_contract_service),
) -> AskContractResponse:
    return await service.ask_contract(contract_id, request)


def _metadata(
    contract_type: str | None,
    jurisdiction: str | None,
    governing_law: str | None,
    effective_date: str | None,
    renewal_term: str | None,
    customer: str | None,
    supplier: str | None,
) -> ContractMetadata:
    return ContractMetadata(
        contract_type=_blank_to_none(contract_type),
        jurisdiction=_blank_to_none(jurisdiction),
        governing_law=_blank_to_none(governing_law),
        effective_date=_blank_to_none(effective_date),
        renewal_term=_blank_to_none(renewal_term),
        customer=_blank_to_none(customer),
        supplier=_blank_to_none(supplier),
    )


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
