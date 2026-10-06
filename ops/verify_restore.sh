#!/bin/sh
set -eu

requested_backup="${BACKUP_ID:-latest}"

if [ "$requested_backup" = "latest" ]; then
    backup_dir="$(
        find /backups \
            -mindepth 1 \
            -maxdepth 1 \
            -type d \
            -name '20??????T??????Z' |
        sort |
        tail -n 1
    )"
else
    case "$requested_backup" in
        *[!0-9TZ]*|"")
            printf 'Invalid BACKUP_ID.\n' >&2
            exit 1
            ;;
    esac

    backup_dir="/backups/$requested_backup"
fi

if [ -z "${backup_dir:-}" ] || [ ! -d "$backup_dir" ]; then
    printf 'Backup directory was not found.\n' >&2
    exit 1
fi

required_files="
database.dump
private_documents.tar.gz
SHA256SUMS
"

for required_file in $required_files; do
    if [ ! -f "$backup_dir/$required_file" ]; then
        printf 'Missing backup file: %s\n' "$required_file" >&2
        exit 1
    fi
done

(
    cd "$backup_dir"
    sha256sum -c SHA256SUMS
)

tar -tzf "$backup_dir/private_documents.tar.gz" >/dev/null

export PGPASSWORD="${POSTGRES_PASSWORD}"

temporary_database="mediflow_restore_verify_$$"

cleanup() {
    dropdb \
        --host="${POSTGRES_HOST:-db}" \
        --port="${POSTGRES_PORT:-5432}" \
        --username="${POSTGRES_USER}" \
        --if-exists \
        "$temporary_database" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

createdb \
    --host="${POSTGRES_HOST:-db}" \
    --port="${POSTGRES_PORT:-5432}" \
    --username="${POSTGRES_USER}" \
    "$temporary_database"

pg_restore \
    --exit-on-error \
    --host="${POSTGRES_HOST:-db}" \
    --port="${POSTGRES_PORT:-5432}" \
    --username="${POSTGRES_USER}" \
    --dbname="$temporary_database" \
    --no-owner \
    --no-privileges \
    "$backup_dir/database.dump"

migration_count="$(
    psql \
        --host="${POSTGRES_HOST:-db}" \
        --port="${POSTGRES_PORT:-5432}" \
        --username="${POSTGRES_USER}" \
        --dbname="$temporary_database" \
        --tuples-only \
        --no-align \
        --command='SELECT COUNT(*) FROM django_migrations;'
)"

case "$migration_count" in
    ''|*[!0-9]*)
        printf 'Restored database verification failed.\n' >&2
        exit 1
        ;;
esac

printf 'Restore verified: %s (%s migrations)\n' \
    "$backup_dir" \
    "$migration_count"