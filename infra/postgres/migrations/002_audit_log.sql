-- Append-only, hash-chained audit log (SPEC section 8, PROGRESS task 8).
-- Who did what, when, with which model and prompt version. Rows hold opaque ids, never PHI.
-- hash = HMAC-SHA-256(AUDIT_CHAIN_KEY, prev_hash || canonical JSON of the row); see apps/api/audit.py.
CREATE TABLE IF NOT EXISTS audit_log (
    seq            bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts             timestamptz NOT NULL,
    actor          text        NOT NULL,
    role           text        NOT NULL,
    action         text        NOT NULL,
    resource_type  text,
    resource_id    text,
    encounter_id   text,
    model          text,
    prompt_version text,
    trace_id       text,
    details        jsonb       NOT NULL DEFAULT '{}'::jsonb,
    prev_hash      bytea       NOT NULL,
    hash           bytea       NOT NULL UNIQUE
);

CREATE OR REPLACE FUNCTION audit_log_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only: % is not allowed', TG_OP;
END;
$$;

-- Triggers fire for every role, the table owner included
DROP TRIGGER IF EXISTS audit_log_no_update_delete ON audit_log;
CREATE TRIGGER audit_log_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();

DROP TRIGGER IF EXISTS audit_log_no_truncate ON audit_log;
CREATE TRIGGER audit_log_no_truncate
    BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION audit_log_append_only();

-- The app login can only add and read entries
GRANT SELECT, INSERT ON audit_log TO app;
