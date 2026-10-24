"""Apply SQL migrations (infra/postgres/migrations) to the clinscribe database, in order, once each,
then create or update LangGraph's checkpoint tables (drafts awaiting review, ADR-0016).

Usage: uv run python -m scripts.migrate
Runs as the database owner (POSTGRES_USER), records applied files in `schema_migrations`.
"""

import sys
from pathlib import Path

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import sql
from psycopg.rows import dict_row

from config.db import APP_DB_USER, owner_conninfo
from config.settings import Settings

MIGRATIONS = Path(__file__).resolve().parents[1] / "infra" / "postgres" / "migrations"
# LangGraph's own tables (its setup() migrates them); the API reads and writes checkpoints and
# deletes a draft's checkpoints when the draft ends
CHECKPOINT_TABLES = ("checkpoints", "checkpoint_blobs", "checkpoint_writes")


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
    # setup() creates indexes CONCURRENTLY, which needs autocommit
    with psycopg.connect(owner_conninfo(Settings()), autocommit=True, row_factory=dict_row) as conn:
        PostgresSaver(conn).setup()
        grant = "GRANT {privileges} ON {table} TO {role}"
        for table, privileges in [
            *((t, "SELECT, INSERT, UPDATE, DELETE") for t in CHECKPOINT_TABLES),
            ("checkpoint_migrations", "SELECT"),
        ]:
            conn.execute(
                sql.SQL(grant).format(
                    privileges=sql.SQL(privileges),
                    table=sql.Identifier(table),
                    role=sql.Identifier(APP_DB_USER),
                )
            )
    print("applied: " + (", ".join(applied_now) if applied_now else "nothing (up to date)"))
    print("checkpoint tables: up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
