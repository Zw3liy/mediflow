\set ON_ERROR_STOP on
\getenv database_name POSTGRES_DB
\getenv migrator_user MEDIFLOW_MIGRATOR_USER
\getenv migrator_password MEDIFLOW_MIGRATOR_PASSWORD
\getenv app_user MEDIFLOW_APP_USER
\getenv app_password MEDIFLOW_APP_PASSWORD

-- Runs with the PostgreSQL bootstrap account. Never give this account to Django.
SELECT format(
    'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION',
    :'migrator_user',
    :'migrator_password'
)
WHERE NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = :'migrator_user'
) \gexec

SELECT format(
    'ALTER ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION',
    :'migrator_user',
    :'migrator_password'
) \gexec

SELECT format(
    'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION',
    :'app_user',
    :'app_password'
)
WHERE NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = :'app_user'
) \gexec

SELECT format(
    'ALTER ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION',
    :'app_user',
    :'app_password'
) \gexec

ALTER DATABASE :"database_name" OWNER TO :"migrator_user";
ALTER SCHEMA public OWNER TO :"migrator_user";

REVOKE ALL ON DATABASE :"database_name" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"database_name" TO :"migrator_user", :"app_user";

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO :"migrator_user";
GRANT USAGE ON SCHEMA public TO :"app_user";

-- Transfer existing Django objects so future migrations can alter them.
SELECT format('ALTER TABLE %I.%I OWNER TO %I',
    schemaname, tablename, :'migrator_user')
FROM pg_tables WHERE schemaname = 'public' \gexec

SELECT format('ALTER SEQUENCE %I.%I OWNER TO %I',
    sequence_schema, sequence_name, :'migrator_user')
FROM information_schema.sequences WHERE sequence_schema = 'public' \gexec

GRANT SELECT, INSERT, UPDATE, DELETE
    ON ALL TABLES IN SCHEMA public TO :"app_user";
GRANT USAGE, SELECT
    ON ALL SEQUENCES IN SCHEMA public TO :"app_user";
GRANT EXECUTE
    ON ALL FUNCTIONS IN SCHEMA public TO :"app_user";

ALTER DEFAULT PRIVILEGES FOR ROLE :"migrator_user" IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_user";
ALTER DEFAULT PRIVILEGES FOR ROLE :"migrator_user" IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO :"app_user";
ALTER DEFAULT PRIVILEGES FOR ROLE :"migrator_user" IN SCHEMA public
    GRANT EXECUTE ON FUNCTIONS TO :"app_user";
