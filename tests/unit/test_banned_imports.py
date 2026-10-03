"""The gateway rule (CLAUDE.md, ADR-0001) is enforced by ruff: `just lint` fails on a violation."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _ruff_check(source: str, pretend_path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-cache",
            "--stdin-filename",
            pretend_path,
            "-",
        ],
        input=source,
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )


@pytest.mark.parametrize(
    "source",
    [
        "import openai\n",
        "from openai import OpenAI\n",
        "import litellm\n",
        "from google import genai\n",
        "import groq\n",
    ],
)
def test_provider_sdk_import_outside_gateway_fails_lint(source: str) -> None:
    result = _ruff_check(source, "apps/api/probe.py")
    assert result.returncode != 0
    assert "TID251" in result.stdout


def test_provider_sdk_import_inside_gateway_is_allowed() -> None:
    result = _ruff_check("import openai\n\n__all__ = ['openai']\n", "llmops/gateway/probe.py")
    assert result.returncode == 0, result.stdout
