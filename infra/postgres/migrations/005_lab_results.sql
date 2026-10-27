-- Lab results awaiting the doctor's confirmation (apps/api/labs.py), until now in the API's memory.
-- The payload (parsed values, flags, identity checks) is kept only while the result waits; when
-- it ends (confirmed, expired, erased) the payload is set to NULL and the row keeps the outcome.
-- The patient is a FHIR id; names and birth dates are not stored, only whether they matched.
CREATE TABLE IF NOT EXISTS lab_results (
    lab_id      text        PRIMARY KEY,
    patient_id  text        NOT NULL,
    created_by  text        NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    status      text        NOT NULL DEFAULT 'awaiting_confirmation',
    payload     jsonb,
    written     jsonb,
    ended_at    timestamptz
);
CREATE INDEX IF NOT EXISTS lab_results_waiting ON lab_results (created_at)
    WHERE status = 'awaiting_confirmation';

-- The API adds results and records how they ended; the retention login (ADR-0022) ends them on
-- the retention limit or an erasure request. Neither deletes a row.
GRANT SELECT, INSERT, UPDATE ON lab_results TO app;
GRANT SELECT, UPDATE ON lab_results TO retention;
