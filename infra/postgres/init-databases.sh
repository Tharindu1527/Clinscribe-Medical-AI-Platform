#!/bin/sh
# Runs once, when the postgres volume is first created.
# One server, separate databases and least-privilege logins (ADR-0003):
#   clinscribe  owned by POSTGRES_USER; the "app" login gets narrow grants in later tasks (audit, de-ID)
#   litellm     owned by the "litellm" login (gateway spend logs and keys)
#   hapi        owned by the "hapi" login (FHIR server)
# Passwords arrive as psql variables, so they are quoted by psql and never pasted into SQL text.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v litellm_pw="$LITELLM_DB_PASSWORD" \
  -v hapi_pw="$HAPI_DB_PASSWORD" \
  -v app_pw="$APP_DB_PASSWORD" <<'EOSQL'
CREATE ROLE litellm LOGIN PASSWORD :'litellm_pw';
CREATE ROLE hapi LOGIN PASSWORD :'hapi_pw';
CREATE ROLE app LOGIN PASSWORD :'app_pw';

CREATE DATABASE litellm OWNER litellm;
CREATE DATABASE hapi OWNER hapi;

REVOKE ALL ON DATABASE litellm FROM PUBLIC;
REVOKE ALL ON DATABASE hapi FROM PUBLIC;
REVOKE ALL ON DATABASE clinscribe FROM PUBLIC;
GRANT CONNECT ON DATABASE clinscribe TO app;
EOSQL
