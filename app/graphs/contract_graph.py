import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from app.core.config import Settings
from app.core.errors import BadRequestError
from app.schemas.contracts import (
    Clause,
    ContractRecord,
    ContractStatus,
    ContractUploadResponse,
    ExtractedPage,
    RiskAnalysisResponse,
)
from app.services.ai import ContractAIService
from app.services.clause_parser import ClauseParser
from app.services.pdf import PDFTextExtractor
from app.services.risk_rules import RiskRuleEngine
from app.storage.contract_store import JsonContractStore
from app.storage.vector_store import ContractVectorRepository


class IngestionState(TypedDict, total=False):
    filename: str
    content_type: str
    content: bytes
    use_ai: bool
    contract: ContractRecord
    pages: list[ExtractedPage]
    raw_text: str
    clauses: list[Clause]


class RiskAnalysisState(TypedDict, total=False):
    contract_id: str
    clauses: list[Clause]
    contract_text: str
    use_llm: bool
    result: RiskAnalysisResponse


class ContractIngestionWorkflow:
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

    async def run(
        self,
        filename: str,
        content_type: str,
        content: bytes,
        use_ai: bool,
    ) -> ContractUploadResponse:
        graph = self._build_graph()
        state = await graph.ainvoke(
            {
                "filename": filename,
                "content_type": content_type,
                "content": content,
                "use_ai": use_ai,
            }
        )
        return ContractUploadResponse(
            contract=state["contract"],
            clauses_count=len(state["clauses"]),
            vector_collection=getattr(
                self.vector_repository,
                "collection_name",
                self.settings.chroma_collection_name,
            ),
        )

    def _build_graph(self):
        try:
            from langgraph.graph import END, START, StateGraph
        except ImportError as exc:
            raise RuntimeError("langgraph is required for contract workflows") from exc

        graph = StateGraph(IngestionState)
        graph.add_node("extract_pdf", self._extract_pdf)
        graph.add_node("parse_clauses", self._parse_clauses)
        graph.add_node("refine_clauses", self._refine_clauses)
        graph.add_node("persist_contract", self._persist_contract)
        graph.add_node("index_clauses", self._index_clauses)
        graph.add_edge(START, "extract_pdf")
        graph.add_edge("extract_pdf", "parse_clauses")
        graph.add_conditional_edges(
            "parse_clauses",
            self._should_refine,
            {"refine": "refine_clauses", "persist": "persist_contract"},
        )
        graph.add_edge("refine_clauses", "persist_contract")
        graph.add_edge("persist_contract", "index_clauses")
        graph.add_edge("index_clauses", END)
        return graph.compile()

    async def _extract_pdf(self, state: IngestionState) -> IngestionState:
        content = state["content"]
        filename = state["filename"]
        content_type = state["content_type"]
        self._validate_upload(filename, content_type, content)

        pages = self.pdf_extractor.extract_pages(content)
        raw_text = "\n\n".join(page.text for page in pages if page.text.strip())
        sha256 = hashlib.sha256(content).hexdigest()
        contract_id = sha256[:16]
        record = ContractRecord(
            id=contract_id,
            filename=Path(filename).name,
            content_type=content_type,
            sha256=sha256,
            size_bytes=len(content),
            page_count=len(pages),
            created_at=datetime.now(UTC),
            status=ContractStatus.INGESTED,
        )
        upload_path = self.settings.uploads_directory / f"{contract_id}.pdf"
        upload_path.parent.mkdir(parents=True, exist_ok=True)
        upload_path.write_bytes(content)
        return {"contract": record, "pages": pages, "raw_text": raw_text}

    async def _parse_clauses(self, state: IngestionState) -> IngestionState:
        clauses = self.clause_parser.extract(state["contract"].id, state["pages"])
        if not clauses:
            raise BadRequestError("No contract clauses could be extracted from the PDF.")
        return {"clauses": clauses}

    async def _refine_clauses(self, state: IngestionState) -> IngestionState:
        clauses = await self.ai_service.extract_clauses(
            state["contract"].id,
            state["raw_text"],
            state["clauses"],
        )
        return {"clauses": clauses}

    async def _persist_contract(self, state: IngestionState) -> IngestionState:
        self.store.save_contract(state["contract"], state["clauses"], state["raw_text"])
        return {}

    async def _index_clauses(self, state: IngestionState) -> IngestionState:
        self.vector_repository.upsert_clauses(state["clauses"])
        return {}

    def _should_refine(self, state: IngestionState) -> str:
        return "refine" if state.get("use_ai") else "persist"

    def _validate_upload(self, filename: str, content_type: str, content: bytes) -> None:
        if len(content) > self.settings.max_upload_bytes:
            raise BadRequestError(f"PDF exceeds {self.settings.max_upload_mb} MB upload limit.")
        if not filename.lower().endswith(".pdf") and content_type != "application/pdf":
            raise BadRequestError("Only PDF uploads are supported.")
        if not content.lstrip().startswith(b"%PDF"):
            raise BadRequestError("Uploaded file does not appear to be a PDF.")


class RiskAnalysisWorkflow:
    def __init__(self, ai_service: ContractAIService, rule_engine: RiskRuleEngine):
        self.ai_service = ai_service
        self.rule_engine = rule_engine

    async def run(
        self,
        contract_id: str,
        clauses: list[Clause],
        contract_text: str,
        use_llm: bool,
    ) -> RiskAnalysisResponse:
        graph = self._build_graph()
        state = await graph.ainvoke(
            {
                "contract_id": contract_id,
                "clauses": clauses,
                "contract_text": contract_text,
                "use_llm": use_llm,
            }
        )
        return state["result"]

    def _build_graph(self):
        try:
            from langgraph.graph import END, START, StateGraph
        except ImportError as exc:
            raise RuntimeError("langgraph is required for risk workflows") from exc

        graph = StateGraph(RiskAnalysisState)
        graph.add_node("rule_baseline", self._rule_baseline)
        graph.add_node("gpt5_analysis", self._gpt5_analysis)
        graph.add_edge(START, "rule_baseline")
        graph.add_conditional_edges(
            "rule_baseline",
            self._should_call_llm,
            {"llm": "gpt5_analysis", "done": END},
        )
        graph.add_edge("gpt5_analysis", END)
        return graph.compile()

    async def _rule_baseline(self, state: RiskAnalysisState) -> RiskAnalysisState:
        return {
            "result": self.rule_engine.analyze(
                contract_id=state["contract_id"],
                clauses=state["clauses"],
            )
        }

    async def _gpt5_analysis(self, state: RiskAnalysisState) -> RiskAnalysisState:
        return {
            "result": await self.ai_service.analyze_risks(
                contract_id=state["contract_id"],
                clauses=state["clauses"],
                contract_text=state["contract_text"],
            )
        }

    def _should_call_llm(self, state: RiskAnalysisState) -> str:
        return "llm" if state.get("use_llm") else "done"
