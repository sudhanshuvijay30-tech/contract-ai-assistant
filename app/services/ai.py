import hashlib
import json
from typing import TypeVar

import httpx
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.errors import AIProviderNotConfiguredError
from app.schemas.contracts import (
    AIProvider,
    AskContractResponse,
    Clause,
    ClauseComparisonRequest,
    ClauseComparisonResponse,
    ClauseType,
    RiskAnalysisResponse,
    RiskItem,
    RiskLevel,
    SourceSnippet,
)

StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class ClauseDraft(BaseModel):
    title: str
    type: ClauseType = ClauseType.OTHER
    text: str
    page_start: int | None = None
    page_end: int | None = None
    confidence: float = Field(default=0.85, ge=0, le=1)


class ClauseExtractionResult(BaseModel):
    clauses: list[ClauseDraft]


class RiskFindingDraft(BaseModel):
    clause_id: str | None = None
    clause_type: ClauseType = ClauseType.OTHER
    title: str
    level: RiskLevel
    summary: str
    rationale: str
    recommendation: str
    evidence: list[str] = Field(default_factory=list)


class RiskAnalysisDraft(BaseModel):
    overall_risk_level: RiskLevel
    executive_summary: str
    risks: list[RiskFindingDraft]


class AnswerDraft(BaseModel):
    answer: str
    confidence: float = Field(ge=0, le=1)
    cited_clause_ids: list[str] = Field(default_factory=list)


class ContractAIService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def extract_clauses(
        self,
        contract_id: str,
        contract_text: str,
        preliminary_clauses: list[Clause],
        llm_provider: AIProvider | None = None,
        llm_model: str | None = None,
    ) -> list[Clause]:
        payload = {
            "contract_text": self._truncate(contract_text),
            "preliminary_clauses": [
                clause.model_dump(mode="json") for clause in preliminary_clauses
            ],
        }
        result = await self._invoke_structured(
            ClauseExtractionResult,
            [
                (
                    "system",
                    "You are a senior commercial contracts lawyer. Extract complete "
                    "contract clauses "
                    "as structured data. Preserve exact clause text where possible.",
                ),
                (
                    "human",
                    "Extract the clauses from this contract. Use the preliminary clauses as hints, "
                    "but correct titles, boundaries, and clause types when needed.\n\n"
                    f"{json.dumps(payload, ensure_ascii=False)}",
                ),
            ],
            llm_provider=llm_provider,
            llm_model=llm_model,
        )
        source_model = self._resolve_chat_model(llm_provider, llm_model)
        clauses = [
            self._draft_to_clause(contract_id, index, draft, contract_text, source_model)
            for index, draft in enumerate(result.clauses, start=1)
            if draft.text.strip()
        ]
        return clauses or preliminary_clauses

    async def analyze_risks(
        self,
        contract_id: str,
        clauses: list[Clause],
        contract_text: str,
        llm_provider: AIProvider | None = None,
        llm_model: str | None = None,
    ) -> RiskAnalysisResponse:
        payload = {
            "contract_id": contract_id,
            "contract_excerpt": self._truncate(contract_text),
            "clauses": [
                {
                    "id": clause.id,
                    "title": clause.title,
                    "type": clause.type,
                    "text": self._truncate(clause.text, limit=2_000),
                }
                for clause in clauses
            ],
        }
        result = await self._invoke_structured(
            RiskAnalysisDraft,
            [
                (
                    "system",
                    "You are a contract risk analyst. Identify legal and commercial risks, explain "
                    "why they matter, and recommend negotiation changes. This is decision support, "
                    "not legal advice.",
                ),
                (
                    "human",
                    "Analyze the contract clauses for risk. Return concise, prioritized findings "
                    "with evidence snippets tied to clause IDs.\n\n"
                    f"{json.dumps(payload, ensure_ascii=False)}",
                ),
            ],
            llm_provider=llm_provider,
            llm_model=llm_model,
        )
        return RiskAnalysisResponse(
            contract_id=contract_id,
            overall_risk_level=result.overall_risk_level,
            executive_summary=result.executive_summary,
            risks=[
                RiskItem(
                    clause_id=risk.clause_id,
                    clause_type=risk.clause_type,
                    title=risk.title,
                    level=risk.level,
                    summary=risk.summary,
                    rationale=risk.rationale,
                    recommendation=risk.recommendation,
                    evidence=risk.evidence,
                )
                for risk in result.risks
            ],
        )

    async def compare_clauses(
        self,
        request: ClauseComparisonRequest,
    ) -> ClauseComparisonResponse:
        return await self._invoke_structured(
            ClauseComparisonResponse,
            [
                (
                    "system",
                    "You compare contract clauses against a preferred position and "
                    "identify material "
                    "legal, operational, and commercial deviations.",
                ),
                (
                    "human",
                    "Compare these clauses. Score alignment from 0 to 1. Identify missing terms, "
                    "material deviations, negotiation points, and an optional "
                    "recommended clause.\n\n"
                    f"{request.model_dump_json()}",
                ),
            ],
            llm_provider=request.llm_provider,
            llm_model=request.llm_model,
        )

    async def answer_question(
        self,
        contract_id: str,
        question: str,
        sources: list[SourceSnippet],
        llm_provider: AIProvider | None = None,
        llm_model: str | None = None,
    ) -> AskContractResponse:
        sources_json = json.dumps(
            [source.model_dump(mode="json") for source in sources],
            ensure_ascii=False,
        )
        result = await self._invoke_structured(
            AnswerDraft,
            [
                (
                    "system",
                    "You answer questions about a contract using only the supplied "
                    "clause snippets. "
                    "If the answer is not supported by the snippets, say that the "
                    "contract excerpts "
                    "do not contain enough information.",
                ),
                (
                    "human",
                    "Question:\n"
                    f"{question}\n\n"
                    "Clause snippets:\n"
                    f"{sources_json}",
                ),
            ],
            llm_provider=llm_provider,
            llm_model=llm_model,
        )
        cited = set(result.cited_clause_ids)
        selected_sources = [source for source in sources if not cited or source.clause_id in cited]
        return AskContractResponse(
            contract_id=contract_id,
            question=question,
            answer=result.answer,
            confidence=result.confidence,
            sources=selected_sources,
        )

    async def _invoke_structured(
        self,
        schema: type[StructuredModel],
        messages: list[tuple[str, str]],
        llm_provider: AIProvider | None = None,
        llm_model: str | None = None,
    ) -> StructuredModel:
        provider = self._resolve_llm_provider(llm_provider)
        model = self._resolve_chat_model(provider, llm_model)
        if provider == AIProvider.OLLAMA:
            return await self._invoke_ollama_structured(schema, messages, model)
        return await self._invoke_openai_structured(schema, messages, model)

    async def _invoke_openai_structured(
        self,
        schema: type[StructuredModel],
        messages: list[tuple[str, str]],
        model_name: str,
    ) -> StructuredModel:
        api_key = self.settings.openai_api_key_value
        if not api_key:
            raise AIProviderNotConfiguredError("OPENAI_API_KEY is required for GPT-5 analysis.")

        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError("langchain-openai is required for GPT-5 analysis") from exc

        model = ChatOpenAI(
            model=model_name,
            api_key=api_key,
            timeout=self.settings.llm_timeout_seconds,
            max_retries=self.settings.llm_max_retries,
        ).with_structured_output(schema)
        try:
            result = await model.ainvoke(messages)
        except Exception as exc:
            raise AIProviderNotConfiguredError(self._format_openai_error(exc)) from exc
        if isinstance(result, schema):
            return result
        return schema.model_validate(result)

    async def _invoke_ollama_structured(
        self,
        schema: type[StructuredModel],
        messages: list[tuple[str, str]],
        model_name: str,
    ) -> StructuredModel:
        prompt_messages = self._ollama_messages(schema, messages)
        payload = {
            "model": model_name,
            "messages": prompt_messages,
            "stream": False,
            "format": schema.model_json_schema(),
            "options": {"temperature": 0},
        }

        try:
            async with httpx.AsyncClient(
                base_url=self.settings.ollama_base_url.rstrip("/"),
                timeout=self.settings.llm_timeout_seconds,
            ) as client:
                response = await client.post("/api/chat", json=payload)
                response.raise_for_status()
        except httpx.ConnectError as exc:
            raise AIProviderNotConfiguredError(
                "Unable to reach Ollama. Start Ollama, then confirm it is running at "
                f"{self.settings.ollama_base_url}."
            ) from exc
        except httpx.HTTPStatusError as exc:
            message = self._format_ollama_http_error(exc.response, model_name)
            raise AIProviderNotConfiguredError(message) from exc
        except httpx.RequestError as exc:
            raise AIProviderNotConfiguredError(
                f"Ollama request failed: {exc.__class__.__name__}."
            ) from exc

        content = response.json().get("message", {}).get("content", "")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise AIProviderNotConfiguredError(
                "Ollama returned non-JSON output. Try a stronger instruction-following model "
                f"or pull {model_name} again."
            ) from exc

        return schema.model_validate(parsed)

    def _resolve_llm_provider(self, provider: AIProvider | str | None = None) -> AIProvider:
        if provider is None:
            return AIProvider(self.settings.llm_provider)
        return AIProvider(provider)

    def _resolve_chat_model(
        self,
        provider: AIProvider | str | None = None,
        model: str | None = None,
    ) -> str:
        if model and model.strip():
            return model.strip()
        resolved_provider = self._resolve_llm_provider(provider)
        if resolved_provider == AIProvider.OLLAMA:
            return self.settings.ollama_chat_model
        return self.settings.openai_model

    def _ollama_messages(
        self,
        schema: type[StructuredModel],
        messages: list[tuple[str, str]],
    ) -> list[dict[str, str]]:
        formatted: list[dict[str, str]] = []
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        for role, content in messages:
            ollama_role = "user" if role == "human" else role
            formatted.append({"role": ollama_role, "content": content})
        formatted.append(
            {
                "role": "user",
                "content": (
                    "Return only valid JSON that satisfies this JSON Schema. "
                    f"Do not include Markdown.\n\n{schema_json}"
                ),
            }
        )
        return formatted

    def _format_openai_error(self, exc: Exception) -> str:
        message = str(exc)
        lowered = message.lower()
        if any(term in lowered for term in ("insufficient_quota", "quota", "billing", "credit")):
            return (
                "OpenAI rejected the request because the account has no available credits "
                "or quota. Set LLM_PROVIDER=ollama to use your local Ollama model."
            )
        return f"OpenAI request failed: {message}"

    def _format_ollama_http_error(self, response: httpx.Response, model_name: str) -> str:
        body = response.text
        lowered = body.lower()
        if response.status_code == 404 or "not found" in lowered:
            return (
                f"Ollama model '{model_name}' is not available. "
                f"Run: ollama pull {model_name}"
            )
        return f"Ollama request failed with HTTP {response.status_code}: {body}"

    def _draft_to_clause(
        self,
        contract_id: str,
        index: int,
        draft: ClauseDraft,
        contract_text: str,
        source_model: str,
    ) -> Clause:
        text = draft.text.strip()
        start = contract_text.find(text[:120])
        if start < 0:
            start = 0
        end = start + len(text)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]
        return Clause(
            id=f"{contract_id}:clause:{index:04d}:{digest}",
            contract_id=contract_id,
            type=draft.type,
            title=draft.title.strip() or "Untitled clause",
            text=text,
            page_start=draft.page_start,
            page_end=draft.page_end,
            start_char=start,
            end_char=end,
            confidence=draft.confidence,
            source=source_model,
        )

    def _truncate(self, text: str, limit: int | None = None) -> str:
        max_chars = limit or self.settings.max_analysis_chars
        if len(text) <= max_chars:
            return text
        return f"{text[:max_chars]}\n\n[TRUNCATED AFTER {max_chars} CHARACTERS]"
