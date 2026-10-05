"""Chaos switches for incident practice (SPEC section 7).

Usage: uv run python -m scripts.chaos primary-down on|off
primary-down: points the primary provider (Gemini) at an address that refuses connections, then
recreates the gateway container. Turns should still succeed through the fallback chain.
"""

import os
import subprocess
import sys
import time

import httpx

from config.settings import Settings

DEAD_ADDRESS = "http://127.0.0.1:9"  # nothing listens here inside the container
FAULTS = {"primary-down": "GEMINI_API_BASE_OVERRIDE"}


def wait_for_gateway(url: str, timeout_s: float = 180) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{url}/health/liveliness", timeout=5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise TimeoutError("gateway did not become healthy")


def set_fault(fault: str, on: bool) -> None:
    env = dict(os.environ)
    env[FAULTS[fault]] = DEAD_ADDRESS if on else ""
    subprocess.run(
        [
            "docker",
            "compose",
            "--profile",
            "core",
            "up",
            "-d",
            "--force-recreate",
            "--no-deps",
            "litellm",
        ],
        check=True,
        env=env,
    )
    wait_for_gateway(Settings().gateway_url)


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in FAULTS or argv[1] not in ("on", "off"):
        print(f"usage: chaos {{{'|'.join(FAULTS)}}} on|off")
        return 2
    set_fault(argv[0], argv[1] == "on")
    print(f"{argv[0]} is {argv[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
