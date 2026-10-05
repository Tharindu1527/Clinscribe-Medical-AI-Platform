from datetime import UTC, datetime

from apps.api.audit import GENESIS, chain_hash

KEY = b"test-chain-key"
TS = datetime(2026, 10, 5, 12, 0, 0, 123456, tzinfo=UTC)
VALUES = {"actor": "dr-1", "role": "doctor", "action": "note.approve", "details": {"n": 1}}


def test_hash_is_deterministic() -> None:
    assert chain_hash(KEY, GENESIS, TS, VALUES) == chain_hash(KEY, GENESIS, TS, dict(VALUES))


def test_any_change_changes_the_hash() -> None:
    base = chain_hash(KEY, GENESIS, TS, VALUES)
    assert chain_hash(KEY, GENESIS, TS, {**VALUES, "actor": "dr-2"}) != base
    assert chain_hash(KEY, GENESIS, TS, {**VALUES, "details": {"n": 2}}) != base
    assert chain_hash(KEY, GENESIS, TS.replace(microsecond=0), VALUES) != base
    assert chain_hash(KEY, b"\x01" * 32, TS, VALUES) != base  # different previous link
    assert chain_hash(b"other-key", GENESIS, TS, VALUES) != base  # needs the key to rebuild
