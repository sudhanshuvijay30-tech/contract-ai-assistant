from pathlib import Path

import pytest

from app.core.config import Settings
from app.schemas.contracts import ExtractedPage, RiskAnalysisRequest, VectorSearchResult
from app.services.ai import ContractAIService
from app.services.clause_parser import ClauseParser
from app.services.contracts import ContractService
from app.services.pdf import PDFTextExtractor
from app.storage.contract_store import JsonContractStore


class FakePDFExtractor(PDFTextExtractor):
    def extract_pages(self, content: bytes):
        return [
            ExtractedPage(
                page_number=1,
                text="""
                1. Limitation of Liability
                Each party's aggregate liability shall not exceed fees paid in the
                prior twelve months.

                2. Termination
                Either party may terminate for material breach after a thirty day cure period.
                """,
            )
        ]


class FakeVectorRepository:
    def __init__(self):
        self.indexed = []

    def upsert_clauses(self, clauses):
        self.indexed.extend(clauses)

    def search(self, contract_id: str, query: str, top_k: int):
        return [
            VectorSearchResult(
                clause_id=self.indexed[0].id,
                text=self.indexed[0].text,
                score=0.91,
                metadata={"title": self.indexed[0].title, "type": self.indexed[0].type.value},
            )
        ]


@pytest.mark.asyncio
async def test_contract_service_ingests_pdf_and_runs_rule_analysis(tmp_path: Path):
    vector_repository = FakeVectorRepository()
    settings = Settings(
        contracts_directory=tmp_path / "contracts",
        uploads_directory=tmp_path / "uploads",
        chroma_persist_directory=tmp_path / "chroma",
    )
    service = ContractService(
        settings=settings,
        store=JsonContractStore(settings.contracts_directory),
        vector_repository=vector_repository,
        ai_service=ContractAIService(settings),
        clause_parser=ClauseParser(),
        pdf_extractor=FakePDFExtractor(),
    )

    response = await service.ingest_pdf(
        filename="agreement.pdf",
        content_type="application/pdf",
        content=b"%PDF-1.7 fake bytes",
        use_ai=False,
    )

    assert response.clauses_count == 2
    assert vector_repository.indexed

    risks = await service.analyze_risks(
        response.contract.id,
        RiskAnalysisRequest(use_llm=False),
    )
    assert risks.contract_id == response.contract.id
