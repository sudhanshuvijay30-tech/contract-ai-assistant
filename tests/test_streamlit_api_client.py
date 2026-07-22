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

