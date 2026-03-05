#!/bin/bash
set -euo pipefail

# ============================================================
# Step 1: Create Azure infrastructure for Zendesk MCP Server
# Run this ONCE to provision all resources.
# ============================================================

RESOURCE_GROUP="fourth-zendesk-prod"
LOCATION="northeurope"
ACR_NAME="fourthzendeskzap"
ENVIRONMENT_NAME="fourth-zendesk-env"
APP_NAME="fourth-zendesk-mcp-server"
LOG_ANALYTICS_NAME="fourth-zendesk-env-logs"

echo "=== Creating Resource Group ==="
az group create \
  --name "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --output table

echo ""
echo "=== Creating Container Registry ==="
az acr create \
  --name "$ACR_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --sku Basic \
  --admin-enabled true \
  --output table

echo ""
echo "=== Creating Log Analytics Workspace ==="
az monitor log-analytics workspace create \
  --workspace-name "$LOG_ANALYTICS_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --retention-time 30 \
  --output table

LOG_ANALYTICS_ID=$(az monitor log-analytics workspace show \
  --workspace-name "$LOG_ANALYTICS_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query customerId -o tsv)

LOG_ANALYTICS_KEY=$(az monitor log-analytics workspace get-shared-keys \
  --workspace-name "$LOG_ANALYTICS_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query primarySharedKey -o tsv)

echo ""
echo "=== Creating Container Apps Environment ==="
az containerapp env create \
  --name "$ENVIRONMENT_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --logs-workspace-id "$LOG_ANALYTICS_ID" \
  --logs-workspace-key "$LOG_ANALYTICS_KEY" \
  --output table

echo ""
echo "=== Infrastructure Created ==="
echo "Resource Group:    $RESOURCE_GROUP"
echo "Container Registry: $ACR_NAME.azurecr.io"
echo "Environment:       $ENVIRONMENT_NAME"
echo ""
echo "Next: run 2-build-and-deploy.sh"
