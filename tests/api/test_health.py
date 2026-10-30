"""Contrato mínimo del adaptador HTTP local."""

from apps.api.app.main import create_app
from fastapi.testclient import TestClient


def test_health_is_available_without_domain_or_storage_access() -> None:
    response = TestClient(create_app()).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "universal-business-api"}
