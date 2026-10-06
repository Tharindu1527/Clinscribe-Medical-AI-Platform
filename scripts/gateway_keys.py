"""Register the gateway's virtual keys with budgets and rate limits (task 5).

- clinscribe-app: the application; every alias, 30 rpm.
- clinscribe-batch: offline jobs (Phase 2 contextual prefixes); only the local Ollama alias, so a
  batch run can never spend cloud free-tier quota, even through failover.

Usage: uv run python -m scripts.gateway_keys
Idempotent: creates the key on first run and updates its limits afterwards. Never prints keys.
"""

import sys

import httpx

from config.settings import Settings

ALIASES = [
    "clinscribe-default",
    "clinscribe-fallback-groq",
    "clinscribe-fallback-openrouter",
    "clinscribe-fallback-local",
]
LIMITS = {
    "key_alias": "clinscribe-app",
    "models": ALIASES,
    "max_budget": 1.0,  # USD per budget period; free tiers should stay near 0
    "budget_duration": "30d",
    "rpm_limit": 30,
}


BATCH_LIMITS = {
    "key_alias": "clinscribe-batch",
    "models": ["clinscribe-fallback-local"],
    "max_budget": 0.1,  # the local model costs nothing; a cloud charge here would be a bug
    "budget_duration": "30d",
    "rpm_limit": 240,
}


def register(client: httpx.Client, key: str, limits: dict[str, object]) -> str | None:
    """Create or update one key; returns an error message or None."""
    exists = client.get("/key/info", params={"key": key}).status_code == 200
    route = "/key/update" if exists else "/key/generate"
    response = client.post(route, json={"key": key, **limits})
    if response.status_code >= 400:
        return f"{limits['key_alias']}: HTTP {response.status_code} {response.text[:300]}"
    verb = "updated" if exists else "created"
    print(
        f"{limits['key_alias']} key {verb}: {limits['rpm_limit']} rpm, "
        f"${limits['max_budget']}/{limits['budget_duration']}, models {', '.join(limits['models'])}"  # type: ignore[arg-type]
    )
    return None


def main() -> int:
    settings = Settings()
    master = settings.litellm_master_key.get_secret_value()
    keys = [(settings.litellm_app_key.get_secret_value(), LIMITS)]
    if settings.litellm_batch_key.get_secret_value():
        keys.append((settings.litellm_batch_key.get_secret_value(), BATCH_LIMITS))
    with httpx.Client(
        base_url=settings.gateway_url, headers={"Authorization": f"Bearer {master}"}, timeout=60
    ) as client:
        errors = [e for key, limits in keys if (e := register(client, key, limits))]
    for error in errors:
        print(f"gateway key setup failed: {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
