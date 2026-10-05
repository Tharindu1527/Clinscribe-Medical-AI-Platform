-- Surrogate mapping for the de-ID service (PROGRESS task 6). No plaintext PHI is stored:
--   lookup_hash = HMAC(encounter, entity type, normalised value) finds an existing surrogate;
--   ciphertext  = Fernet(original value), decrypted only to re-identify on the doctor's screen.
CREATE TABLE IF NOT EXISTS deid_mappings (
    encounter_id text        NOT NULL,
    lookup_hash  bytea       NOT NULL,
    entity_type  text        NOT NULL,
    surrogate    text        NOT NULL,
    ciphertext   bytea       NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (encounter_id, lookup_hash),
    UNIQUE (encounter_id, surrogate)
);

-- The de-ID service connects as "app": it may add and read mappings, never change or delete them.
GRANT SELECT, INSERT ON deid_mappings TO app;
