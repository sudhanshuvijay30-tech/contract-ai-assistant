import httpx
import pytest

from app.ui.api_client import APIClientError, ContractAPIClient, missing_openai_help


def make_client(handler):
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(base_url="http://testserver", transport=transport)
    return ContractAPIClient(base_url="http://testserver", client=http_client)


def test_upload_contract_posts_file_and_use_ai_flag():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/contracts/upload"
        assert request.url.params["use_ai"] == "true"
        assert request.url.params["llm_provider"] == "ollama"
        assert request.url.params["llm_model"] == "llama3.1:8b"
        assert b"contract.pdf" in request.content
        return httpx.Response(
            201,
            json={
                "contract": {"id": "abc123"},
                "clauses_count": 2,
                "vector_collection": "contract_clauses",
            },
        )

    response = make_client(handler).upload_contract(
        filename="contract.pdf",
        content=b"%PDF-1.7 sample",
        content_type="application/pdf",
        use_ai=True,
        llm_provider="ollama",
        llm_model="llama3.1:8b",
    )

    assert response["contract"]["id"] == "abc123"


def test_client_surfaces_api_error_detail_and_code():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={
                "detail": "OPENAI_API_KEY is required for GPT-5 analysis.",
                "code": "ai_provider_not_configured",
            },
        )

    with pytest.raises(APIClientError) as exc_info:
        make_client(handler).analyze_risks("contract-1", use_llm=True)

    assert exc_info.value.status_code == 503
    assert exc_info.value.code == "ai_provider_not_configured"
    assert "OPENAI_API_KEY" in exc_info.value.message
    assert "Add it to .env" in missing_openai_help(exc_info.value)


def test_compare_clauses_sends_selected_ai_provider():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/compare"
        payload = request.read()
        assert b'"llm_provider":"openai"' in payload
        assert b'"llm_model":"gpt-5"' in payload
        return httpx.Response(
            200,
            json={
                "alignment_score": 0.7,
                "risk_delta": "medium",
                "summary": "Some deviations exist.",
                "missing_terms": [],
                "material_deviations": [],
                "negotiation_points": [],
                "recommended_clause": None,
            },
        )

    response = make_client(handler).compare_clauses(
        source_clause={"text": "The preferred clause includes a mutual liability cap."},
        counterparty_clause={"text": "The counterparty clause has no liability cap."},
        preferred_position=None,
        use_llm=True,
        llm_provider="openai",
        llm_model="gpt-5",
    )

    assert response["risk_delta"] == "medium"
