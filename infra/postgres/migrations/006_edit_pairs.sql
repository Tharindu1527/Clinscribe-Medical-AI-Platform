-- Doctors' edits to AI drafts as before/after pairs (SPEC section 5: "Doctor edits are saved as
-- before/after pairs, which become new evaluation data"; ADR-0028), written when an edited draft is
-- approved. Both sides are the de-identified note (surrogates such as PERSON_1), never the record's
-- originals; the patient is reached through the draft (drafts.patient_id), so an erasure finds them.
CREATE TABLE IF NOT EXISTS edit_pairs (
    draft_id        text        PRIMARY KEY REFERENCES drafts (draft_id),
    reviewer        text        NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    prompt_version  text        NOT NULL,
    model           text        NOT NULL,
    before          jsonb       NOT NULL,
    after           jsonb       NOT NULL
);

-- The API adds pairs and the evaluation export reads them; only the retention login (ADR-0022)
-- deletes one, on the retention limit or an erasure request.
GRANT SELECT, INSERT ON edit_pairs TO app;
GRANT SELECT, DELETE ON edit_pairs TO retention;
