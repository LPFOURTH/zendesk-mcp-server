#!/bin/bash
set -euo pipefail

# ============================================================
# Update environment variables on the deployed Container App
# Usage: ./update-env.sh KEY=VALUE [KEY2=VALUE2 ...]
# ============================================================

RESOURCE_GROUP="fourth-zendesk-prod"
APP_NAME="fourth-zendesk-mcp-server"

if [ $# -eq 0 ]; then
  echo "Usage: $0 KEY=VALUE [KEY2=VALUE2 ...]"
  echo ""
  echo "Examples:"
  echo "  $0 ZENDESK_SUBDOMAIN=your-subdomain"
  echo "  $0 ZENDESK_RATE_LIMIT=100"
  echo "  $0 DISABLED_TOOLS=create_ticket,create_article"
  echo "  $0 TOOLS_PRESET=read_only"
  echo ""
  echo "Current env vars:"
  az containerapp show \
    --name "$APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query "properties.template.containers[0].env[].{name:name,value:value}" \
    --output table
  exit 0
fi

echo "=== Updating environment variables ==="
az containerapp update \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --set-env-vars "$@" \
  --output table

echo ""
echo "=== Updated. App will restart with new config. ==="
