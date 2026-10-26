"""Apply SQL migrations (infra/postgres/migrations) to the clinscribe database, in order, once each,
then create or update LangGraph's checkpoint tables (drafts awaiting review, ADR-0016).
Before the migrations it creates the "retention" login (ADR-0022) or resets its password; after
them, Grafana's read-only login on the gateway's spend log (ADR-0023).

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

from config.db import APP_DB_USER, GRAFANA_DB_USER, RETENTION_DB_USER, owner_conninfo
from config.settings import Settings

MIGRATIONS = Path(__file__).resolve().parents[1] / "infra" / "postgres" / "migrations"
# LangGraph's own tables (its setup() migrates them); the API reads and writes checkpoints and
# deletes a draft's checkpoints when the draft ends
CHECKPOINT_TABLES = ("checkpoints", "checkpoint_blobs", "checkpoint_writes")


# The spend-log columns the dashboards read: no request or response content, no keys
SPEND_COLUMNS = (
    "startTime",
    "model",
    "model_group",
    "spend",
    "status",
    "total_tokens",
    "prompt_tokens",
    "completion_tokens",
    "request_duration_ms",
    "metadata",  # spend_logs_metadata: encounter id and requested alias (gateway client)
)


def ensure_login(conn: psycopg.Connection[Any], name: str, password: str, database: str) -> None:
    """Create a login or reset its password; the password is sent as a literal, never printed."""
    if not password:
        raise SystemExit(f"the password for {name} is empty (run just gen-keys)")
    role = sql.Identifier(name)
    exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,))
    verb = "ALTER" if exists.fetchone() else "CREATE"
    conn.execute(sql.SQL(verb + " ROLE {} LOGIN PASSWORD {}").format(role, sql.Literal(password)))
    conn.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database), role)
    )


def grant_spend_log_columns(settings: Settings) -> str:
    """Grafana's login may read SPEND_COLUMNS of LiteLLM's spend log, nothing else (ADR-0023)."""
    with psycopg.connect(owner_conninfo(settings, "litellm")) as conn:
        table = conn.execute("""SELECT to_regclass('public."LiteLLM_SpendLogs"')""").fetchone()
        if table is None or table[0] is None:
            return "spend log: table not created yet (start the gateway, then run just migrate)"
        role = sql.Identifier(GRAFANA_DB_USER)
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
        conn.execute(
            sql.SQL('GRANT SELECT ({}) ON "LiteLLM_SpendLogs" TO {}').format(
                sql.SQL(", ").join(sql.Identifier(c) for c in SPEND_COLUMNS), role
            )
        )
    return "spend log: Grafana's read-only columns granted"


def main() -> int:
    applied_now = []
    settings = Settings()
    with psycopg.connect(owner_conninfo(settings)) as conn:
        ensure_login(
            conn, RETENTION_DB_USER, settings.retention_db_password.get_secret_value(), "clinscribe"
        )
        ensure_login(
            conn, GRAFANA_DB_USER, settings.grafana_db_password.get_secret_value(), "litellm"
        )
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
    print(grant_spend_log_columns(settings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
