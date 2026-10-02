#!/bin/sh
# Runs once when the Postgres volume is first created.
# The middleware connects as payer_app, a NON-superuser: superusers bypass
# row-level security, so the app must never use the bootstrap account.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v app_password="$APP_DB_PASSWORD" <<'SQL'
CREATE ROLE payer_app LOGIN PASSWORD :'app_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
GRANT CONNECT ON DATABASE payer_ai TO payer_app;
GRANT USAGE, CREATE ON SCHEMA public TO payer_app;
SQL
