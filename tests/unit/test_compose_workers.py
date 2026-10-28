"""A service with several uvicorn workers must not have them killed for being slow (postmortem
0005): uvicorn's supervisor kills a worker that misses a 5 s ping, mid-request."""

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit
COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"
MIN_HEALTHCHECK_S = 30


def _uvicorn_commands() -> dict[str, list[str]]:
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    return {
        name: [str(part) for part in service["command"]]
        for name, service in services.items()
        if isinstance(service.get("command"), list) and service["command"][:1] == ["uvicorn"]
    }


def test_multi_worker_services_give_a_busy_worker_time_to_answer() -> None:
    checked = 0
    for name, command in _uvicorn_commands().items():
        if "--workers" not in command or int(command[command.index("--workers") + 1]) < 2:
            continue
        checked += 1
        assert "--timeout-worker-healthcheck" in command, f"{name}: uvicorn's default is 5 s"
        timeout = int(command[command.index("--timeout-worker-healthcheck") + 1])
        assert timeout >= MIN_HEALTHCHECK_S, name
    assert checked >= 1  # the de-ID service runs three workers
