"""Create host folders that containers write to, before `just up` (bind mounts).

If Docker creates a bind-mount folder itself on Linux, it is owned by root, and the OTel collector
(an unprivileged user) cannot write its trace file and restarts in a loop. That was the CI failure
on 2026-10-06; Docker Desktop on Windows does not enforce these permissions, so it never showed.
The folder holds redacted, synthetic-only trace exports, so making it world-writable is acceptable.
"""

import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRITABLE_DIRS = [ROOT / ".artifacts" / "otel"]


def prepare(dirs: list[Path] = WRITABLE_DIRS) -> None:
    for directory in dirs:
        directory.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            directory.chmod(stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)


def main() -> int:
    prepare()
    return 0


if __name__ == "__main__":
    sys.exit(main())
