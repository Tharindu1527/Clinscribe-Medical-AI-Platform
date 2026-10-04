import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.main import app as api_app
from privacy.deid.app import app as deid_app


@pytest.mark.parametrize(("app", "service"), [(api_app, "api"), (deid_app, "deid")])
def test_health(app: FastAPI, service: str) -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": service}
