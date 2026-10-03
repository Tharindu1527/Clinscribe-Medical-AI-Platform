import importlib

import pytest

PACKAGES = [
    "agents",
    "apps.api",
    "config.settings",
    "evals",
    "llmops.gateway",
    "llmops.telemetry",
    "mcp_servers",
    "privacy.deid",
    "retrieval",
    "scripts",
    "voice",
]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_imports(name: str) -> None:
    assert importlib.import_module(name) is not None
