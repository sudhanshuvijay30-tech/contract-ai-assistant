from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class APIClientError(Exception):
    def __init__(self, message: str, status_code: int | None = None, code: str | None = None):
        self.message = message
        self.status_code = status_code
        self.code = code
        super().__init__(message)


@dataclass
class ContractAPIClient:
    base_url: str = "http://localhost:8000"
    timeout_seconds: float = 90.0
    client: httpx.Client | None = None

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def upload_contract(
        self,
        filename: str,
        content: bytes,
        content_type: str,
        use_ai: bool,
        llm_provider: str | None = None,
        llm_model: str | None = None,
    ) -> dict[str, Any]:
        params = {"use_ai": str(use_ai).lower()}
        if llm_provider:
            params["llm_provider"] = llm_provider
        if llm_model:
            params["llm_model"] = llm_model
        return self._request(
            "POST",
            "/contracts/upload",
            params=params,
            files={"file": (filename, content, content_type)},
        )

    def list_clauses(self, contract_id: str) -> dict[str, Any]:
        return self._request("GET", f"/contracts/{contract_id}/clauses")

    def analyze_risks(
        self,
        contract_id: str,
        use_llm: bool,
        llm_provider: str | None = None,
        llm_model: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/contracts/{contract_id}/risks",
            json={
                "use_llm": use_llm,
                "llm_provider": llm_provider,
                "llm_model": llm_model,
            },
        )

    def compare_clauses(
        self,
        source_clause: dict[str, Any],
        counterparty_clause: dict[str, Any],
        preferred_position: str | None,
        use_llm: bool,
        llm_provider: str | None = None,
        llm_model: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/compare",
            json={
                "source_clause": source_clause,
                "counterparty_clause": counterparty_clause,
                "preferred_position": preferred_position or None,
                "use_llm": use_llm,
                "llm_provider": llm_provider,
                "llm_model": llm_model,
            },
        )

    def ask_contract(
        self,
        contract_id: str,
        question: str,
        top_k: int,
        use_llm: bool,
        llm_provider: str | None = None,
        llm_model: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/contracts/{contract_id}/ask",
            json={
                "question": question,
                "top_k": top_k,
                "use_llm": use_llm,
                "llm_provider": llm_provider,
                "llm_model": llm_model,
            },
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        client = self.client or httpx.Client(
            base_url=self.base_url.rstrip("/"),
            timeout=self.timeout_seconds,
        )
        close_client = self.client is None
        try:
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {"data": payload}
        except httpx.HTTPStatusError as exc:
            raise self._api_error(exc.response) from exc
        except httpx.RequestError as exc:
            raise APIClientError(
                f"Unable to reach the FastAPI service at {self.base_url}.",
                code="api_unreachable",
            ) from exc
        finally:
            if close_client:
                client.close()

    def _api_error(self, response: httpx.Response) -> APIClientError:
        message = response.text or "The API returned an error."
        code = None
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if isinstance(payload, dict):
            detail = payload.get("detail")
            code = payload.get("code")
            if isinstance(detail, str):
                message = detail
        return APIClientError(message=message, status_code=response.status_code, code=code)


def missing_openai_help(error: APIClientError) -> str | None:
    if error.code == "ai_provider_not_configured" and "Ollama" in error.message:
        return error.message
    missing_key_error = (
        error.code in {"ai_provider_not_configured", "vector_store_error"}
        and "OPENAI_API_KEY" in error.message
    )
    if missing_key_error:
        return (
            "OPENAI_API_KEY is missing or empty. Add it to .env, then restart both FastAPI "
            "and Streamlit."
        )
    return None
