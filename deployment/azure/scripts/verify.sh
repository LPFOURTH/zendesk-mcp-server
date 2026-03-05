#!/bin/bash
set -euo pipefail

# ============================================================
# Verify deployment: health check + MCP initialize handshake
# ============================================================

RESOURCE_GROUP="fourth-zendesk-prod"
APP_NAME="fourth-zendesk-mcp-server"

FQDN=$(az containerapp show \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query "properties.configuration.ingress.fqdn" -o tsv 2>/dev/null || echo "")

if [ -z "$FQDN" ]; then
  echo "Container App not found. Using localhost:8000 for local testing."
  BASE_URL="http://localhost:8000"
else
  BASE_URL="https://$FQDN"
fi

echo "=== Verify: $BASE_URL ==="
echo ""

echo "--- Health Check ---"
HEALTH=$(curl -s -w "\nHTTP_STATUS:%{http_code}" "$BASE_URL/health" --max-time 10 2>&1)
HTTP_CODE=$(echo "$HEALTH" | grep "HTTP_STATUS" | cut -d: -f2)
BODY=$(echo "$HEALTH" | grep -v "HTTP_STATUS")

if [ "$HTTP_CODE" = "200" ]; then
  echo "PASS: Health check returned 200"
  echo "$BODY" | python3 -m json.tool 2>/dev/null || echo "$BODY"
else
  echo "FAIL: Health check returned $HTTP_CODE"
  echo "$BODY"
  exit 1
fi

echo ""
echo "--- SSE Connection Test ---"
SSE_RESPONSE=$(curl -s -N "$BASE_URL/sse" --max-time 3 2>&1 || true)
if echo "$SSE_RESPONSE" | grep -q "sessionId"; then
  SESSION_ID=$(echo "$SSE_RESPONSE" | grep "data:" | head -1 | sed 's/.*sessionId=//')
  echo "PASS: SSE endpoint returned session ID: ${SESSION_ID:0:36}..."
else
  echo "FAIL: SSE endpoint did not return a session ID"
  echo "$SSE_RESPONSE"
  exit 1
fi

echo ""
echo "--- Container App Status ---"
if [ "$BASE_URL" != "http://localhost:8000" ]; then
  az containerapp show \
    --name "$APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query "{name:name, status:properties.runningStatus, replicas:properties.template.scale, fqdn:properties.configuration.ingress.fqdn}" \
    --output table
fi

echo ""
echo "=== All checks passed ==="
