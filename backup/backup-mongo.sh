#!/bin/bash
# Nightly mongodump loop - see docs/backlog.md item 2 / docs/deployment.md.
# Runs inside docker-compose.prod.yaml's `backup-mongo` service, the same
# mongo:8 image as the real database - mongodump is already present, no
# extra package install, and its entrypoint is overridden to run this
# script instead of starting a second mongod.
#
# Restore: `mongorestore --uri="$MONGODB_URL" --archive=<file> --gzip`
set -euo pipefail

RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
INTERVAL_SECONDS="${BACKUP_INTERVAL_SECONDS:-86400}"  # 24h default

while true; do
    timestamp=$(date -u +%Y%m%dT%H%M%SZ)
    archive="/backups/mongo-${timestamp}.archive.gz"
    echo "[backup-mongo] starting dump -> ${archive}"
    if mongodump --uri="${MONGODB_URL}" --archive="${archive}" --gzip; then
        echo "[backup-mongo] dump complete"
    else
        echo "[backup-mongo] dump FAILED" >&2
    fi

    # Rotation: drop anything older than RETENTION_DAYS - no separate
    # cleanup job needed, each run prunes for itself.
    find /backups -name 'mongo-*.archive.gz' -mtime "+${RETENTION_DAYS}" -delete

    echo "[backup-mongo] sleeping ${INTERVAL_SECONDS}s"
    sleep "${INTERVAL_SECONDS}"
done
