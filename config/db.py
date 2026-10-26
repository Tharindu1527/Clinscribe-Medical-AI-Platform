"""Postgres connection strings (one place): the clinscribe database's logins and Grafana's."""

from psycopg.conninfo import make_conninfo

from config.settings import Settings

APP_DB_USER = "app"  # least-privilege login created by infra/postgres/init-databases.sh
RETENTION_DB_USER = "retention"  # retention and erasure jobs, created by scripts/migrate.py
GRAFANA_DB_USER = "grafana_reader"  # dashboards (ADR-0023), created by scripts/migrate.py


def _conninfo(settings: Settings, user: str, secret: str, dbname: str = "clinscribe") -> str:
    # make_conninfo quotes every value, so a password with a space or a quote still works (an
    # f-string did not); connect_timeout: fail fast (see the localhost/::1 note in PROGRESS)
    return make_conninfo(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=dbname,
        user=user,
        password=secret,
        connect_timeout=10,
    )


def app_conninfo(settings: Settings) -> str:
    """The `app` login: SELECT/INSERT on deid_mappings and audit_log only."""
    return _conninfo(settings, APP_DB_USER, settings.app_db_password.get_secret_value())


def retention_conninfo(settings: Settings) -> str:
    """The `retention` login: deletes de-ID mappings and ends drafts; appends to the audit log."""
    return _conninfo(settings, RETENTION_DB_USER, settings.retention_db_password.get_secret_value())


def owner_conninfo(settings: Settings, dbname: str = "clinscribe") -> str:
    """The database owner: migrations and administrative tests only."""
    return _conninfo(
        settings, settings.postgres_user, settings.postgres_password.get_secret_value(), dbname
    )


def grafana_conninfo(settings: Settings) -> str:
    """Grafana's login on the gateway database: SELECT on a few spend-log columns (ADR-0023)."""
    return _conninfo(
        settings, GRAFANA_DB_USER, settings.grafana_db_password.get_secret_value(), "litellm"
    )
