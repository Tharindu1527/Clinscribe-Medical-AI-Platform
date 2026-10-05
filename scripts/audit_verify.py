"""Recompute the audit log's hash chain and report the first broken row (task 8).

Usage: uv run python -m scripts.audit_verify   (exit 1 if the chain is broken)
"""

import sys

from apps.api.audit import AuditLog
from config.db import app_conninfo
from config.settings import Settings


def main() -> int:
    settings = Settings()
    result = AuditLog(app_conninfo(settings), settings.audit_chain_key).verify()
    if result.ok:
        print(f"audit chain OK: {result.rows} rows verified")
        return 0
    print(f"audit chain BROKEN at seq {result.first_bad_seq}: {result.reason} ({result.rows} rows)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
