import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


def test_health_endpoint():
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_metrics_requires_bearer_token_when_auth_enabled(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("API_AUTH_TOKEN", "secret-token")
    get_settings.cache_clear()
    client = TestClient(create_app())

    missing = client.get("/metrics")
    allowed = client.get("/metrics", headers={"Authorization": "Bearer secret-token"})

    assert missing.status_code == 401
    assert allowed.status_code == 200
    assert "contract_ai_requests_total" in allowed.text
    get_settings.cache_clear()


def test_production_auth_requires_token(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("API_AUTH_TOKEN", "")
    get_settings.cache_clear()

    with pytest.raises(RuntimeError):
        create_app()

    get_settings.cache_clear()
