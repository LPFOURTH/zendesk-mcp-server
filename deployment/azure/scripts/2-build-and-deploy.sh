#!/bin/bash
set -euo pipefail

# ============================================================
# Step 2: Build Docker image and deploy to Azure Container Apps
# Run this to deploy a new version.
# ============================================================

RESOURCE_GROUP="fourth-ai-prod"
ACR_NAME="fourthzendeskmcp"
ENVIRONMENT_NAME="fourth-ai-env"
APP_NAME="fourth-zendesk-mcp-server"
IMAGE_TAG="${1:-latest}"

# Zendesk credentials (pass as args or set before running)
ZENDESK_SUBDOMAIN="${ZENDESK_SUBDOMAIN:-}"
ZENDESK_EMAIL="${ZENDESK_EMAIL:-}"
ZENDESK_API_TOKEN="${ZENDESK_API_TOKEN:-}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

echo "=== Building Docker image in ACR ==="
echo "Project root: $PROJECT_ROOT"
echo "Image tag: $IMAGE_TAG"
az acr build \
  --registry "$ACR_NAME" \
  --image "$APP_NAME:$IMAGE_TAG" \
  --file "$PROJECT_ROOT/Dockerfile" \
  "$PROJECT_ROOT"

ACR_LOGIN_SERVER=$(az acr show --name "$ACR_NAME" --query loginServer -o tsv)
ACR_USERNAME=$(az acr credential show --name "$ACR_NAME" --query username -o tsv)
ACR_PASSWORD=$(az acr credential show --name "$ACR_NAME" --query "passwords[0].value" -o tsv)

echo ""
echo "=== Checking if Container App exists ==="
if az containerapp show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
  echo "Container App exists. Updating..."
  az containerapp update \
    --name "$APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --image "$ACR_LOGIN_SERVER/$APP_NAME:$IMAGE_TAG" \
    --set-env-vars \
      "DEPLOY_TIME=$(date +%s)" \
      "DEPLOY_TAG=$IMAGE_TAG" \
    --output table
else
  echo "Container App does not exist. Creating..."

  ENV_VARS="MCP_TRANSPORT=http MCP_HTTP_PORT=8000 MCP_HTTP_HOST=0.0.0.0"

  if [ -n "$ZENDESK_SUBDOMAIN" ]; then
    ENV_VARS="$ENV_VARS ZENDESK_SUBDOMAIN=$ZENDESK_SUBDOMAIN"
  fi
  if [ -n "$ZENDESK_EMAIL" ]; then
    ENV_VARS="$ENV_VARS ZENDESK_EMAIL=$ZENDESK_EMAIL"
  fi
  if [ -n "$ZENDESK_API_TOKEN" ]; then
    ENV_VARS="$ENV_VARS ZENDESK_API_TOKEN=secretref:zendesk-api-token"
  fi

  SECRET_ARGS=""
  if [ -n "$ZENDESK_API_TOKEN" ]; then
    SECRET_ARGS="--secrets zendesk-api-token=$ZENDESK_API_TOKEN registry-password=$ACR_PASSWORD"
  else
    SECRET_ARGS="--secrets registry-password=$ACR_PASSWORD"
  fi

  az containerapp create \
    --name "$APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --environment "$ENVIRONMENT_NAME" \
    --image "$ACR_LOGIN_SERVER/$APP_NAME:$IMAGE_TAG" \
    --registry-server "$ACR_LOGIN_SERVER" \
    --registry-username "$ACR_USERNAME" \
    --registry-password "$ACR_PASSWORD" \
    --target-port 8000 \
    --ingress external \
    --transport http \
    --min-replicas 1 \
    --max-replicas 10 \
    --cpu 0.5 \
    --memory 1Gi \
    --env-vars $ENV_VARS \
    $SECRET_ARGS \
    --output table
fi

echo ""
echo "=== Enabling Sticky Sessions (required for SSE) ==="
az containerapp ingress sticky-sessions set \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --affinity sticky \
  --output table 2>/dev/null || echo "(sticky sessions may already be set)"

echo ""
echo "=== Deployment Complete ==="
FQDN=$(az containerapp show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" --query "properties.configuration.ingress.fqdn" -o tsv)
echo "App URL:       https://$FQDN"
echo "SSE endpoint:  https://$FQDN/sse"
echo "Health check:  https://$FQDN/health"
echo ""
echo "Next: run 3-setup-custom-domain.sh (optional)"
