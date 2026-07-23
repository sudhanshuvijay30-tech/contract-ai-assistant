from app.core.config import Settings
from app.graphs.contract_graph import (
    ClauseComparisonWorkflow,
    ContractIngestionWorkflow,
    ContractQuestionWorkflow,
    RiskAnalysisWorkflow,
)
from app.schemas.contracts import (
    AIProvider,
    AskContractRequest,
    AskContractResponse,
    AuditEvent,
    ClauseComparisonRequest,
    ClauseComparisonResponse,
    ClauseListResponse,
    ContractMetadata,
    ContractRecord,
    ContractUploadResponse,
    RiskAnalysisRequest,
)
from app.services.ai import ContractAIService
from app.services.clause_parser import ClauseParser
from app.services.comparison import ClauseComparator
from app.services.metadata import ContractMetadataExtractor
from app.services.pdf import PDFTextExtractor
from app.services.risk_rules import RiskRuleEngine
from app.storage.contract_store import ContractStore
from app.storage.vector_store import ContractVectorRepository


class ContractService:
    def __init__(
        self,
        settings: Settings,
        store: ContractStore,
        vector_repository: ContractVectorRepository,
        ai_service: ContractAIService,
        clause_parser: ClauseParser,
        pdf_extractor: PDFTextExtractor,
        metadata_extractor: ContractMetadataExtractor,
    ):
        self.settings = settings
        self.store = store
        self.vector_repository = vector_repository
        self.ai_service = ai_service
        self.clause_parser = clause_parser
        self.pdf_extractor = pdf_extractor
        self.metadata_extractor = metadata_extractor
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
        metadata: ContractMetadata | None = None,
        actor: str = "system",
    ) -> ContractUploadResponse:
        workflow = ContractIngestionWorkflow(
            settings=self.settings,
            store=self.store,
            vector_repository=self.vector_repository,
            ai_service=self.ai_service,
            clause_parser=self.clause_parser,
            pdf_extractor=self.pdf_extractor,
            metadata_extractor=self.metadata_extractor,
        )
        response = await workflow.run(
            filename,
            content_type,
            content,
            use_ai,
            llm_provider,
            llm_model,
            metadata,
        )
        self.audit(
            "contract.uploaded",
            actor=actor,
            contract_id=response.contract.id,
            metadata={
                "filename": response.contract.filename,
                "clauses_count": response.clauses_count,
                "use_ai": use_ai,
            },
        )
        return response

    def get_contract(self, contract_id: str) -> ContractRecord:
        return self.store.get_contract(contract_id)

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
        self.audit(
            "contract.risk_analysis.completed",
            contract_id=contract_id,
            metadata={"use_llm": request.use_llm, "risk_count": len(result.risks)},
        )
        return result

    async def compare_clauses(
        self,
        request: ClauseComparisonRequest,
    ) -> ClauseComparisonResponse:
        workflow = ClauseComparisonWorkflow(self.ai_service, self.comparator)
        result = await workflow.run(request)
        self.audit(
            "contract.clause_comparison.completed",
            metadata={"use_llm": request.use_llm, "risk_delta": result.risk_delta.value},
        )
        return result

    async def ask_contract(
        self,
        contract_id: str,
        request: AskContractRequest,
    ) -> AskContractResponse:
        workflow = ContractQuestionWorkflow(
            store=self.store,
            vector_repository=self.vector_repository,
            ai_service=self.ai_service,
        )
        result = await workflow.run(contract_id, request)
        self.audit(
            "contract.question_answered",
            contract_id=contract_id,
            metadata={"use_llm": request.use_llm, "source_count": len(result.sources)},
        )
        return result

    def audit(
        self,
        action: str,
        actor: str = "system",
        contract_id: str | None = None,
        job_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        self.store.save_audit_event(
            AuditEvent(
                action=action,
                actor=actor,
                contract_id=contract_id,
                job_id=job_id,
                metadata=metadata or {},
            )
        )
