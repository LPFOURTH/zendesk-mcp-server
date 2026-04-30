#!/bin/bash
set -euo pipefail

# ============================================================
# Refresh Ideas Data
# Runs inside the fourth-ideas-refresh Container App Job.
# Fetches ideas from Zendesk → uploads JSON to blob.
# ============================================================

ACCOUNT="${IDEAS_STORAGE_ACCOUNT:-fourthzendeskideas}"
CONTAINER="${IDEAS_STORAGE_CONTAINER:-ideas-data}"
BLOB="${IDEAS_BLOB_NAME:-ideas_latest.json}"

echo "=== Step 1: Authenticate via managed identity ==="
az login --identity --output none

echo ""
echo "=== Step 2: Fetch ideas from Zendesk ==="
python3 /app/export_ideas.py --export-json /tmp/ideas_latest.json --db /tmp/ideas.db
echo "JSON size: $(du -h /tmp/ideas_latest.json | cut -f1)"

echo ""
echo "=== Step 3: Upload to blob ==="
az storage blob upload \
  --account-name "$ACCOUNT" \
  --container-name "$CONTAINER" \
  --name "$BLOB" \
  --file /tmp/ideas_latest.json \
  --auth-mode login \
  --overwrite \
  --output none

echo ""
echo "=== Refresh complete ==="
echo "Blob:      https://${ACCOUNT}.blob.core.windows.net/${CONTAINER}/${BLOB}"
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
