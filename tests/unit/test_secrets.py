"""Secrets stay in .env (CLAUDE.md): no value of a secret-named key in .env appears in any file git
tracks, and connection strings carry any password intact. Failures name keys and files, never
values. Without a .env (CI's unit job) the tracked-file check is skipped."""

import re
import subprocess
from pathlib import Path

import pytest
from psycopg.conninfo import conninfo_to_dict

from config.db import app_conninfo, owner_conninfo
from config.settings import Settings

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]
SECRET_NAME = re.compile(r"PASSWORD|SECRET|KEY|TOKEN", re.IGNORECASE)


def _env_secrets() -> dict[str, str]:
    env = ROOT / ".env"
    if not env.exists():
        pytest.skip("no .env on this machine")
    secrets = {}
    for line in env.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        named = sep and not key.lstrip().startswith("#") and SECRET_NAME.search(key)
        if named and len(value.strip()) >= 8:  # shorter values match by accident, not by leak
            secrets[key.strip()] = value.strip()
    return secrets


def test_no_secret_from_env_is_in_a_tracked_file() -> None:
    secrets = _env_secrets()
    tracked = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout.split(b"\0")
    found = []
    for name in (n.decode() for n in tracked if n):
        path = ROOT / name
        if not path.is_file() or path.stat().st_size > 20_000_000:
            continue
        text = path.read_bytes().decode("utf-8", errors="ignore")
        found += [(key, name) for key, value in secrets.items() if value in text]
    assert not found, f"secret values from .env in tracked files (key, file): {found}"


def test_a_password_with_spaces_and_quotes_survives_the_connection_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    awkward = "two words 'and' a\\backslash"
    monkeypatch.setenv("APP_DB_PASSWORD", awkward)
    monkeypatch.setenv("POSTGRES_PASSWORD", awkward)
    settings = Settings()
    assert conninfo_to_dict(app_conninfo(settings))["password"] == awkward
    owner = conninfo_to_dict(owner_conninfo(settings, "litellm"))
    assert (owner["password"], owner["dbname"]) == (awkward, "litellm")
