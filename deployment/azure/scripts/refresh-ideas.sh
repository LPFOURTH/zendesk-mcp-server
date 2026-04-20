#!/bin/bash
set -euo pipefail

# ============================================================
# Refresh Ideas Data
# Runs inside the Container App Job container.
# Fetches latest ideas from Zendesk, rebuilds MCP server image.
# ============================================================

RESOURCE_GROUP="fourth-ai-prod"
ACR_NAME="fourthzendeskmcp"
APP_NAME="fourth-zendesk-mcp-ideas-dev"

echo "=== Step 1: Fetch ideas from Zendesk ==="
python3 /app/export_ideas.py --export-json /tmp/ideas_latest.json --db /tmp/ideas.db
echo "JSON size: $(du -h /tmp/ideas_latest.json | cut -f1)"

echo ""
echo "=== Step 2: Prepare MCP server build context ==="
cp /tmp/ideas_latest.json /app/mcp-server/ideas_latest.json

echo ""
echo "=== Step 3: Build new MCP server image ==="
az acr build \
  --registry "$ACR_NAME" \
  --image "$APP_NAME:latest" \
  --file /app/mcp-server/Dockerfile \
  /app/mcp-server

echo ""
echo "=== Step 4: Redeploy MCP server ==="
az containerapp update \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --image "${ACR_NAME}.azurecr.io/${APP_NAME}:latest" \
  --set-env-vars "DEPLOY_TIME=$(date +%s)" "DATA_REFRESHED=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --output table

echo ""
echo "=== Refresh complete ==="
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
