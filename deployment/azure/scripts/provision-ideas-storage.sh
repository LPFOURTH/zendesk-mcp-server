#!/bin/bash
set -euo pipefail

# ============================================================
# Provision Storage Account for Ideas blob-backed cache
# ============================================================

RESOURCE_GROUP="fourth-ai-prod"
LOCATION="northeurope"
ACCOUNT="${IDEAS_STORAGE_ACCOUNT:-fourthzendeskideas}"
CONTAINER="${IDEAS_STORAGE_CONTAINER:-ideas-data}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
SEED_JSON="$PROJECT_ROOT/ideas_latest.json"

echo "=== Step 1: Create storage account ==="
if az storage account show --name "$ACCOUNT" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
  echo "Storage account $ACCOUNT already exists; skipping create."
else
  az storage account create \
    --name "$ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --sku Standard_LRS \
    --kind StorageV2 \
    --min-tls-version TLS1_2 \
    --allow-blob-public-access false \
    --output table
fi

echo ""
echo "=== Step 2: Enable blob versioning ==="
az storage account blob-service-properties update \
  --account-name "$ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" \
  --enable-versioning true \
  --output table

echo ""
echo "=== Step 3: Create container ==="
az storage container create \
  --name "$CONTAINER" \
  --account-name "$ACCOUNT" \
  --auth-mode login \
  --public-access off \
  --output table || true   # idempotent

echo ""
echo "=== Step 4: Set 90-day version retention policy ==="
az storage account management-policy create \
  --account-name "$ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" \
  --policy "$(cat <<'JSON'
{
  "rules": [
    {
      "name": "ideas-version-retention",
      "enabled": true,
      "type": "Lifecycle",
      "definition": {
        "actions": {
          "version": {
            "delete": { "daysAfterCreationGreaterThan": 90 }
          }
        },
        "filters": { "blobTypes": ["blockBlob"] }
      }
    }
  ]
}
JSON
)" \
  --output table

echo ""
echo "=== Step 5: Seed initial blob from $SEED_JSON ==="
if [ -f "$SEED_JSON" ]; then
  az storage blob upload \
    --account-name "$ACCOUNT" \
    --container-name "$CONTAINER" \
    --name "ideas_latest.json" \
    --file "$SEED_JSON" \
    --auth-mode login \
    --overwrite \
    --output table
else
  echo "WARNING: seed file $SEED_JSON not found; skipping initial upload."
  echo "         The Ideas MCP will fall back to its bundled JSON until the next refresh job run."
fi

echo ""
echo "=== Provisioning complete ==="
echo "Account:   $ACCOUNT"
echo "Container: $CONTAINER"
echo "Blob URL:  https://${ACCOUNT}.blob.core.windows.net/${CONTAINER}/ideas_latest.json"
