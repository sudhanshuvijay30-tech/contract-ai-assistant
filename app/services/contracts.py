from app.core.config import Settings
from app.core.errors import NotFoundError
from app.graphs.contract_graph import ContractIngestionWorkflow, RiskAnalysisWorkflow
from app.schemas.contracts import (
    AIProvider,
    AskContractRequest,
    AskContractResponse,
    ClauseComparisonRequest,
    ClauseComparisonResponse,
    ClauseListResponse,
    ContractUploadResponse,
    RiskAnalysisRequest,
)
from app.services.ai import ContractAIService
from app.services.clause_parser import ClauseParser
from app.services.comparison import ClauseComparator
from app.services.pdf import PDFTextExtractor
from app.services.risk_rules import RiskRuleEngine
from app.storage.contract_store import JsonContractStore
from app.storage.vector_store import ContractVectorRepository


class ContractService:
    def __init__(
        self,
        settings: Settings,
        store: JsonContractStore,
        vector_repository: ContractVectorRepository,
        ai_service: ContractAIService,
        clause_parser: ClauseParser,
        pdf_extractor: PDFTextExtractor,
    ):
        self.settings = settings
        self.store = store
        self.vector_repository = vector_repository
        self.ai_service = ai_service
        self.clause_parser = clause_parser
        self.pdf_extractor = pdf_extractor
        self.risk_rules = RiskRuleEngine()
        self.comparator = ClauseComparator()

    async def ingest_pdf(
        self,
        filename: str,
        content_type: str,
        content: bytes,
        use_ai: bool,
        llm_provider: AIProvider | None = None,
        llm_model: str | None = None,
    ) -> ContractUploadResponse:
        workflow = ContractIngestionWorkflow(
            settings=self.settings,
            store=self.store,
            vector_repository=self.vector_repository,
            ai_service=self.ai_service,
            clause_parser=self.clause_parser,
            pdf_extractor=self.pdf_extractor,
        )
        return await workflow.run(filename, content_type, content, use_ai, llm_provider, llm_model)

    def list_clauses(self, contract_id: str) -> ClauseListResponse:
        clauses = self.store.get_clauses(contract_id)
        return ClauseListResponse(contract_id=contract_id, clauses=clauses)

    async def analyze_risks(
        self,
        contract_id: str,
        request: RiskAnalysisRequest,
    ):
        contract = self.store.get_contract(contract_id)
        clauses = self.store.get_clauses(contract_id)
        raw_text = self.store.get_contract_text(contract_id)
        workflow = RiskAnalysisWorkflow(ai_service=self.ai_service, rule_engine=self.risk_rules)
        result = await workflow.run(
            contract_id=contract.id,
            clauses=clauses,
            contract_text=raw_text,
            use_llm=request.use_llm,
            llm_provider=request.llm_provider,
            llm_model=request.llm_model,
        )
        self.store.update_status(contract_id, "analyzed")
        return result

    async def compare_clauses(
        self,
        request: ClauseComparisonRequest,
    ) -> ClauseComparisonResponse:
        if request.use_llm:
            return await self.ai_service.compare_clauses(request)
        return self.comparator.compare(request)

    async def ask_contract(
        self,
        contract_id: str,
        request: AskContractRequest,
    ) -> AskContractResponse:
        self.store.get_contract(contract_id)
        results = self.vector_repository.search(contract_id, request.question, request.top_k)
        clauses = {clause.id: clause for clause in self.store.get_clauses(contract_id)}
        sources = [
            result.to_source_snippet(clauses.get(result.clause_id))
            for result in results
            if result.clause_id in clauses
        ]
        if not sources:
            raise NotFoundError("No relevant clauses were found for that question.")
        if request.use_llm:
            return await self.ai_service.answer_question(
                contract_id,
                request.question,
                sources,
                llm_provider=request.llm_provider,
                llm_model=request.llm_model,
            )
        joined_sources = "\n\n".join(f"{source.title}: {source.text}" for source in sources[:3])
        return AskContractResponse(
            contract_id=contract_id,
            question=request.question,
            answer=f"Relevant contract excerpts:\n\n{joined_sources}",
            confidence=0.55,
            sources=sources,
        )
