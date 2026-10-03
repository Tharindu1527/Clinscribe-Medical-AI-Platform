from pathlib import Path

import pytest

from scripts.doctor import wsl_memory_gb
from scripts.gen_keys import GENERATORS, fill_env


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
