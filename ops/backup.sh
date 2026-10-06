#!/bin/sh
set -eu
umask 077

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
case "${BACKUP_RETENTION_DAYS:-30}" in
    ''|*[!0-9]*) printf 'Invalid backup retention.\n' >&2; exit 1 ;;
esac
backup_dir="/backups/$timestamp"
temporary_dir="/backups/.${timestamp}.tmp"

cleanup() {
    rm -rf -- "$temporary_dir"
}
trap cleanup EXIT INT TERM

mkdir -p "$temporary_dir"

export PGPASSWORD="${POSTGRES_PASSWORD}"

pg_dump \
    --host="${POSTGRES_HOST:-db}" \
    --port="${POSTGRES_PORT:-5432}" \
    --username="${POSTGRES_USER}" \
    --dbname="${POSTGRES_DB}" \
    --format=custom \
    --no-owner \
    --no-privileges \
    --file="$temporary_dir/database.dump"

tar \
    -C /private_documents \
    -czf "$temporary_dir/private_documents.tar.gz" \
    .

(
    cd "$temporary_dir"
    sha256sum \
        database.dump \
        private_documents.tar.gz \
        > SHA256SUMS
)

chmod 600 \
    "$temporary_dir/database.dump" \
    "$temporary_dir/private_documents.tar.gz" \
    "$temporary_dir/SHA256SUMS"

mv -- "$temporary_dir" "$backup_dir"
trap - EXIT INT TERM

retention_days="${BACKUP_RETENTION_DAYS:-30}"

find /backups \
    -mindepth 1 \
    -maxdepth 1 \
    -type d \
    -name '20??????T??????Z' \
    -mtime "+${retention_days}" \
    -exec rm -rf -- {} +

printf 'Backup created: %s\n' "$backup_dir"