from pathlib import Path
from typing import Any

from pydantic import SecretStr

from config.settings import Settings

ROOT = Path(__file__).resolve().parents[2]


def _example_keys() -> set[str]:
    keys = set()
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            keys.add(line.split("=", 1)[0].strip())
    return keys


def test_every_setting_has_an_env_example_key_and_vice_versa() -> None:
    fields = {name.upper() for name in Settings.model_fields}
    keys = _example_keys()
    assert fields - keys == set(), "Settings fields missing from .env.example"
    assert keys - fields == set(), ".env.example keys without a Settings field"


def test_settings_load_without_env_file() -> None:
    settings = Settings(_env_file=None)
    assert settings.synthea_seed == 42
    assert settings.langfuse_host == "https://cloud.langfuse.com"


def test_secret_values_never_appear_in_repr_str_or_json() -> None:
    secret_fields = [
        name for name, field in Settings.model_fields.items() if field.annotation is SecretStr
    ]
    values: dict[str, Any] = {name: SecretStr(f"canary-{name}-value") for name in secret_fields}
    settings = Settings(_env_file=None, **values)

    rendered = repr(settings) + str(settings) + settings.model_dump_json()
    for name in secret_fields:
        assert f"canary-{name}-value" not in rendered
    assert len(secret_fields) >= 10
