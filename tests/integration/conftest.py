"""Integration tests need the Docker stack (`just up`).

When the stack is down they are skipped, so `just test` still works on a laptop without Docker.
Set CLINSCRIBE_REQUIRE_STACK=1 (as `just gate` does) to make a missing stack fail instead.
"""

import json
import os
import shutil
import subprocess

import pytest

ROOT_ARGS = ["docker", "compose", "--profile", "*"]


def compose_services() -> list[dict[str, str]]:
    """Running compose services (Service, State, Health); empty if Docker is unavailable."""
    if shutil.which("docker") is None:
        return []
    proc = subprocess.run(
        [*ROOT_ARGS, "ps", "--format", "json"], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        return []
    out = proc.stdout.strip()
    if not out:
        return []
    # Compose prints either one JSON array or one JSON object per line, depending on version
    if out.startswith("["):
        return list(json.loads(out))
    return [json.loads(line) for line in out.splitlines() if line.strip()]


@pytest.fixture(scope="session")
def stack() -> list[dict[str, str]]:
    services = compose_services()
    if not services:
        if os.environ.get("CLINSCRIBE_REQUIRE_STACK") == "1":
            pytest.fail("Docker stack is not running (just up)")
        pytest.skip("Docker stack is not running (just up)")
    return services
