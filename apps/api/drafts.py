"""Drafts awaiting a doctor's review (ADR-0016): who made each one, for which patient, and how it
ended. The draft itself (de-identified transcript and note) lives in the graph's checkpointer; its
checkpoints are deleted when the draft ends, and this record keeps the outcome. No PHI.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import psycopg

WAITING = "awaiting_review"


@dataclass(frozen=True)
class Draft:
    draft_id: str
    patient_id: str  # FHIR id
    encounter_id: str
    created_by: str
    status: str = WAITING
    resource_id: str | None = None


class Drafts(Protocol):
    def add(self, draft: Draft) -> None: ...
    def get(self, draft_id: str) -> Draft | None: ...
    def waiting(self) -> list[Draft]: ...  # newest first
    def finish(self, draft_id: str, status: str, resource_id: str | None) -> None: ...


class MemoryDrafts:
    """Same behaviour as PostgresDrafts, for unit tests."""

    def __init__(self) -> None:
        self._rows: dict[str, Draft] = {}

    def add(self, draft: Draft) -> None:
        self._rows[draft.draft_id] = draft

    def get(self, draft_id: str) -> Draft | None:
        return self._rows.get(draft_id)

    def waiting(self) -> list[Draft]:
        return [d for d in reversed(self._rows.values()) if d.status == WAITING]

    def finish(self, draft_id: str, status: str, resource_id: str | None) -> None:
        old = self._rows[draft_id]
        self._rows[draft_id] = Draft(
            old.draft_id, old.patient_id, old.encounter_id, old.created_by, status, resource_id
        )


class PostgresDrafts:
    COLUMNS = "draft_id, patient_id, encounter_id, created_by, status, resource_id"

    def __init__(self, conninfo: str) -> None:
        self._conninfo = conninfo

    def add(self, draft: Draft) -> None:
        with psycopg.connect(self._conninfo) as conn:
            conn.execute(
                "INSERT INTO drafts (draft_id, patient_id, encounter_id, created_by) "
                "VALUES (%s, %s, %s, %s)",
                (draft.draft_id, draft.patient_id, draft.encounter_id, draft.created_by),
            )

    def get(self, draft_id: str) -> Draft | None:
        with psycopg.connect(self._conninfo) as conn:
            row = conn.execute(
                f"SELECT {self.COLUMNS} FROM drafts WHERE draft_id = %s",  # noqa: S608 (fixed columns)
                (draft_id,),
            ).fetchone()
        return Draft(*row) if row else None

    def waiting(self) -> list[Draft]:
        with psycopg.connect(self._conninfo) as conn:
            rows = conn.execute(
                f"SELECT {self.COLUMNS} FROM drafts WHERE status = %s "  # noqa: S608 (fixed columns)
                "ORDER BY created_at DESC",
                (WAITING,),
            ).fetchall()
        return [Draft(*row) for row in rows]

    def finish(self, draft_id: str, status: str, resource_id: str | None) -> None:
        with psycopg.connect(self._conninfo) as conn:
            conn.execute(
                "UPDATE drafts SET status = %s, resource_id = %s, ended_at = %s "
                "WHERE draft_id = %s",
                (status, resource_id, datetime.now(UTC), draft_id),
            )
