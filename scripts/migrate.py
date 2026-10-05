"""Apply SQL migrations (infra/postgres/migrations) to the clinscribe database, in order, once each.

Usage: uv run python -m scripts.migrate
Runs as the database owner (POSTGRES_USER), records applied files in `schema_migrations`.
"""

import sys
from pathlib import Path

import psycopg

from config.db import owner_conninfo
from config.settings import Settings

MIGRATIONS = Path(__file__).resolve().parents[1] / "infra" / "postgres" / "migrations"


def main() -> int:
    applied_now = []
    with psycopg.connect(owner_conninfo(Settings())) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        for path in sorted(MIGRATIONS.glob("*.sql")):
            if path.name in done:
                continue
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8").encode())
                conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.name,))
            applied_now.append(path.name)
    print("applied: " + (", ".join(applied_now) if applied_now else "nothing (up to date)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
