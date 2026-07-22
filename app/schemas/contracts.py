from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ClauseType(StrEnum):
    CONFIDENTIALITY = "confidentiality"
    INDEMNITY = "indemnity"
    LIMITATION_OF_LIABILITY = "limitation_of_liability"
    TERMINATION = "termination"
    PAYMENT = "payment"
    DATA_PROTECTION = "data_protection"
    INTELLECTUAL_PROPERTY = "intellectual_property"
    WARRANTIES = "warranties"
    GOVERNING_LAW = "governing_law"
    DISPUTE_RESOLUTION = "dispute_resolution"
    ASSIGNMENT = "assignment"
    AUDIT = "audit"
    FORCE_MAJEURE = "force_majeure"
    NON_COMPETE = "non_compete"
    OTHER = "other"


class ContractStatus(StrEnum):
    INGESTED = "ingested"
    ANALYZED = "analyzed"
    FAILED = "failed"


class HealthResponse(BaseModel):
    status: str
    app_name: str
    version: str
    environment: str
    model: str
    llm_provider: str
    embedding_provider: str


class ExtractedPage(BaseModel):
    page_number: int = Field(ge=1)
    text: str


class ContractRecord(BaseModel):
    id: str
    filename: str
    content_type: str
    sha256: str
    size_bytes: int = Field(ge=0)
    page_count: int = Field(ge=0)
    created_at: datetime
    status: ContractStatus = ContractStatus.INGESTED


class Clause(BaseModel):
    id: str
    contract_id: str
    type: ClauseType = ClauseType.OTHER
    title: str
    text: str
    page_start: int | None = None
    page_end: int | None = None
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)
    confidence: float = Field(default=0.75, ge=0, le=1)
    source: str = "heuristic"


class ContractUploadResponse(BaseModel):
    contract: ContractRecord
    clauses_count: int
    vector_collection: str


class ClauseListResponse(BaseModel):
    contract_id: str
    clauses: list[Clause]


class RiskAnalysisRequest(BaseModel):
    use_llm: bool = True


class RiskItem(BaseModel):
    id: str = Field(default_factory=lambda: f"risk-{uuid4().hex}")
    clause_id: str | None = None
    clause_type: ClauseType = ClauseType.OTHER
    title: str
    level: RiskLevel
    summary: str
    rationale: str
    recommendation: str
    evidence: list[str] = Field(default_factory=list)


class RiskAnalysisResponse(BaseModel):
    contract_id: str
    overall_risk_level: RiskLevel
    executive_summary: str
    risks: list[RiskItem]


class ClauseInput(BaseModel):
    title: str | None = None
    type: ClauseType = ClauseType.OTHER
    text: str = Field(min_length=10)


class ClauseComparisonRequest(BaseModel):
    source_clause: ClauseInput
    counterparty_clause: ClauseInput
    preferred_position: str | None = None
    use_llm: bool = True


class ClauseComparisonResponse(BaseModel):
    alignment_score: float = Field(ge=0, le=1)
    risk_delta: RiskLevel
    summary: str
    missing_terms: list[str] = Field(default_factory=list)
    material_deviations: list[str] = Field(default_factory=list)
    negotiation_points: list[str] = Field(default_factory=list)
    recommended_clause: str | None = None


class AskContractRequest(BaseModel):
    question: str = Field(min_length=3)
    top_k: int = Field(default=5, ge=1, le=12)
    use_llm: bool = True


class SourceSnippet(BaseModel):
    clause_id: str
    title: str
    clause_type: ClauseType
    text: str
    score: float | None = None
    page_start: int | None = None
    page_end: int | None = None


class AskContractResponse(BaseModel):
    contract_id: str
    question: str
    answer: str
    confidence: float = Field(ge=0, le=1)
    sources: list[SourceSnippet]


class VectorSearchResult(BaseModel):
    clause_id: str
    text: str
    score: float | None = None
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    def to_source_snippet(self, clause: object | None) -> SourceSnippet:
        if clause is None:
            return SourceSnippet(
                clause_id=self.clause_id,
                title=str(self.metadata.get("title", "Unknown clause")),
                clause_type=self.metadata.get("type", ClauseType.OTHER),
                text=self.text,
                score=self.score,
            )
        return SourceSnippet(
            clause_id=str(clause.id),
            title=str(clause.title),
            clause_type=getattr(clause, "type", ClauseType.OTHER),
            text=self.text or str(clause.text),
            score=self.score,
            page_start=getattr(clause, "page_start", None),
            page_end=getattr(clause, "page_end", None),
        )
