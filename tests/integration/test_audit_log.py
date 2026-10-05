"""PROGRESS task 8 gate: the audit log is append-only and its hash chain catches tampering.

Entries written here stay in the log (it is append-only by design); they are labelled actor="test".
"""

from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from apps.api.audit import AuditEntry, AuditLog
from config.db import app_conninfo, owner_conninfo
from config.settings import Settings
from scripts import migrate


@pytest.fixture(scope="module")
def audit(stack: list[dict[str, str]]) -> AuditLog:
    assert migrate.main() == 0
    settings = Settings()
    return AuditLog(app_conninfo(settings), settings.audit_chain_key)


def _entry(i: int) -> AuditEntry:
    return AuditEntry(
        actor="test", role="operator", action="test.append", resource_id=f"r-{i}", details={"i": i}
    )


def test_chain_verifies_after_100_appends_including_10_concurrent(audit: AuditLog) -> None:
    for i in range(90):
        audit.append(_entry(i))
    with ThreadPoolExecutor(max_workers=10) as pool:
        seqs = list(pool.map(lambda i: audit.append(_entry(i)), range(90, 100)))
    assert len(set(seqs)) == 10
    result = audit.verify()
    assert result.ok, result
    assert result.rows >= 100


@pytest.mark.parametrize(
    "sql", ["UPDATE audit_log SET actor = 'mallory'", "DELETE FROM audit_log", "TRUNCATE audit_log"]
)
def test_app_login_cannot_change_or_remove_entries(audit: AuditLog, sql: str) -> None:
    with (
        psycopg.connect(app_conninfo(Settings())) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute(sql)


def test_even_the_owner_is_blocked_by_the_trigger(audit: AuditLog) -> None:
    with (
        psycopg.connect(owner_conninfo(Settings())) as conn,
        pytest.raises(psycopg.errors.RaiseException, match="append-only"),
    ):
        conn.execute("UPDATE audit_log SET actor = 'mallory' WHERE seq = 1")


def test_tampering_is_reported_at_the_exact_row(audit: AuditLog) -> None:
    target = audit.append(_entry(-1))
    audit.append(_entry(-2))  # a later row, so the break is not simply the last one
    with psycopg.connect(owner_conninfo(Settings())) as conn:
        # Simulate an attacker with owner rights; everything is rolled back afterwards
        conn.execute("ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_update_delete")
        conn.execute("UPDATE audit_log SET actor = 'mallory' WHERE seq = %s", (target,))
        result = audit.verify(conn)
        conn.rollback()
    assert not result.ok
    assert result.first_bad_seq == target
    assert "hash does not match" in result.reason
    assert audit.verify().ok  # rollback left the real chain intact
