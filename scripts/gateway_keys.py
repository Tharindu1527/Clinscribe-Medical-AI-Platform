"""Register the app's virtual key on the LiteLLM proxy with a budget and rate limit (task 5).

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


def main() -> int:
    settings = Settings()
    app_key = settings.litellm_app_key.get_secret_value()
    master = settings.litellm_master_key.get_secret_value()
    with httpx.Client(
        base_url=settings.gateway_url, headers={"Authorization": f"Bearer {master}"}, timeout=60
    ) as client:
        exists = client.get("/key/info", params={"key": app_key}).status_code == 200
        if exists:
            response = client.post("/key/update", json={"key": app_key, **LIMITS})
        else:
            response = client.post("/key/generate", json={"key": app_key, **LIMITS})
        if response.status_code >= 400:
            print(f"gateway key setup failed: HTTP {response.status_code} {response.text[:300]}")
            return 1
    action = "updated" if exists else "created"
    print(
        f"app key {action}: alias clinscribe-app, {LIMITS['rpm_limit']} rpm, "
        f"${LIMITS['max_budget']}/{LIMITS['budget_duration']}, models {', '.join(ALIASES)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
