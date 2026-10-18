"""PROGRESS task 5 gate (Phase 1 gate a): the gateway answers when the primary provider fails."""

import contextlib
import os
import subprocess
import time

import httpx
import pytest

from config.settings import Settings
from llmops.gateway.client import ChatMessage, GatewayClient
from privacy.deid.types import issue
from scripts.chaos import set_fault

PROMPT = [
    ChatMessage(
        "user",
        issue("Reply with the single word: ready", source="synthetic-test-fixture"),
    )
]


def _spend_log_entry(response_id: str, timeout_s: float = 120) -> str | None:
    """'model|model_group' that LiteLLM recorded for a response (spend logs are batched)."""
    password = Settings().litellm_db_password.get_secret_value()
    # The id travels as a psql variable (quoted by psql), not pasted into the SQL text
    query = (
        "SELECT model || '|' || model_group FROM \"LiteLLM_SpendLogs\" "
        "WHERE request_id = :'response_id';\n"
    )
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        out = subprocess.run(
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
                "litellm",
                "-d",
                "litellm",
                "-At",
                "-v",
                f"response_id={response_id}",
            ],
            input=query,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "PGPASSWORD": password},
        ).stdout.strip()
        if out:
            return out
        time.sleep(5)
    return None


# Gemini 3.x Flash and gpt-oss reason before answering; reasoning tokens count against
# max_tokens, so a tiny limit returns empty text.
MAX_TOKENS = 256


def test_primary_answers_normally(gateway: GatewayClient) -> None:
    result = gateway.complete("clinscribe-default", PROMPT, max_tokens=MAX_TOKENS)
    assert result.text.strip()
    # The response's `model` field may echo the alias; the spend log records the real deployment
    assert result.response_id
    recorded = _spend_log_entry(result.response_id)
    assert recorded is not None, "call not found in LiteLLM spend logs"
    model, group = recorded.split("|")
    assert group == "clinscribe-default", recorded  # served by the primary, not a fallback
    assert model.startswith("gemini/"), recorded


def test_turn_succeeds_through_failover_when_primary_is_down(gateway: GatewayClient) -> None:
    set_fault("primary-down", on=True)
    try:
        result = gateway.complete("clinscribe-default", PROMPT, max_tokens=MAX_TOKENS)
    finally:
        set_fault("primary-down", on=False)

    assert result.text.strip()
    assert "gpt-oss" in result.model, f"expected the Groq fallback, got {result.model}"
    assert result.response_id
    recorded = _spend_log_entry(result.response_id)
    assert recorded is not None, "failover call not found in LiteLLM spend logs"
    assert recorded == "groq/openai/gpt-oss-20b|clinscribe-fallback-groq", recorded


def test_local_model_answers(gateway: GatewayClient) -> None:
    """Last step of the chain. Skipped until Ollama has the model (full check is Phase 5)."""
    base = "http://127.0.0.1:11434"
    try:
        tags = httpx.get(f"{base}/api/tags", timeout=5).json().get("models", [])
    except httpx.HTTPError:
        pytest.skip("Ollama is not running")
    if not any(m["name"].startswith("llama3.2:3b") for m in tags):
        pytest.skip("llama3.2:3b not pulled yet")
    result = gateway.complete("clinscribe-fallback-local", PROMPT, max_tokens=MAX_TOKENS)
    assert result.text.strip()


def test_turn_succeeds_with_every_cloud_provider_down() -> None:
    """Phase 5 exit gate (SPEC section 12): all cloud providers disabled, the turn completes on the
    local Ollama model, and the spend log records it. The model is unloaded first: a cold load
    (~75 s) is the realistic case, and it outlasted the gateway's 60 s timeout until 2026-10-19
    (the warm model left by the previous test hid that)."""
    with contextlib.suppress(httpx.HTTPError):
        httpx.post(
            "http://127.0.0.1:11434/api/generate",
            json={"model": "llama3.2:3b", "keep_alive": 0},
            timeout=30,
        )
    settings = Settings()
    # 300 s, as the API's client: three dead clouds, then a cold local load
    gateway = GatewayClient(settings.gateway_url, settings.litellm_app_key, timeout=300)
    set_fault("cloud-down", on=True)
    try:
        result = gateway.complete("clinscribe-default", PROMPT, max_tokens=MAX_TOKENS)
    finally:
        set_fault("cloud-down", on=False)
        gateway.close()

    assert result.text.strip()
    assert result.response_id
    recorded = _spend_log_entry(result.response_id)
    assert recorded is not None, "local-model call not found in LiteLLM spend logs"
    assert recorded.endswith("|clinscribe-fallback-local"), recorded
