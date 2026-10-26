"""Surrogate mapping: the same PHI value gets the same surrogate within an encounter.

No plaintext is stored. Each value is found by a keyed hash (HMAC) and kept only as Fernet
ciphertext, which is decrypted solely to re-identify text on the doctor's own screen.
"""

import hashlib
import hmac
import re
from typing import Protocol

import psycopg
from cryptography.fernet import Fernet
from pydantic import SecretStr


def normalise(value: str) -> str:
    """Compare values by letters and digits only: '(555) 123-4567' == '555.123.4567'."""
    return re.sub(r"[\W_]+", "", value.casefold())


class SurrogateStore(Protocol):
    def surrogate_for(self, encounter_id: str, entity: str, value: str) -> str: ...

    def original_for(self, encounter_id: str, surrogate: str) -> str | None: ...


class _Keys:
    def __init__(self, mapping_key: SecretStr) -> None:
        raw = mapping_key.get_secret_value().encode()
        if not raw:
            raise ValueError("DEID_MAPPING_KEY is empty (run just gen-keys)")
        self.fernet = Fernet(raw)
        self._lookup_key = hashlib.sha256(b"clinscribe-deid-lookup:" + raw).digest()

    def lookup(self, encounter_id: str, entity: str, value: str) -> bytes:
        message = f"{encounter_id}\x1f{entity}\x1f{normalise(value)}".encode()
        return hmac.new(self._lookup_key, message, hashlib.sha256).digest()


class InMemoryStore:
    """Same behaviour as PostgresStore, for unit tests and offline evaluation."""

    def __init__(self, mapping_key: SecretStr) -> None:
        self._keys = _Keys(mapping_key)
        self._by_lookup: dict[tuple[str, bytes], str] = {}
        self._ciphertext: dict[tuple[str, str], bytes] = {}

    def surrogate_for(self, encounter_id: str, entity: str, value: str) -> str:
        key = (encounter_id, self._keys.lookup(encounter_id, entity, value))
        if key not in self._by_lookup:
            count = sum(
                1
                for (enc, sur) in self._ciphertext
                if enc == encounter_id and sur.startswith(entity + "_")
            )
            surrogate = f"{entity}_{count + 1}"
            self._by_lookup[key] = surrogate
            self._ciphertext[(encounter_id, surrogate)] = self._keys.fernet.encrypt(value.encode())
        return self._by_lookup[key]

    def original_for(self, encounter_id: str, surrogate: str) -> str | None:
        token = self._ciphertext.get((encounter_id, surrogate))
        return self._keys.fernet.decrypt(token).decode() if token else None

    def entries(self, encounter_id: str) -> list[tuple[str, str, str]]:
        return sorted(
            (sur.rsplit("_", 1)[0], sur, self._keys.fernet.decrypt(token).decode())
            for (enc, sur), token in self._ciphertext.items()
            if enc == encounter_id
        )


class PostgresStore:
    """Mapping in the `deid_mappings` table (infra/postgres/migrations/001_deid_mappings.sql)."""

    def __init__(self, conninfo: str, mapping_key: SecretStr) -> None:
        self._conninfo = conninfo
        self._keys = _Keys(mapping_key)

    def surrogate_for(self, encounter_id: str, entity: str, value: str) -> str:
        lookup = self._keys.lookup(encounter_id, entity, value)
        with psycopg.connect(self._conninfo) as conn, conn.transaction():
            # Serialise numbering per encounter so concurrent requests never reuse a surrogate
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (encounter_id,))
            row = conn.execute(
                "SELECT surrogate FROM deid_mappings WHERE encounter_id = %s AND lookup_hash = %s",
                (encounter_id, lookup),
            ).fetchone()
            if row:
                return str(row[0])
            count_row = conn.execute(
                "SELECT count(*) FROM deid_mappings WHERE encounter_id = %s AND entity_type = %s",
                (encounter_id, entity),
            ).fetchone()
            surrogate = f"{entity}_{(count_row[0] if count_row else 0) + 1}"
            conn.execute(
                "INSERT INTO deid_mappings (encounter_id, lookup_hash, entity_type, surrogate,"
                " ciphertext) VALUES (%s, %s, %s, %s, %s)",
                (
                    encounter_id,
                    lookup,
                    entity,
                    surrogate,
                    self._keys.fernet.encrypt(value.encode()),
                ),
            )
            return surrogate

    def original_for(self, encounter_id: str, surrogate: str) -> str | None:
        with psycopg.connect(self._conninfo) as conn:
            row = conn.execute(
                "SELECT ciphertext FROM deid_mappings WHERE encounter_id = %s AND surrogate = %s",
                (encounter_id, surrogate),
            ).fetchone()
        return self._keys.fernet.decrypt(bytes(row[0])).decode() if row else None

    def entries(self, encounter_id: str) -> list[tuple[str, str, str]]:
        """(entity type, surrogate, original) for one encounter: a data subject's copy of what the
        mapping holds (GDPR Art. 15, ADR-0022). Decrypted here; never logged."""
        with psycopg.connect(self._conninfo) as conn:
            rows = conn.execute(
                "SELECT entity_type, surrogate, ciphertext FROM deid_mappings "
                "WHERE encounter_id = %s ORDER BY entity_type, surrogate",
                (encounter_id,),
            ).fetchall()
        return [(str(e), str(s), self._keys.fernet.decrypt(bytes(c)).decode()) for e, s, c in rows]
