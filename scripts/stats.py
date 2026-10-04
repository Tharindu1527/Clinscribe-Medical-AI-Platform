"""Memory use per ClinScribe container and in total (ADR-0003 budget: core stack <= 8 GB).

Usage: uv run python -m scripts.stats
"""

import json
import re
import subprocess
import sys

UNITS = {"B": 1, "KIB": 2**10, "MIB": 2**20, "GIB": 2**30, "KB": 1e3, "MB": 1e6, "GB": 1e9}
BUDGET_BYTES = 8 * 2**30


def parse_size(text: str) -> float:
    """Parse a docker size such as '512.3MiB' or '1.2GiB' into bytes."""
    match = re.fullmatch(r"\s*([\d.]+)\s*([A-Za-z]+)\s*", text)
    if not match:
        raise ValueError(f"unrecognised size: {text!r}")
    return float(match.group(1)) * UNITS[match.group(2).upper()]


def main() -> int:
    out = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{json .}}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    rows = [json.loads(line) for line in out.splitlines() if line.strip()]
    rows = [r for r in rows if r["Name"].startswith("clinscribe-")]
    if not rows:
        print("No clinscribe containers running (just up).")
        return 1

    total = 0.0
    print(f"{'container':<34}{'used':>10}{'limit':>10}")
    for row in sorted(rows, key=lambda r: str(r["Name"])):
        used, limit = (part.strip() for part in row["MemUsage"].split("/"))
        used_bytes = parse_size(used)
        total += used_bytes
        print(f"{row['Name']:<34}{used_bytes / 2**20:>8.0f}MB{parse_size(limit) / 2**20:>8.0f}MB")
    verdict = "within" if total <= BUDGET_BYTES else "OVER"
    print(f"{'total':<34}{total / 2**30:>8.2f}GB   ({verdict} the 8 GB core budget)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
