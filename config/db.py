"""Postgres connection strings for the clinscribe database (one place, three logins)."""

from config.settings import Settings

APP_DB_USER = "app"  # least-privilege login created by infra/postgres/init-databases.sh
RETENTION_DB_USER = "retention"  # retention and erasure jobs, created by scripts/migrate.py


def _conninfo(settings: Settings, user: str, password: str) -> str:
    # connect_timeout: fail fast instead of hanging (see the localhost/::1 note in PROGRESS)
    return (
        f"host={settings.postgres_host} port={settings.postgres_port} dbname=clinscribe "
        f"user={user} password={password} connect_timeout=10"
    )


def app_conninfo(settings: Settings) -> str:
    """The `app` login: SELECT/INSERT on deid_mappings and audit_log only."""
    return _conninfo(settings, APP_DB_USER, settings.app_db_password.get_secret_value())


def retention_conninfo(settings: Settings) -> str:
    """The `retention` login: deletes de-ID mappings and ends drafts; appends to the audit log."""
    return _conninfo(settings, RETENTION_DB_USER, settings.retention_db_password.get_secret_value())


def owner_conninfo(settings: Settings) -> str:
    """The database owner: migrations and administrative tests only."""
    return _conninfo(
        settings, settings.postgres_user, settings.postgres_password.get_secret_value()
    )
