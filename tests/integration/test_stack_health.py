"""PROGRESS task 3 gate: every core + fhir service is up and healthy."""

import os
import subprocess

import httpx
import pytest

from config.settings import Settings

EXPECTED = {"postgres", "otel-collector", "litellm", "deid", "api", "hapi-fhir"}
HTTP_CHECKS = {
    "api": "http://127.0.0.1:8000/health",
    "deid": "http://127.0.0.1:8001/health",
    "litellm": "http://127.0.0.1:4000/health/liveliness",
    "otel-collector": "http://127.0.0.1:13133/",
    "hapi-fhir": "http://127.0.0.1:8080/fhir/metadata",
}


def test_all_expected_services_running_and_healthy(stack: list[dict[str, str]]) -> None:
    by_name = {s["Service"]: s for s in stack}
    assert by_name.keys() >= EXPECTED, f"missing: {EXPECTED - by_name.keys()}"
    for name in EXPECTED:
        assert by_name[name]["State"] == "running", name
        # Services without an in-container healthcheck report an empty Health
        assert by_name[name].get("Health", "") in ("", "healthy"), name


@pytest.mark.parametrize("service", sorted(HTTP_CHECKS))
def test_http_endpoint_answers(stack: list[dict[str, str]], service: str) -> None:
    response = httpx.get(HTTP_CHECKS[service], timeout=30)
    assert response.status_code == 200, response.text[:200]


def test_fhir_server_is_r4(stack: list[dict[str, str]]) -> None:
    metadata = httpx.get(HTTP_CHECKS["hapi-fhir"], timeout=30).json()
    assert metadata["resourceType"] == "CapabilityStatement"
    assert metadata["fhirVersion"] == "4.0.1"


def test_postgres_has_one_database_per_service(stack: list[dict[str, str]]) -> None:
    user = Settings().postgres_user
    out = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            user,
            "-d",
            "clinscribe",
            "-Atc",
            "SELECT datname || ':' || pg_get_userbyid(datdba) FROM pg_database",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert {"clinscribe:" + user, "litellm:litellm", "hapi:hapi"} <= set(out)


def _connect_as_app(db: str) -> subprocess.CompletedProcess[str]:
    # `-e PGPASSWORD` with no value passes the variable through from this process's environment,
    # so the password never appears on a command line.
    password = Settings().app_db_password.get_secret_value()
    return subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "-e",
            "PGPASSWORD",
            "postgres",
            "psql",
            "-h",
            "localhost",
            "-U",
            "app",
            "-d",
            db,
            "-Atc",
            "SELECT 1",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PGPASSWORD": password},
    )


def test_app_login_reaches_clinscribe_only(stack: list[dict[str, str]]) -> None:
    allowed = _connect_as_app("clinscribe")
    assert allowed.returncode == 0, allowed.stderr  # positive control: password and login work
    for db in ("litellm", "hapi"):
        denied = _connect_as_app(db)
        assert denied.returncode != 0, f"app login could connect to {db}"
        assert "permission denied" in denied.stderr
