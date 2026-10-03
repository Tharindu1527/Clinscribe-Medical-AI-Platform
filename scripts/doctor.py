"""Check that the local prerequisites for ClinScribe are installed (PROGRESS task 0).

Usage: uv run python -m scripts.doctor
Exits 1 if a required tool is missing. Never prints secret values.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REQUIRED_TOOLS = ["uv", "just", "docker"]
OPTIONAL_TOOLS = ["ollama"]
WSL_TARGET_GB = 10
# The C: drive is nearly full on the dev machine: every cache must live on another drive.
CACHE_ENV_VARS = [
    "UV_CACHE_DIR",
    "UV_PYTHON_INSTALL_DIR",
    "UV_TOOL_DIR",
    "OLLAMA_MODELS",
    "HF_HOME",
]


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False)  # noqa: S603
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return proc.returncode, (proc.stdout or proc.stderr).strip()


def wsl_memory_gb(wslconfig: Path) -> float | None:
    """Return the `memory=` cap from a .wslconfig file, in GB, or None if not set."""
    if not wslconfig.is_file():
        return None
    match = re.search(
        r"^\s*memory\s*=\s*(\d+(?:\.\d+)?)\s*(GB|MB)\s*$",
        wslconfig.read_text(encoding="utf-8"),
        re.IGNORECASE | re.MULTILINE,
    )
    if not match:
        return None
    value = float(match.group(1))
    return value / 1024 if match.group(2).upper() == "MB" else value


def is_on_system_drive(path: str | None) -> bool:
    """True if the path is unset or on C: (where Windows puts caches by default)."""
    return not path or path.strip().upper().startswith("C:")


def main() -> int:
    failed = False

    def report(ok: bool, label: str, detail: str = "", required: bool = True) -> None:
        nonlocal failed
        status = "OK  " if ok else ("FAIL" if required else "WARN")
        print(f"[{status}] {label}{': ' + detail if detail else ''}")
        failed = failed or (required and not ok)

    for tool in REQUIRED_TOOLS + OPTIONAL_TOOLS:
        path = shutil.which(tool)
        report(path is not None, tool, path or "not on PATH", required=tool in REQUIRED_TOOLS)

    report(sys.version_info[:2] == (3, 11), "python 3.11 (project venv)", sys.version.split()[0])

    if shutil.which("docker"):
        code, out = _run(["docker", "info", "--format", "{{.MemTotal}}"])
        detail = (
            f"{int(out) / 2**30:.1f} GB available to Docker"
            if code == 0 and out.isdigit()
            else "daemon not reachable"
        )
        report(code == 0, "docker daemon", detail)

    if shutil.which("ollama"):
        code, out = _run(["ollama", "list"])
        models = (
            [line.split()[0] for line in out.splitlines()[1:] if line.strip()] if code == 0 else []
        )
        report(bool(models), "ollama model pulled", ", ".join(models) or "none", required=False)

    if os.name == "nt":
        cap = wsl_memory_gb(Path.home() / ".wslconfig")
        report(
            cap == WSL_TARGET_GB,
            "WSL2 memory cap",
            f"{cap} GB (target {WSL_TARGET_GB} GB)" if cap else "not set in ~/.wslconfig",
            required=False,
        )

    if os.name == "nt":
        for var in CACHE_ENV_VARS:
            value = os.environ.get(var)
            report(not is_on_system_drive(value), f"{var} off C:", value or "unset", required=False)
        npm = shutil.which("npm")  # npm.cmd on Windows, so use the resolved path
        if npm:
            code, npm_cache = _run([npm, "config", "get", "cache"])
            ok = code == 0 and not is_on_system_drive(npm_cache)
            report(ok, "npm cache off C:", npm_cache, required=False)

    report(
        Path(".env").is_file(),
        ".env present",
        "" if Path(".env").is_file() else "copy .env.example, then just gen-keys",
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
