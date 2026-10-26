-- Retention limits and GDPR erasure (ADR-0022) run as the "retention" login, which
-- scripts/migrate.py creates (with its password) before applying this file. It deletes de-ID
-- mappings and ends drafts; it may only append to the audit log, whose triggers block UPDATE,
-- DELETE and TRUNCATE for every role. The API's "app" login still cannot delete a mapping.
GRANT SELECT, DELETE ON deid_mappings TO retention;
GRANT SELECT, UPDATE ON drafts TO retention;
GRANT SELECT, INSERT ON audit_log TO retention;
