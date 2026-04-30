#!/bin/bash
set -euo pipefail

# ============================================================
# Deploy Ideas Dev instance to Azure Container Apps
# Uses same infra (RG, ACR, environment) as prod,
# but a separate Container App on port 8000.
# ============================================================

RESOURCE_GROUP="fourth-ai-prod"
ACR_NAME="fourthzendeskmcp"
ENVIRONMENT_NAME="fourth-ai-env"
APP_NAME="fourth-zendesk-mcp-ideas-dev"
IMAGE_TAG="${1:-latest}"

# Zendesk credentials (set before running)
ZENDESK_SUBDOMAIN="${ZENDESK_SUBDOMAIN:-hotschedules}"
ZENDESK_EMAIL="${ZENDESK_EMAIL:-}"
ZENDESK_API_TOKEN="${ZENDESK_API_TOKEN:-}"

# Ideas cache: bundled file is the fallback; blob is the live source.
IDEAS_CACHE_FILE="${IDEAS_CACHE_FILE:-/app/ideas_latest.json}"
IDEAS_BLOB_ACCOUNT="${IDEAS_BLOB_ACCOUNT:-fourthzendeskideas}"
IDEAS_BLOB_CONTAINER="${IDEAS_BLOB_CONTAINER:-ideas-data}"
IDEAS_BLOB_NAME="${IDEAS_BLOB_NAME:-ideas_latest.json}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Copy ideas data into build context (lives one level up)
IDEAS_JSON="$(cd "$PROJECT_ROOT/.." && pwd)/ideas_latest.json"
if [ -f "$IDEAS_JSON" ]; then
  echo "=== Copying ideas_latest.json into build context ==="
  cp "$IDEAS_JSON" "$PROJECT_ROOT/ideas_latest.json"
else
  echo "WARNING: $IDEAS_JSON not found. Ideas tools will start without data."
  echo "         Run: python3 export_ideas.py --export-json ideas_latest.json"
fi

echo "=== Building Docker image (ideas-dev) in ACR ==="
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
echo "=== Checking if Ideas Dev Container App exists ==="
if az containerapp show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
  echo "Container App exists. Updating..."
  az containerapp update \
    --name "$APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --image "$ACR_LOGIN_SERVER/$APP_NAME:$IMAGE_TAG" \
    --set-env-vars \
      "DEPLOY_TIME=$(date +%s)" \
      "DEPLOY_TAG=$IMAGE_TAG" \
      "IDEAS_BLOB_ACCOUNT=$IDEAS_BLOB_ACCOUNT" \
      "IDEAS_BLOB_CONTAINER=$IDEAS_BLOB_CONTAINER" \
      "IDEAS_BLOB_NAME=$IDEAS_BLOB_NAME" \
    --output table
else
  echo "Container App does not exist. Creating..."

  ENV_VARS="MCP_TRANSPORT=http MCP_HTTP_PORT=8000 MCP_HTTP_HOST=0.0.0.0"
  ENV_VARS="$ENV_VARS IDEAS_CACHE_FILE=$IDEAS_CACHE_FILE"
  ENV_VARS="$ENV_VARS IDEAS_BLOB_ACCOUNT=$IDEAS_BLOB_ACCOUNT"
  ENV_VARS="$ENV_VARS IDEAS_BLOB_CONTAINER=$IDEAS_BLOB_CONTAINER"
  ENV_VARS="$ENV_VARS IDEAS_BLOB_NAME=$IDEAS_BLOB_NAME"

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
    --max-replicas 1 \
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
echo "=== Assigning system-assigned managed identity ==="
APP_PRINCIPAL_ID=$(az containerapp identity assign \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --system-assigned \
  --query "principalId" -o tsv)
echo "App principalId: $APP_PRINCIPAL_ID"

echo ""
echo "=== Granting Storage Blob Data Reader on $IDEAS_BLOB_ACCOUNT/$IDEAS_BLOB_CONTAINER ==="
STORAGE_ID=$(az storage account show \
  --name "$IDEAS_BLOB_ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" \
  --query id -o tsv)

az role assignment create \
  --assignee-object-id "$APP_PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Reader" \
  --scope "${STORAGE_ID}/blobServices/default/containers/${IDEAS_BLOB_CONTAINER}" \
  --output table 2>&1 | tee /tmp/ideas-dev-grant.log || \
  grep -q "RoleAssignmentExists" /tmp/ideas-dev-grant.log

echo ""
echo "=== Ideas Dev Deployment Complete ==="
FQDN=$(az containerapp show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" --query "properties.configuration.ingress.fqdn" -o tsv)
echo "App URL:       https://$FQDN"
echo "SSE endpoint:  https://$FQDN/sse"
echo "Health check:  https://$FQDN/health"
echo ""
echo "NOTE: This is a DEV instance with community ideas tools."
echo "      Prod (fourth-zendesk-mcp-server) is NOT affected."
