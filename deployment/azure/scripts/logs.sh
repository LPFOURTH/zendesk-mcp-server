#!/bin/bash
set -euo pipefail

# ============================================================
# View Container App logs (live tail or recent)
# ============================================================

RESOURCE_GROUP="fourth-zendesk-prod"
APP_NAME="fourth-zendesk-mcp-server"

MODE="${1:-follow}"

case "$MODE" in
  follow|tail|live)
    echo "=== Tailing live logs (Ctrl+C to stop) ==="
    az containerapp logs show \
      --name "$APP_NAME" \
      --resource-group "$RESOURCE_GROUP" \
      --follow \
      --tail 50
    ;;
  recent|last)
    echo "=== Last 100 log entries ==="
    az containerapp logs show \
      --name "$APP_NAME" \
      --resource-group "$RESOURCE_GROUP" \
      --tail 100
    ;;
  *)
    echo "Usage: $0 [follow|recent]"
    echo "  follow  - Live tail (default)"
    echo "  recent  - Last 100 entries"
    ;;
esac
