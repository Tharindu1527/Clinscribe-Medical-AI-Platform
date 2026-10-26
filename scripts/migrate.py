"""Apply SQL migrations (infra/postgres/migrations) to the clinscribe database, in order, once each,
then create or update LangGraph's checkpoint tables (drafts awaiting review, ADR-0016).
Before the migrations it creates the "retention" login (ADR-0022) or resets its password.

Usage: uv run python -m scripts.migrate
Runs as the database owner (POSTGRES_USER), records applied files in `schema_migrations`.
"""

import sys
from pathlib import Path
from typing import Any

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import sql
from psycopg.rows import dict_row

from config.db import APP_DB_USER, RETENTION_DB_USER, owner_conninfo
from config.settings import Settings

MIGRATIONS = Path(__file__).resolve().parents[1] / "infra" / "postgres" / "migrations"
# LangGraph's own tables (its setup() migrates them); the API reads and writes checkpoints and
# deletes a draft's checkpoints when the draft ends
CHECKPOINT_TABLES = ("checkpoints", "checkpoint_blobs", "checkpoint_writes")


def ensure_retention_login(conn: psycopg.Connection[Any], password: str) -> None:
    """The retention jobs' login; its password is sent as a literal, never printed or logged."""
    if not password:
        raise SystemExit("RETENTION_DB_PASSWORD is empty (run just gen-keys)")
    role = sql.Identifier(RETENTION_DB_USER)
    exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (RETENTION_DB_USER,))
    verb = "ALTER" if exists.fetchone() else "CREATE"
    conn.execute(sql.SQL(verb + " ROLE {} LOGIN PASSWORD {}").format(role, sql.Literal(password)))
    conn.execute(sql.SQL("GRANT CONNECT ON DATABASE clinscribe TO {}").format(role))


def main() -> int:
    applied_now = []
    settings = Settings()
    with psycopg.connect(owner_conninfo(settings)) as conn:
        ensure_retention_login(conn, settings.retention_db_password.get_secret_value())
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
        for table, privileges, role in [
            *((t, "SELECT, INSERT, UPDATE, DELETE", APP_DB_USER) for t in CHECKPOINT_TABLES),
            ("checkpoint_migrations", "SELECT", APP_DB_USER),
            *((t, "SELECT, DELETE", RETENTION_DB_USER) for t in CHECKPOINT_TABLES),
        ]:
            conn.execute(
                sql.SQL(grant).format(
                    privileges=sql.SQL(privileges),
                    table=sql.Identifier(table),
                    role=sql.Identifier(role),
                )
            )
    print("applied: " + (", ".join(applied_now) if applied_now else "nothing (up to date)"))
    print("checkpoint tables: up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
