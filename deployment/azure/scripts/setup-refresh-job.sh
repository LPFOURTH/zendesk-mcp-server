#!/bin/bash
set -euo pipefail

# ============================================================
# One-time setup: Create scheduled Container App Job
# Runs every Monday at 6am UTC to refresh Ideas data.
# ============================================================

RESOURCE_GROUP="fourth-ai-prod"
ACR_NAME="fourthzendeskmcp"
ENVIRONMENT_NAME="fourth-ai-env"
JOB_NAME="fourth-ideas-refresh"
IMAGE_TAG="${1:-latest}"

# Zendesk credentials (required)
ZENDESK_SUBDOMAIN="${ZENDESK_SUBDOMAIN:-hotschedules}"
ZENDESK_EMAIL="${ZENDESK_EMAIL:?Set ZENDESK_EMAIL}"
ZENDESK_API_TOKEN="${ZENDESK_API_TOKEN:?Set ZENDESK_API_TOKEN}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"

echo "=== Building refresh job image ==="
echo "Project root: $PROJECT_ROOT"

# Build from project root (needs export_ideas.py + zendesk-mcp-server/)
az acr build \
  --registry "$ACR_NAME" \
  --image "$JOB_NAME:$IMAGE_TAG" \
  --file "$PROJECT_ROOT/zendesk-mcp-server/deployment/azure/Dockerfile.refresh" \
  "$PROJECT_ROOT"

ACR_LOGIN_SERVER=$(az acr show --name "$ACR_NAME" --query loginServer -o tsv)
ACR_USERNAME=$(az acr credential show --name "$ACR_NAME" --query username -o tsv)
ACR_PASSWORD=$(az acr credential show --name "$ACR_NAME" --query "passwords[0].value" -o tsv)

echo ""
echo "=== Creating scheduled Container App Job ==="

if az containerapp job show --name "$JOB_NAME" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
  echo "Job already exists. Updating image..."
  az containerapp job update \
    --name "$JOB_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --image "$ACR_LOGIN_SERVER/$JOB_NAME:$IMAGE_TAG" \
    --output table
else
  az containerapp job create \
    --name "$JOB_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --environment "$ENVIRONMENT_NAME" \
    --image "$ACR_LOGIN_SERVER/$JOB_NAME:$IMAGE_TAG" \
    --registry-server "$ACR_LOGIN_SERVER" \
    --registry-username "$ACR_USERNAME" \
    --registry-password "$ACR_PASSWORD" \
    --trigger-type "Schedule" \
    --cron-expression "0 6 * * 1" \
    --replica-timeout 1800 \
    --replica-retry-limit 1 \
    --replica-completion-count 1 \
    --parallelism 1 \
    --cpu 1.0 \
    --memory 2Gi \
    --env-vars \
      "ZENDESK_SUBDOMAIN=$ZENDESK_SUBDOMAIN" \
      "ZENDESK_EMAIL=$ZENDESK_EMAIL" \
      "ZENDESK_API_TOKEN=secretref:zendesk-api-token" \
    --secrets \
      "zendesk-api-token=$ZENDESK_API_TOKEN" \
      "registry-password=$ACR_PASSWORD" \
    --output table
fi

echo ""
echo "=== Setup Complete ==="
echo "Job name:     $JOB_NAME"
echo "Schedule:     Every Monday at 6am UTC"
echo "Timeout:      30 minutes"
echo ""
echo "Manual trigger:"
echo "  az containerapp job start --name $JOB_NAME --resource-group $RESOURCE_GROUP"
echo ""
echo "Check executions:"
echo "  az containerapp job execution list --name $JOB_NAME --resource-group $RESOURCE_GROUP -o table"
