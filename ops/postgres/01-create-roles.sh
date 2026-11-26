#!/bin/sh
set -eu

: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_USER:?POSTGRES_USER must be the bootstrap account}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
: "${MEDIFLOW_MIGRATOR_USER:?MEDIFLOW_MIGRATOR_USER is required}"
: "${MEDIFLOW_MIGRATOR_PASSWORD:?MEDIFLOW_MIGRATOR_PASSWORD is required}"
: "${MEDIFLOW_APP_USER:?MEDIFLOW_APP_USER is required}"
: "${MEDIFLOW_APP_PASSWORD:?MEDIFLOW_APP_PASSWORD is required}"

if [ "$POSTGRES_USER" = "$MEDIFLOW_MIGRATOR_USER" ] ||
   [ "$POSTGRES_USER" = "$MEDIFLOW_APP_USER" ] ||
   [ "$MEDIFLOW_MIGRATOR_USER" = "$MEDIFLOW_APP_USER" ]; then
    printf 'Bootstrap, migration and application role names must all differ.\n' >&2
    exit 1
fi

if [ "$POSTGRES_PASSWORD" = "$MEDIFLOW_MIGRATOR_PASSWORD" ] ||
   [ "$POSTGRES_PASSWORD" = "$MEDIFLOW_APP_PASSWORD" ] ||
   [ "$MEDIFLOW_MIGRATOR_PASSWORD" = "$MEDIFLOW_APP_PASSWORD" ]; then
    printf 'Bootstrap, migration and application passwords must all differ.\n' >&2
    exit 1
fi

export PGPASSWORD="$POSTGRES_PASSWORD"

psql \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    --set=ON_ERROR_STOP=1 \
    --set=database_name="$POSTGRES_DB" \
    --set=migrator_user="$MEDIFLOW_MIGRATOR_USER" \
    --set=migrator_password="$MEDIFLOW_MIGRATOR_PASSWORD" \
    --set=app_user="$MEDIFLOW_APP_USER" \
    --set=app_password="$MEDIFLOW_APP_PASSWORD" \
    --file=/opt/tos-postgres/00-create-roles.sql
