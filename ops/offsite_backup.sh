#!/bin/sh
set -eu
umask 077
: "${RESTIC_REPOSITORY:?Set an offsite repository}"
: "${RESTIC_PASSWORD:?Set a separately stored encryption password}"
# Repository creation is an explicit one-time operator action. Never auto-init on failure.
while true; do
    if restic backup /backups --exclude '/backups/.*' --tag mediflow; then
        date -u +%Y%m%dT%H%M%SZ > /backups/.offsite-success
        printf 'Encrypted offsite backup completed.\n'
    else
        printf 'Encrypted offsite backup failed.\n' >&2
    fi
    sleep 86400
done
