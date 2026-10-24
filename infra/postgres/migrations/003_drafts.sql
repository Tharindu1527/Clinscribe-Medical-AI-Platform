-- Drafts awaiting a doctor's review (ADR-0016). The draft itself (de-identified transcript and note)
-- lives in LangGraph's checkpoint tables, created by scripts/migrate.py; this table lists drafts and
-- keeps how each one ended after its checkpoints are deleted. No PHI: the patient is a FHIR id.
CREATE TABLE IF NOT EXISTS drafts (
    draft_id     text        PRIMARY KEY,
    patient_id   text        NOT NULL,
    encounter_id text        NOT NULL,
    created_by   text        NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    status       text        NOT NULL DEFAULT 'awaiting_review',
    resource_id  text,
    ended_at     timestamptz
);
CREATE INDEX IF NOT EXISTS drafts_waiting ON drafts (created_at) WHERE status = 'awaiting_review';

-- The API (login "app") adds drafts and records their outcome; it never deletes a row.
GRANT SELECT, INSERT, UPDATE ON drafts TO app;
