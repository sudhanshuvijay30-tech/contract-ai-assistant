import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from app.core.config import Settings
from app.core.errors import BadRequestError, NotFoundError
from app.schemas.contracts import (
    AgentTrace,
    AIProvider,
    AskContractRequest,
    AskContractResponse,
    Clause,
    ClauseComparisonRequest,
    ClauseComparisonResponse,
    ContractMetadata,
    ContractRecord,
    ContractStatus,
    ContractUploadResponse,
    ExtractedPage,
    RiskAnalysisResponse,
    SourceSnippet,
    VectorSearchResult,
)
from app.services.ai import ContractAIService
from app.services.clause_parser import ClauseParser
from app.services.comparison import ClauseComparator
from app.services.metadata import ContractMetadataExtractor
from app.services.pdf import PDFTextExtractor
from app.services.risk_rules import RiskRuleEngine
from app.storage.contract_store import ContractStore
from app.storage.vector_store import ContractVectorRepository


class IngestionState(TypedDict, total=False):
    filename: str
    content_type: str
    content: bytes
    use_ai: bool
    llm_provider: AIProvider | None
    llm_model: str | None
    metadata: ContractMetadata | None
    contract: ContractRecord
    pages: list[ExtractedPage]
    raw_text: str
    clauses: list[Clause]
    agent_trace: list[AgentTrace]


class RiskAnalysisState(TypedDict, total=False):
    contract_id: str
    clauses: list[Clause]
    contract_text: str
    use_llm: bool
    llm_provider: AIProvider | None
    llm_model: str | None
    result: RiskAnalysisResponse
    agent_trace: list[AgentTrace]


class ClauseComparisonState(TypedDict, total=False):
    request: ClauseComparisonRequest
    result: ClauseComparisonResponse
    agent_trace: list[AgentTrace]


class QuestionAnswerState(TypedDict, total=False):
    contract_id: str
    request: AskContractRequest
    clauses: list[Clause]
    sources: list[SourceSnippet]
    results: list[VectorSearchResult]
    result: AskContractResponse
    agent_trace: list[AgentTrace]


class ContractIngestionWorkflow:
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

    async def run(
        self,
        filename: str,
        content_type: str,
        content: bytes,
        use_ai: bool,
        llm_provider: AIProvider | None = None,
        llm_model: str | None = None,
        metadata: ContractMetadata | None = None,
    ) -> ContractUploadResponse:
        graph = self._build_graph()
        state = await graph.ainvoke(
            {
                "filename": filename,
                "content_type": content_type,
                "content": content,
                "use_ai": use_ai,
                "llm_provider": llm_provider,
                "llm_model": llm_model,
                "metadata": metadata,
                "agent_trace": [],
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
            agent_trace=state.get("agent_trace", []),
        )

    def _build_graph(self):
        try:
            from langgraph.graph import END, START, StateGraph
        except ImportError as exc:
            raise RuntimeError("langgraph is required for contract workflows") from exc

        graph = StateGraph(IngestionState)
        graph.add_node("ingestion_agent", self._ingestion_agent)
        graph.add_node("clause_extraction_agent", self._clause_extraction_agent)
        graph.add_node("clause_refinement_agent", self._clause_refinement_agent)
        graph.add_node("metadata_agent", self._metadata_agent)
        graph.add_node("persistence_agent", self._persistence_agent)
        graph.add_node("retriever_index_agent", self._retriever_index_agent)
        graph.add_edge(START, "ingestion_agent")
        graph.add_edge("ingestion_agent", "clause_extraction_agent")
        graph.add_conditional_edges(
            "clause_extraction_agent",
            self._should_refine,
            {"refine": "clause_refinement_agent", "metadata": "metadata_agent"},
        )
        graph.add_edge("clause_refinement_agent", "metadata_agent")
        graph.add_edge("metadata_agent", "persistence_agent")
        graph.add_edge("persistence_agent", "retriever_index_agent")
        graph.add_edge("retriever_index_agent", END)
        return graph.compile()

    async def _ingestion_agent(self, state: IngestionState) -> IngestionState:
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
        return {
            "contract": record,
            "pages": pages,
            "raw_text": raw_text,
            "agent_trace": [
                *state.get("agent_trace", []),
                AgentTrace(
                    agent_name="Ingestion Agent",
                    summary=f"Validated and extracted {len(pages)} page(s) from the uploaded PDF.",
                    details={"sha256": sha256, "size_bytes": len(content)},
                ),
            ],
        }

    async def _clause_extraction_agent(self, state: IngestionState) -> IngestionState:
        clauses = self.clause_parser.extract(state["contract"].id, state["pages"])
        if not clauses:
            raise BadRequestError("No contract clauses could be extracted from the PDF.")
        return {
            "clauses": clauses,
            "agent_trace": [
                *state.get("agent_trace", []),
                AgentTrace(
                    agent_name="Clause Extraction Agent",
                    summary=f"Extracted {len(clauses)} clause candidate(s).",
                ),
            ],
        }

    async def _clause_refinement_agent(self, state: IngestionState) -> IngestionState:
        clauses = await self.ai_service.extract_clauses(
            state["contract"].id,
            state["raw_text"],
            state["clauses"],
            llm_provider=state.get("llm_provider"),
            llm_model=state.get("llm_model"),
        )
        return {
            "clauses": clauses,
            "agent_trace": [
                *state.get("agent_trace", []),
                AgentTrace(
                    agent_name="Clause Refinement Agent",
                    summary=(
                        "Refined clause boundaries with "
                        f"{state.get('llm_model') or 'configured model'}."
                    ),
                ),
            ],
        }

    async def _metadata_agent(self, state: IngestionState) -> IngestionState:
        metadata = self.metadata_extractor.extract(
            state["filename"],
            state["raw_text"],
            state.get("metadata"),
        )
        contract = state["contract"].model_copy(update={"metadata": metadata})
        return {
            "contract": contract,
            "agent_trace": [
                *state.get("agent_trace", []),
                AgentTrace(
                    agent_name="Metadata Agent",
                    summary="Extracted contract metadata for enterprise retrieval filters.",
                    details=metadata.model_dump(mode="json"),
                ),
            ],
        }

    async def _persistence_agent(self, state: IngestionState) -> IngestionState:
        self.store.save_contract(state["contract"], state["clauses"], state["raw_text"])
        return {
            "agent_trace": [
                *state.get("agent_trace", []),
                AgentTrace(
                    agent_name="Persistence Agent",
                    summary=f"Saved contract metadata and {len(state['clauses'])} clause(s).",
                ),
            ]
        }

    async def _retriever_index_agent(self, state: IngestionState) -> IngestionState:
        self.vector_repository.upsert_clauses(
            state["clauses"],
            contract_metadata=state["contract"].metadata,
        )
        return {
            "agent_trace": [
                *state.get("agent_trace", []),
                AgentTrace(
                    agent_name="Retriever Agent",
                    summary="Indexed clauses in ChromaDB with contract metadata filters.",
                ),
            ]
        }

    def _should_refine(self, state: IngestionState) -> str:
        return "refine" if state.get("use_ai") else "metadata"

    def _validate_upload(self, filename: str, content_type: str, content: bytes) -> None:
        if len(content) > self.settings.max_upload_bytes:
            raise BadRequestError(f"PDF exceeds {self.settings.max_upload_mb} MB upload limit.")
        safe_name = Path(filename).name.strip()
        if not safe_name or not safe_name.lower().endswith(".pdf"):
            raise BadRequestError("Only PDF uploads are supported.")
        if content_type not in set(self.settings.allowed_pdf_content_types):
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
        llm_provider: AIProvider | None = None,
        llm_model: str | None = None,
    ) -> RiskAnalysisResponse:
        graph = self._build_graph()
        state = await graph.ainvoke(
            {
                "contract_id": contract_id,
                "clauses": clauses,
                "contract_text": contract_text,
                "use_llm": use_llm,
                "llm_provider": llm_provider,
                "llm_model": llm_model,
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
        graph.add_node("legal_analysis_agent", self._legal_analysis_agent)
        graph.add_node("compliance_agent", self._compliance_agent)
        graph.add_node("negotiation_agent", self._negotiation_agent)
        graph.add_edge(START, "rule_baseline")
        graph.add_conditional_edges(
            "rule_baseline",
            self._should_call_llm,
            {"llm": "legal_analysis_agent", "done": "compliance_agent"},
        )
        graph.add_edge("legal_analysis_agent", "compliance_agent")
        graph.add_edge("compliance_agent", "negotiation_agent")
        graph.add_edge("negotiation_agent", END)
        return graph.compile()

    async def _rule_baseline(self, state: RiskAnalysisState) -> RiskAnalysisState:
        return {
            "result": self.rule_engine.analyze(
                contract_id=state["contract_id"],
                clauses=state["clauses"],
            ),
            "agent_trace": [
                *state.get("agent_trace", []),
                AgentTrace(
                    agent_name="Risk Agent",
                    summary="Generated rule-based baseline risk findings.",
                ),
            ],
        }

    async def _legal_analysis_agent(self, state: RiskAnalysisState) -> RiskAnalysisState:
        return {
            "result": await self.ai_service.analyze_risks(
                contract_id=state["contract_id"],
                clauses=state["clauses"],
                contract_text=state["contract_text"],
                llm_provider=state.get("llm_provider"),
                llm_model=state.get("llm_model"),
            ),
            "agent_trace": [
                *state.get("agent_trace", []),
                AgentTrace(
                    agent_name="Legal Analysis Agent",
                    summary="Generated LLM-assisted risk analysis.",
                ),
            ],
        }

    async def _compliance_agent(self, state: RiskAnalysisState) -> RiskAnalysisState:
        result = state["result"]
        findings = list(result.compliance_findings)
        clause_types = {clause.type.value for clause in state["clauses"]}
        if (
            "governing_law" not in clause_types
            and "No governing law clause was detected." not in findings
        ):
            findings.append("No governing law clause was detected.")
        if (
            "data_protection" not in clause_types
            and "No dedicated data protection clause was detected." not in findings
        ):
            findings.append("No dedicated data protection clause was detected.")
        return {
            "result": result.model_copy(update={"compliance_findings": findings}),
            "agent_trace": [
                *state.get("agent_trace", []),
                AgentTrace(
                    agent_name="Compliance Agent",
                    summary=f"Added {len(findings)} compliance checkpoint(s).",
                ),
            ],
        }

    async def _negotiation_agent(self, state: RiskAnalysisState) -> RiskAnalysisState:
        result = state["result"]
        recommendations = list(result.negotiation_recommendations)
        if not recommendations:
            recommendations = [
                "Resolve high-risk items before commercial language cleanup.",
                "Document accepted deviations in the approval record.",
            ]
        trace = [
            *state.get("agent_trace", []),
            AgentTrace(
                agent_name="Negotiation Agent",
                summary=f"Generated {len(recommendations)} negotiation recommendation(s).",
            ),
        ]
        return {
            "result": result.model_copy(
                update={
                    "negotiation_recommendations": recommendations,
                    "agent_trace": trace,
                }
            ),
            "agent_trace": trace,
        }

    def _should_call_llm(self, state: RiskAnalysisState) -> str:
        return "llm" if state.get("use_llm") else "done"


class ClauseComparisonWorkflow:
    def __init__(self, ai_service: ContractAIService, comparator: ClauseComparator):
        self.ai_service = ai_service
        self.comparator = comparator

    async def run(self, request: ClauseComparisonRequest) -> ClauseComparisonResponse:
        graph = self._build_graph()
        state = await graph.ainvoke({"request": request, "agent_trace": []})
        return state["result"]

    def _build_graph(self):
        try:
            from langgraph.graph import END, START, StateGraph
        except ImportError as exc:
            raise RuntimeError("langgraph is required for comparison workflows") from exc

        graph = StateGraph(ClauseComparisonState)
        graph.add_node("legal_analysis_agent", self._legal_analysis_agent)
        graph.add_node("compliance_agent", self._compliance_agent)
        graph.add_node("negotiation_agent", self._negotiation_agent)
        graph.add_edge(START, "legal_analysis_agent")
        graph.add_edge("legal_analysis_agent", "compliance_agent")
        graph.add_edge("compliance_agent", "negotiation_agent")
        graph.add_edge("negotiation_agent", END)
        return graph.compile()

    async def _legal_analysis_agent(
        self, state: ClauseComparisonState
    ) -> ClauseComparisonState:
        request = state["request"]
        if request.use_llm:
            result = await self.ai_service.compare_clauses(request)
        else:
            result = self.comparator.compare(request)
        return {
            "result": result,
            "agent_trace": [
                *state.get("agent_trace", []),
                AgentTrace(
                    agent_name="Legal Analysis Agent",
                    summary="Compared source and counterparty clause positions.",
                ),
            ],
        }

    async def _compliance_agent(self, state: ClauseComparisonState) -> ClauseComparisonState:
        result = state["result"]
        notes = list(result.compliance_notes)
        if not notes and result.risk_delta.value in {"high", "critical"}:
            notes.append("High-risk deviations should receive legal approval before signature.")
        return {
            "result": result.model_copy(update={"compliance_notes": notes}),
            "agent_trace": [
                *state.get("agent_trace", []),
                AgentTrace(
                    agent_name="Compliance Agent",
                    summary=f"Added {len(notes)} compliance note(s).",
                ),
            ],
        }

    async def _negotiation_agent(self, state: ClauseComparisonState) -> ClauseComparisonState:
        result = state["result"]
        strategy = list(result.negotiation_strategy)
        if not strategy:
            strategy = [
                "Open with objective risk allocation language.",
                (
                    "Escalate only material deviations that change liability, payment, "
                    "data, or termination risk."
                ),
            ]
        trace = [
            *state.get("agent_trace", []),
            AgentTrace(
                agent_name="Negotiation Agent",
                summary=f"Generated {len(strategy)} negotiation strategy point(s).",
            ),
        ]
        return {
            "result": result.model_copy(
                update={"negotiation_strategy": strategy, "agent_trace": trace}
            ),
            "agent_trace": trace,
        }


class ContractQuestionWorkflow:
    def __init__(
        self,
        store: ContractStore,
        vector_repository: ContractVectorRepository,
        ai_service: ContractAIService,
    ):
        self.store = store
        self.vector_repository = vector_repository
        self.ai_service = ai_service

    async def run(self, contract_id: str, request: AskContractRequest) -> AskContractResponse:
        graph = self._build_graph()
        state = await graph.ainvoke(
            {"contract_id": contract_id, "request": request, "agent_trace": []}
        )
        return state["result"]

    def _build_graph(self):
        try:
            from langgraph.graph import END, START, StateGraph
        except ImportError as exc:
            raise RuntimeError("langgraph is required for Q&A workflows") from exc

        graph = StateGraph(QuestionAnswerState)
        graph.add_node("retriever_agent", self._retriever_agent)
        graph.add_node("qa_agent", self._qa_agent)
        graph.add_edge(START, "retriever_agent")
        graph.add_edge("retriever_agent", "qa_agent")
        graph.add_edge("qa_agent", END)
        return graph.compile()

    async def _retriever_agent(self, state: QuestionAnswerState) -> QuestionAnswerState:
        contract_id = state["contract_id"]
        request = state["request"]
        self.store.get_contract(contract_id)
        clauses = {clause.id: clause for clause in self.store.get_clauses(contract_id)}
        results = self.vector_repository.search(
            contract_id,
            request.question,
            request.top_k,
            metadata_filters=request.metadata_filters,
        )
        sources = [
            result.to_source_snippet(clauses.get(result.clause_id))
            for result in results
            if result.clause_id in clauses
        ]
        if not sources:
            raise NotFoundError("No relevant clauses were found for that question.")
        return {
            "sources": sources,
            "agent_trace": [
                *state.get("agent_trace", []),
                AgentTrace(
                    agent_name="Retriever Agent",
                    summary=f"Retrieved {len(sources)} relevant clause source(s).",
                    details={"metadata_filters": request.metadata_filters},
                ),
            ],
        }

    async def _qa_agent(self, state: QuestionAnswerState) -> QuestionAnswerState:
        request = state["request"]
        contract_id = state["contract_id"]
        sources = state["sources"]
        if request.use_llm:
            result = await self.ai_service.answer_question(
                contract_id,
                request.question,
                sources,
                llm_provider=request.llm_provider,
                llm_model=request.llm_model,
            )
        else:
            joined_sources = "\n\n".join(
                f"{source.title}: {source.text}" for source in sources[:3]
            )
            result = AskContractResponse(
                contract_id=contract_id,
                question=request.question,
                answer=f"Relevant contract excerpts:\n\n{joined_sources}",
                confidence=0.55,
                sources=sources,
            )
        trace = [
            *state.get("agent_trace", []),
            AgentTrace(
                agent_name="Q&A Agent",
                summary="Generated a contract-grounded answer.",
            ),
        ]
        return {
            "result": result.model_copy(update={"agent_trace": trace}),
            "agent_trace": trace,
        }
