#!/bin/bash
# ══════════════════════════════════════════════════════════════════
# backup.sh — Snapshot the entire WINECO project
#
# Creates a timestamped zip in ../wineco_backups/ containing:
#   - All source code and configuration
#   - All InfluxDB data (./data/influxdb)
#   - All Grafana data + dashboards (./data/grafana)
#
# Restore by unzipping anywhere and running `docker compose up -d`.
# ══════════════════════════════════════════════════════════════════

set -e
umask 077

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_NAME="$(basename "$PROJECT_DIR")"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="$(dirname "$PROJECT_DIR")/wineco_backups"
ARCHIVE="$BACKUP_DIR/${PROJECT_NAME}_${TIMESTAMP}.zip"

mkdir -p "$BACKUP_DIR"

echo "📦 Backing up to: $ARCHIVE"
echo "   (this includes ./data — your InfluxDB and Grafana state)"

cd "$(dirname "$PROJECT_DIR")"

# Exclude repository history and local credentials; runtime data may still be sensitive.
zip -r "$ARCHIVE" "$PROJECT_NAME" \
    -x "$PROJECT_NAME/**/__pycache__/*" \
    -x "$PROJECT_NAME/**/.DS_Store" \
    -x "$PROJECT_NAME/**/*.pyc" \
    -x "$PROJECT_NAME/.git/*" \
    -x "$PROJECT_NAME/cloud_rasp/.env" \
    -x "$PROJECT_NAME/.env"

SIZE="$(du -h "$ARCHIVE" | cut -f1)"
echo "✅ Backup complete — $SIZE"
echo "Private runtime backup: do not publish. Restore credentials separately."
echo ""
echo "To restore on another machine:"
echo "  1. unzip $(basename "$ARCHIVE")"
echo "  2. cd $PROJECT_NAME"
echo "  3. docker compose up -d --build"
