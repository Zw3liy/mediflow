#!/bin/sh
set -eu

interval="${BACKUP_INTERVAL_SECONDS:-86400}"

case "$interval" in
    ''|*[!0-9]*|0)
        printf 'BACKUP_INTERVAL_SECONDS must be a positive integer.\n' >&2
        exit 1
        ;;
esac

while true; do
    /ops/backup.sh
    printf 'Next backup in %s seconds.\n' "$interval"
    sleep "$interval"
done
