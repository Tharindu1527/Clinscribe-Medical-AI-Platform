"""Live tests call real free-tier providers through the gateway. Run with `just test-live`."""

from collections.abc import Iterator

import httpx
import pytest

from config.settings import Settings
from llmops.gateway.client import GatewayClient
from scripts import gateway_keys


@pytest.fixture(scope="session")
def gateway() -> Iterator[GatewayClient]:
    settings = Settings()
    try:
        httpx.get(f"{settings.gateway_url}/health/liveliness", timeout=5).raise_for_status()
    except httpx.HTTPError:
        pytest.fail("gateway is not running (just up)")
    if not settings.gemini_api_key.get_secret_value():
        pytest.fail("GEMINI_API_KEY is empty in .env")
    assert gateway_keys.main() == 0
    client = GatewayClient(settings.gateway_url, settings.litellm_app_key)
    yield client
    client.close()
