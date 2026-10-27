"""Lab results awaiting the doctor's confirmation (Lab mode). They lived in the API's memory, so a
restart dropped them, and retention, erasure and access requests could not reach them (ADR-0016
update). The parsed values are kept only until the doctor confirms: then they are in the FHIR
record, and this row keeps who, when, how it ended and which Observations were written.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

AWAITING = "awaiting_confirmation"


@dataclass(frozen=True)
class PendingLab:
    lab_id: str
    patient_id: str  # FHIR id
    created_by: str
    # parse_lab_report's result: preliminary observations, abnormal, identity, not mapped, ...
    payload: dict[str, Any] = field(default_factory=dict)


class PostgresLabResults:
    """The `lab_results` table (infra/postgres/migrations/005_lab_results.sql)."""

    def __init__(self, conninfo: str) -> None:
        self._conninfo = conninfo

    def add(self, lab: PendingLab) -> None:
        with psycopg.connect(self._conninfo) as conn:
            conn.execute(
                "INSERT INTO lab_results (lab_id, patient_id, created_by, payload) "
                "VALUES (%s, %s, %s, %s)",
                (lab.lab_id, lab.patient_id, lab.created_by, Jsonb(lab.payload)),
            )

    def get(self, lab_id: str) -> PendingLab | None:
        with psycopg.connect(self._conninfo) as conn:
            row = conn.execute(
                "SELECT lab_id, patient_id, created_by, payload FROM lab_results "
                "WHERE lab_id = %s AND status = %s",
                (lab_id, AWAITING),
            ).fetchone()
        return PendingLab(str(row[0]), str(row[1]), str(row[2]), dict(row[3])) if row else None

    def finish(self, lab_id: str, status: str, written: list[str]) -> None:
        """End the result and drop its values: once confirmed they live in the FHIR record."""
        with psycopg.connect(self._conninfo) as conn:
            conn.execute(
                "UPDATE lab_results SET status = %s, written = %s, payload = NULL, ended_at = %s "
                "WHERE lab_id = %s AND status = %s",
                (status, Jsonb(written), datetime.now(UTC), lab_id, AWAITING),
            )
