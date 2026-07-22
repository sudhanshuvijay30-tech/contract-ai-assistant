import pytest

from app.core.config import Settings
from app.schemas.contracts import ClauseComparisonRequest, ClauseInput, RiskLevel
from app.services.ai import ContractAIService


@pytest.mark.asyncio
async def test_ai_service_routes_structured_calls_to_ollama_by_default(tmp_path, monkeypatch):
    settings = Settings(
        chroma_persist_directory=tmp_path / "chroma",
        llm_provider="ollama",
        ollama_chat_model="llama3.1:8b",
    )
    service = ContractAIService(settings)

    async def fake_ollama(schema, messages):
        assert schema.__name__ == "ClauseComparisonResponse"
        assert messages
        return schema(
            alignment_score=0.82,
            risk_delta=RiskLevel.LOW,
            summary="The clauses are aligned.",
            missing_terms=[],
            material_deviations=[],
            negotiation_points=["Keep the current position."],
        )

    monkeypatch.setattr(service, "_invoke_ollama_structured", fake_ollama)

    response = await service.compare_clauses(
        ClauseComparisonRequest(
            source_clause=ClauseInput(
                text="Customer may terminate after a thirty day cure period."
            ),
            counterparty_clause=ClauseInput(
                text="Customer may terminate after thirty days notice."
            ),
            use_llm=True,
        )
    )

    assert response.alignment_score == 0.82
    assert response.risk_delta == RiskLevel.LOW
