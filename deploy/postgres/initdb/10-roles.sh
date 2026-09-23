#!/usr/bin/env bash
# Provisions the two application-facing Postgres roles that Row-Level Security
# depends on. Runs once, on first container init, with access to the same
# environment variables as the postgres container (see docker-compose.yml).
#
# installtec_migrator: owns the schema; Alembic connects as this role.
# installtec_app:      NOT the table owner, NOBYPASSRLS; the running app and
#                       Celery workers connect as this role for every request/task.
# RLS policies are meaningless against a connection that bypasses them (table
# owners bypass RLS by default), so this separation is a correctness
# requirement, not a hardening nicety. See docs/security-rls.md.
set -euo pipefail

: "${MIGRATOR_DB_USER:=installtec_migrator}"
: "${MIGRATOR_DB_PASSWORD:?MIGRATOR_DB_PASSWORD must be set}"
: "${APP_DB_USER:=installtec_app}"
: "${APP_DB_PASSWORD:?APP_DB_PASSWORD must be set}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${MIGRATOR_DB_USER}') THEN
            CREATE ROLE ${MIGRATOR_DB_USER} LOGIN PASSWORD '${MIGRATOR_DB_PASSWORD}' NOSUPERUSER NOBYPASSRLS CREATEDB;
        ELSE
            ALTER ROLE ${MIGRATOR_DB_USER} WITH LOGIN PASSWORD '${MIGRATOR_DB_PASSWORD}';
        END IF;

        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${APP_DB_USER}') THEN
            CREATE ROLE ${APP_DB_USER} LOGIN PASSWORD '${APP_DB_PASSWORD}' NOSUPERUSER NOBYPASSRLS NOCREATEDB;
        ELSE
            ALTER ROLE ${APP_DB_USER} WITH LOGIN PASSWORD '${APP_DB_PASSWORD}';
        END IF;
    END
    \$\$;

    -- Migrator owns the schema so it can run DDL; grant it ownership of the
    -- database itself so CREATE TABLE without an explicit OWNER TO defaults sanely.
    ALTER DATABASE ${POSTGRES_DB} OWNER TO ${MIGRATOR_DB_USER};
    GRANT ALL ON SCHEMA public TO ${MIGRATOR_DB_USER};
    GRANT USAGE ON SCHEMA public TO ${APP_DB_USER};

    -- Tables/sequences created by the migrator from here on are readable/writable
    -- by the app role by default, so each migration doesn't need its own GRANT.
    ALTER DEFAULT PRIVILEGES FOR ROLE ${MIGRATOR_DB_USER} IN SCHEMA public
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ${APP_DB_USER};
    ALTER DEFAULT PRIVILEGES FOR ROLE ${MIGRATOR_DB_USER} IN SCHEMA public
        GRANT USAGE, SELECT ON SEQUENCES TO ${APP_DB_USER};
    ALTER DEFAULT PRIVILEGES FOR ROLE ${MIGRATOR_DB_USER} IN SCHEMA public
        GRANT EXECUTE ON FUNCTIONS TO ${APP_DB_USER};
EOSQL

echo "installtec_migrator / installtec_app roles ready."
