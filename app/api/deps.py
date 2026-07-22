from functools import lru_cache

from app.core.config import Settings, get_settings
from app.services.ai import ContractAIService
from app.services.clause_parser import ClauseParser
from app.services.contracts import ContractService
from app.services.pdf import PDFTextExtractor
from app.storage.contract_store import JsonContractStore
from app.storage.vector_store import ContractVectorRepository


@lru_cache
def get_contract_store() -> JsonContractStore:
    settings = get_settings()
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


def get_contract_service() -> ContractService:
    settings: Settings = get_settings()
    return ContractService(
        settings=settings,
        store=get_contract_store(),
        vector_repository=get_vector_repository(),
        ai_service=get_ai_service(),
        clause_parser=get_clause_parser(),
        pdf_extractor=get_pdf_extractor(),
    )

