"""Run the voice agent's smoke test in its own uv project with a fresh demo-doctor token."""

import os
import subprocess
import sys
from pathlib import Path

from apps.api.auth import issue_token
from config.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    env = {**os.environ, "CLINSCRIBE_TOKEN": issue_token("dr-demo", Settings().auth_token_key)}
    env.pop("VIRTUAL_ENV", None)  # let uv pick the voice project's environment
    command = ["uv", "run", "--project", "voice", "python", "voice/smoke.py"]
    return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
