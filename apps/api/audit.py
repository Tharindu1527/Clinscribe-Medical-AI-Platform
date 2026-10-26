"""Append-only, hash-chained audit log (SPEC section 8: who did what, when, with which model).

Each entry's hash is HMAC-SHA-256(key, previous hash || canonical JSON of the entry). Changing,
removing or reordering any row breaks every later hash, and without the key nobody can rebuild
the chain. The database also refuses UPDATE, DELETE and TRUNCATE (migration 002).
Entries carry opaque ids only (encounter, resource, trace), never PHI.
"""

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from pydantic import SecretStr

GENESIS = bytes(32)
_LOCK_ID = 4_210_771  # advisory lock that serialises appends


@dataclass(frozen=True)
class AuditEntry:
    actor: str
    role: str
    action: str
    resource_type: str | None = None
    resource_id: str | None = None
    encounter_id: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    trace_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    rows: int
    first_bad_seq: int | None = None
    reason: str = ""


_FIELDS = (
    "actor",
    "role",
    "action",
    "resource_type",
    "resource_id",
    "encounter_id",
    "model",
    "prompt_version",
    "trace_id",
)


def _canonical(ts: datetime, values: dict[str, Any]) -> bytes:
    record = {"ts": ts.astimezone(UTC).isoformat(timespec="microseconds"), **values}
    return json.dumps(record, sort_keys=True, separators=(",", ":"), default=str).encode()


def chain_hash(key: bytes, prev_hash: bytes, ts: datetime, values: dict[str, Any]) -> bytes:
    return hmac.new(key, prev_hash + _canonical(ts, values), hashlib.sha256).digest()


class AuditLog:
    def __init__(self, conninfo: str, chain_key: SecretStr) -> None:
        self._conninfo = conninfo
        self._key = chain_key.get_secret_value().encode()
        if not self._key:
            raise ValueError("AUDIT_CHAIN_KEY is empty (run just gen-keys)")

    def append(self, entry: AuditEntry, conn: psycopg.Connection[Any] | None = None) -> int:
        """Append one entry. With `conn`, inside that connection's transaction, so the entry
        commits or rolls back with the change it records (retention and erasure, ADR-0022)."""
        if conn is None:
            with psycopg.connect(self._conninfo) as own:
                return self._append(own, entry)
        return self._append(conn, entry)

    def _append(self, conn: psycopg.Connection[Any], entry: AuditEntry) -> int:
        values = {name: getattr(entry, name) for name in _FIELDS}
        values["details"] = entry.details
        ts = datetime.now(UTC)  # microseconds, the same precision Postgres stores
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_ID,))
            row = conn.execute("SELECT hash FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
            prev = bytes(row[0]) if row else GENESIS
            digest = chain_hash(self._key, prev, ts, values)
            inserted = conn.execute(
                "INSERT INTO audit_log (ts, actor, role, action, resource_type, resource_id,"
                " encounter_id, model, prompt_version, trace_id, details, prev_hash, hash)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING seq",
                (ts, *(values[n] for n in _FIELDS), Jsonb(entry.details), prev, digest),
            ).fetchone()
        if inserted is None:
            raise RuntimeError("audit insert returned no row")
        return int(inserted[0])

    def verify(self, conn: psycopg.Connection[Any] | None = None) -> VerifyResult:
        """Recompute the whole chain. Pass a connection to verify inside an open transaction."""
        if conn is None:
            with psycopg.connect(self._conninfo) as own:
                return self._verify(own)
        return self._verify(conn)

    def _verify(self, conn: psycopg.Connection[Any]) -> VerifyResult:
        rows = conn.execute(
            "SELECT seq, ts, actor, role, action, resource_type, resource_id, encounter_id,"
            " model, prompt_version, trace_id, details, prev_hash, hash"
            " FROM audit_log ORDER BY seq"
        ).fetchall()
        prev = GENESIS
        for row in rows:
            seq, ts = row[0], row[1]
            values = dict(zip(_FIELDS, row[2:11], strict=True))
            values["details"] = row[11]
            stored_prev, stored_hash = bytes(row[12]), bytes(row[13])
            if stored_prev != prev:
                return VerifyResult(
                    False, len(rows), seq, "prev_hash does not link to the row before"
                )
            if not hmac.compare_digest(chain_hash(self._key, prev, ts, values), stored_hash):
                return VerifyResult(False, len(rows), seq, "hash does not match the row contents")
            prev = stored_hash
        return VerifyResult(True, len(rows))
