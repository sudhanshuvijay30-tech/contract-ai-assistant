from fastapi import APIRouter, Body, Depends, File, Query, UploadFile, status

from app import __version__
from app.api.deps import get_contract_service
from app.core.config import get_settings
from app.schemas.contracts import (
    AskContractRequest,
    AskContractResponse,
    ClauseComparisonRequest,
    ClauseComparisonResponse,
    ClauseListResponse,
    ContractUploadResponse,
    HealthResponse,
    RiskAnalysisRequest,
    RiskAnalysisResponse,
)
from app.services.contracts import ContractService

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        version=__version__,
        environment=settings.environment,
        model=settings.openai_model,
    )


@router.post(
    "/contracts/upload",
    response_model=ContractUploadResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["contracts"],
)
async def upload_contract(
    file: UploadFile = File(...),
    use_ai: bool = Query(False, description="Use GPT-5 to refine deterministic clause extraction."),
    service: ContractService = Depends(get_contract_service),
) -> ContractUploadResponse:
    content = await file.read()
    return await service.ingest_pdf(
        filename=file.filename or "contract.pdf",
        content_type=file.content_type or "application/pdf",
        content=content,
        use_ai=use_ai,
    )


@router.get(
    "/contracts/{contract_id}/clauses",
    response_model=ClauseListResponse,
    tags=["contracts"],
)
def list_clauses(
    contract_id: str,
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
    service: ContractService = Depends(get_contract_service),
) -> AskContractResponse:
    return await service.ask_contract(contract_id, request)

