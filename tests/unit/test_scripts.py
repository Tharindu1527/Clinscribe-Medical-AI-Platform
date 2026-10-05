import os
from pathlib import Path

import pytest

from scripts.doctor import is_on_system_drive, wsl_memory_gb
from scripts.gen_keys import GENERATORS, fill_env
from scripts.prepare_dirs import prepare
from scripts.stats import parse_size


def test_gen_keys_fills_only_empty_generated_keys_and_prints_no_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    example = tmp_path / ".env.example"
    example.write_text(
        "GROQ_API_KEY=\nAUDIT_CHAIN_KEY=\nDEID_MAPPING_KEY=keep-me\n", encoding="utf-8"
    )
    env = tmp_path / ".env"

    filled = fill_env(env, example)

    values = dict(line.split("=", 1) for line in env.read_text(encoding="utf-8").splitlines())
    assert filled == ["AUDIT_CHAIN_KEY"]
    assert len(values["AUDIT_CHAIN_KEY"]) == 64
    assert values["DEID_MAPPING_KEY"] == "keep-me"  # existing value untouched
    assert values["GROQ_API_KEY"] == ""  # provider keys are never generated
    assert values["AUDIT_CHAIN_KEY"] not in capsys.readouterr().out

    assert fill_env(env, example) == []  # idempotent


def test_gen_keys_appends_keys_added_to_example_later(tmp_path: Path) -> None:
    example = tmp_path / ".env.example"
    env = tmp_path / ".env"
    env.write_text("GROQ_API_KEY=my-key\n", encoding="utf-8")
    example.write_text(
        "GROQ_API_KEY=\n# HAPI_DB_PASSWORD= (comment)\nHAPI_DB_PASSWORD=\nSYNTHEA_SEED=42\n",
        encoding="utf-8",
    )

    assert fill_env(env, example) == ["HAPI_DB_PASSWORD"]

    values = dict(line.split("=", 1) for line in env.read_text(encoding="utf-8").splitlines())
    assert values["GROQ_API_KEY"] == "my-key"
    assert values["SYNTHEA_SEED"] == "42"  # example default carried over
    assert len(values["HAPI_DB_PASSWORD"]) >= 24


@pytest.mark.parametrize(
    ("text", "expected"),
    [("512MiB", 512 * 2**20), ("1.5GiB", 1.5 * 2**30), ("0B", 0), (" 100kB ", 100_000)],
)
def test_parse_docker_size(text: str, expected: float) -> None:
    assert parse_size(text) == expected


def test_prepare_dirs_creates_writable_folders(tmp_path: Path) -> None:
    target = tmp_path / ".artifacts" / "otel"
    prepare([target])
    prepare([target])  # idempotent
    assert target.is_dir()
    if os.name == "posix":
        assert target.stat().st_mode & 0o777 == 0o777  # the collector's user can write


def test_generated_keys_are_unique() -> None:
    for generate in GENERATORS.values():
        assert generate() != generate()


@pytest.mark.parametrize(
    ("content", "expected"),
    [("[wsl2]\nmemory=10GB\n", 10.0), ("[wsl2]\nmemory = 8192MB\n", 8.0), ("[wsl2]\n", None)],
)
def test_wsl_memory_parsing(tmp_path: Path, content: str, expected: float | None) -> None:
    config = tmp_path / ".wslconfig"
    config.write_text(content, encoding="utf-8")
    assert wsl_memory_gb(config) == expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (r"C:\Users\x\AppData\Local\npm-cache", True),
        ("c:/cache", True),
        (None, True),
        ("", True),
        (r"D:\devcache\uv-cache", False),
    ],
)
def test_is_on_system_drive(path: str | None, expected: bool) -> None:
    assert is_on_system_drive(path) is expected
