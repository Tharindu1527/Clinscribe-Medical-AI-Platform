"""Fill empty generated secrets in .env without ever printing them.

Usage: uv run python -m scripts.gen_keys
Creates .env from .env.example if it does not exist, and appends keys that were added to
.env.example later. Keys that already have a value are left untouched, so provider keys
you pasted in are never overwritten.
"""

import base64
import os
import secrets
import sys
from collections.abc import Callable
from pathlib import Path

GENERATORS: dict[str, Callable[[], str]] = {
    "LITELLM_MASTER_KEY": lambda: "sk-" + secrets.token_urlsafe(32),
    "LITELLM_SALT_KEY": lambda: secrets.token_urlsafe(32),
    "LITELLM_APP_KEY": lambda: "sk-" + secrets.token_urlsafe(32),
    "LITELLM_BATCH_KEY": lambda: "sk-" + secrets.token_urlsafe(32),
    "LITELLM_LOAD_KEY": lambda: "sk-" + secrets.token_urlsafe(32),
    "POSTGRES_PASSWORD": lambda: secrets.token_urlsafe(24),
    "APP_DB_PASSWORD": lambda: secrets.token_urlsafe(24),
    "LITELLM_DB_PASSWORD": lambda: secrets.token_urlsafe(24),
    "HAPI_DB_PASSWORD": lambda: secrets.token_urlsafe(24),
    # Fernet keys are 32 random bytes, urlsafe-base64 encoded
    "DEID_MAPPING_KEY": lambda: base64.urlsafe_b64encode(os.urandom(32)).decode(),
    "DEID_REIDENTIFY_KEY": lambda: secrets.token_hex(32),
    "AUDIT_CHAIN_KEY": lambda: secrets.token_hex(32),
    "APPROVAL_TOKEN_KEY": lambda: secrets.token_hex(32),
    "AUTH_TOKEN_KEY": lambda: secrets.token_hex(32),
    "LIVEKIT_API_KEY": lambda: "API" + secrets.token_hex(8),
    "LIVEKIT_API_SECRET": lambda: secrets.token_urlsafe(32),
    "QDRANT_API_KEY": lambda: secrets.token_urlsafe(32),
    "NEO4J_PASSWORD": lambda: secrets.token_urlsafe(24),
    "PGVECTOR_PASSWORD": lambda: secrets.token_urlsafe(24),
}


def fill_env(env_path: Path, example_path: Path) -> list[str]:
    """Fill empty generated keys in env_path. Returns the names (never values) that were set."""
    if not env_path.exists():
        env_path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")

    lines = env_path.read_text(encoding="utf-8").splitlines()
    present = {line.partition("=")[0].strip() for line in lines if "=" in line}
    for line in example_path.read_text(encoding="utf-8").splitlines():
        key = line.partition("=")[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key not in present:
            lines.append(line)  # new key from .env.example, with its example default

    filled: list[str] = []
    for i, line in enumerate(lines):
        key, sep, value = line.partition("=")
        key = key.strip()
        if sep and key in GENERATORS and not value.strip():
            lines[i] = f"{key}={GENERATORS[key]()}"
            filled.append(key)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return filled


def main() -> int:
    filled = fill_env(Path(".env"), Path(".env.example"))
    print(
        "Generated: "
        + (", ".join(filled) if filled else "nothing (all generated keys already set)")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
