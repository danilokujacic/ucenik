#!/bin/sh
# Nightly MinIO object mirror loop - see docs/backlog.md item 2 /
# docs/deployment.md. Runs inside docker-compose.prod.yaml's
# `backup-minio` service (minio/mc image).
#
# Deliberately simple, not incremental: each run mirrors the bucket's
# *current* full state into a fresh timestamped directory (`mc mirror`
# makes dest match source, it doesn't diff against yesterday's snapshot).
# Correct and easy to reason about; revisit if the bucket gets large enough
# that a full copy every run becomes a real storage/time cost.
#
# Restore: `mc mirror /backups/<timestamp> backup-source/$S3_BUCKET`
# (with the alias set up the same way this script sets it up below).
set -eu

RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
INTERVAL_SECONDS="${BACKUP_INTERVAL_SECONDS:-86400}"

mc alias set backup-source "${S3_ENDPOINT_URL}" "${S3_ACCESS_KEY}" "${S3_SECRET_KEY}"

while true; do
    timestamp=$(date -u +%Y%m%dT%H%M%SZ)
    dest="/backups/${timestamp}"
    echo "[backup-minio] mirroring ${S3_BUCKET} -> ${dest}"
    if mc mirror --quiet "backup-source/${S3_BUCKET}" "${dest}"; then
        echo "[backup-minio] mirror complete"
    else
        echo "[backup-minio] mirror FAILED"
    fi

    # Rotation: drop snapshot directories older than RETENTION_DAYS.
    # Not `find -mtime` (minio/mc's minimal image doesn't have `find` at
    # all - confirmed by actually running it, not assumed) and deliberately
    # not `mc find --older-than` either, despite mc being the one binary
    # this image guarantees: tested against this exact image and it
    # matched the /backups mount root itself as a false positive and
    # produced other surprising results against local filesystem targets -
    # mc find's local-path semantics aren't trustworthy enough for
    # deletion. Plain `stat`+`date` arithmetic instead - both confirmed
    # present, unambiguous, verified against this exact image.
    now=$(date +%s)
    retention_seconds=$((RETENTION_DAYS * 86400))
    for dir in /backups/*/; do
        [ -d "$dir" ] || continue
        mtime=$(stat -c %Y "$dir")
        age=$((now - mtime))
        if [ "$age" -gt "$retention_seconds" ]; then
            echo "[backup-minio] pruning ${dir} (age ${age}s > ${retention_seconds}s)"
            rm -rf "$dir"
        fi
    done

    echo "[backup-minio] sleeping ${INTERVAL_SECONDS}s"
    sleep "${INTERVAL_SECONDS}"
done
