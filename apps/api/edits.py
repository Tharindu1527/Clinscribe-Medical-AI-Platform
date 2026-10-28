"""Doctors' edits to AI drafts, kept as before/after pairs for evaluation (ADR-0028).

SPEC section 5: "Doctor edits are saved as before/after pairs, which become new evaluation data".
A pair is written when an edited draft is approved. Both sides are the de-identified note the graph
worked on (surrogates such as PERSON_1; the doctor's edits are de-identified before they reach
the graph), never the originals the record holds. The evaluation export
(`evals/agents/edit_pairs.py`) scans every statement again before a pair becomes evaluation data;
retention and erasure (`scripts/retention.py`) delete them.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import psycopg
from psycopg.types.json import Jsonb


@dataclass(frozen=True)
class EditPair:
    draft_id: str
    reviewer: str
    prompt_version: str
    model: str
    before: dict[str, Any]  # the AI draft, a SoapNote
    after: dict[str, Any]  # the note as the doctor approved it
    created_at: datetime | None = None


class EditPairs(Protocol):
    def add(self, pair: EditPair) -> None: ...
    def all(self) -> list[EditPair]: ...  # oldest first


class MemoryEditPairs:
    """Same behaviour as PostgresEditPairs, for unit tests."""

    def __init__(self) -> None:
        self._rows: list[EditPair] = []

    def add(self, pair: EditPair) -> None:
        self._rows.append(pair)

    def all(self) -> list[EditPair]:
        return list(self._rows)


class PostgresEditPairs:
    def __init__(self, conninfo: str) -> None:
        self._conninfo = conninfo

    def add(self, pair: EditPair) -> None:
        with psycopg.connect(self._conninfo) as conn:
            conn.execute(
                "INSERT INTO edit_pairs (draft_id, reviewer, prompt_version, model, before, after) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    pair.draft_id,
                    pair.reviewer,
                    pair.prompt_version,
                    pair.model,
                    Jsonb(pair.before),
                    Jsonb(pair.after),
                ),
            )

    def all(self) -> list[EditPair]:
        with psycopg.connect(self._conninfo) as conn:
            rows = conn.execute(
                "SELECT draft_id, reviewer, prompt_version, model, before, after, created_at "
                "FROM edit_pairs ORDER BY created_at"
            ).fetchall()
        return [EditPair(*row) for row in rows]
