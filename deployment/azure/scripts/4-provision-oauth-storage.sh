#!/bin/bash
set -euo pipefail

# ============================================================
# Step 4: Provision Key Vault + Cosmos DB for persistent OAuth storage
# Run ONCE per environment. Idempotent.
# Prereq: az login as a user with Owner on the resource group.
#
# Spec: docs/superpowers/specs/2026-04-28-persistent-oauth-storage-design.md
# ============================================================

RESOURCE_GROUP="${RESOURCE_GROUP:-fourth-ai-prod}"
LOCATION="${LOCATION:-northeurope}"
APP_NAME="${APP_NAME:-fourth-zendesk-mcp-server}"
KV_NAME="${KV_NAME:-fourth-mcp-kv}"
COSMOS_ACCOUNT="${COSMOS_ACCOUNT:-fourth-mcp-cosmos}"
COSMOS_DB="${COSMOS_DB:-mcp}"
COSMOS_CONTAINER="${COSMOS_CONTAINER:-oauth_state}"

echo "=== Step 1/6: Ensure Key Vault exists ==="
if az keyvault show --name "$KV_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
  echo "Key Vault $KV_NAME already exists."
else
  # soft-delete is on by default in modern Azure (no flag needed); purge
  # protection is opt-in.
  az keyvault create \
    --name "$KV_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --enable-rbac-authorization true \
    --enable-purge-protection true \
    --output table
fi

echo ""
echo "=== Step 2/6: Generate keys and write to Key Vault ==="

gen_key() {
  python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
}

# Only generate-and-set if the secret doesn't already exist (idempotent).
ensure_secret() {
  local name="$1"; local value="$2"
  if az keyvault secret show --vault-name "$KV_NAME" --name "$name" >/dev/null 2>&1; then
    echo "Secret $name already exists — leaving untouched."
  else
    az keyvault secret set --vault-name "$KV_NAME" --name "$name" --value "$value" --output none
    echo "Secret $name created."
  fi
}

ensure_secret "mcp-jwt-signing-key" "$(gen_key)"
ensure_secret "mcp-storage-encryption-key" "$(gen_key)"

echo ""
echo "=== Step 3/6: Ensure Cosmos DB account exists (serverless) ==="
if az cosmosdb show --name "$COSMOS_ACCOUNT" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
  echo "Cosmos account $COSMOS_ACCOUNT already exists."
else
  az cosmosdb create \
    --name "$COSMOS_ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    --locations regionName="$LOCATION" failoverPriority=0 isZoneRedundant=False \
    --capabilities EnableServerless \
    --default-consistency-level "Session" \
    --output table
fi

COSMOS_ENDPOINT=$(az cosmosdb show --name "$COSMOS_ACCOUNT" --resource-group "$RESOURCE_GROUP" --query documentEndpoint -o tsv)
ensure_secret "cosmos-endpoint" "$COSMOS_ENDPOINT"

echo ""
echo "=== Step 4/6: Ensure Cosmos database and container ==="
if az cosmosdb sql database show \
    --account-name "$COSMOS_ACCOUNT" --resource-group "$RESOURCE_GROUP" \
    --name "$COSMOS_DB" >/dev/null 2>&1; then
  echo "Database $COSMOS_DB already exists."
else
  az cosmosdb sql database create \
    --account-name "$COSMOS_ACCOUNT" --resource-group "$RESOURCE_GROUP" \
    --name "$COSMOS_DB" --output table
fi

if az cosmosdb sql container show \
    --account-name "$COSMOS_ACCOUNT" --resource-group "$RESOURCE_GROUP" \
    --database-name "$COSMOS_DB" --name "$COSMOS_CONTAINER" >/dev/null 2>&1; then
  echo "Container $COSMOS_CONTAINER already exists."
else
  # indexing policy: disable all indexes (we only do point reads)
  cat > /tmp/cosmos-indexing-policy.json <<'JSON'
{
  "indexingMode": "consistent",
  "automatic": true,
  "includedPaths": [],
  "excludedPaths": [{"path": "/*"}]
}
JSON
  az cosmosdb sql container create \
    --account-name "$COSMOS_ACCOUNT" --resource-group "$RESOURCE_GROUP" \
    --database-name "$COSMOS_DB" --name "$COSMOS_CONTAINER" \
    --partition-key-path "/pk" \
    --ttl -1 \
    --idx @/tmp/cosmos-indexing-policy.json \
    --output table
  rm -f /tmp/cosmos-indexing-policy.json
fi

echo ""
echo "=== Step 5/6: Ensure system-assigned managed identity on Container App ==="
if az containerapp show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
  PRINCIPAL_ID=$(az containerapp identity show \
    --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" \
    --query principalId -o tsv 2>/dev/null || true)
  if [ -z "${PRINCIPAL_ID:-}" ] || [ "$PRINCIPAL_ID" = "null" ]; then
    echo "Assigning system-assigned identity..."
    PRINCIPAL_ID=$(az containerapp identity assign \
      --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" \
      --system-assigned --query principalId -o tsv)
  else
    echo "System-assigned identity already exists: $PRINCIPAL_ID"
  fi
else
  echo "Container App $APP_NAME does not exist yet."
  echo "Skipping role assignments — re-run this script after first deploy."
  exit 0
fi

echo ""
echo "=== Step 6/6: Grant role assignments ==="

# Key Vault Secrets User on the vault
KV_SCOPE=$(az keyvault show --name "$KV_NAME" --resource-group "$RESOURCE_GROUP" --query id -o tsv)
if az role assignment list --assignee "$PRINCIPAL_ID" --scope "$KV_SCOPE" --query "[?roleDefinitionName=='Key Vault Secrets User'] | length(@)" -o tsv 2>/dev/null | grep -q "^[1-9]"; then
  echo "KV role already assigned."
else
  az role assignment create \
    --assignee-object-id "$PRINCIPAL_ID" \
    --assignee-principal-type ServicePrincipal \
    --role "Key Vault Secrets User" \
    --scope "$KV_SCOPE" \
    --output none
  echo "Granted Key Vault Secrets User on $KV_NAME."
fi

# Cosmos DB Built-in Data Contributor (data plane)
# Role definition ID 00000000-0000-0000-0000-000000000002 is well-known.
COSMOS_SCOPE=$(az cosmosdb show --name "$COSMOS_ACCOUNT" --resource-group "$RESOURCE_GROUP" --query id -o tsv)
if az cosmosdb sql role assignment list \
    --account-name "$COSMOS_ACCOUNT" --resource-group "$RESOURCE_GROUP" \
    --query "[?principalId=='$PRINCIPAL_ID' && roleDefinitionId | contains(@, '00000000-0000-0000-0000-000000000002')] | length(@)" \
    -o tsv 2>/dev/null | grep -q "^[1-9]"; then
  echo "Cosmos data role already assigned."
else
  az cosmosdb sql role assignment create \
    --account-name "$COSMOS_ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    --scope "$COSMOS_SCOPE" \
    --principal-id "$PRINCIPAL_ID" \
    --role-definition-id "00000000-0000-0000-0000-000000000002" \
    --output none
  echo "Granted Cosmos DB Built-in Data Contributor on $COSMOS_ACCOUNT."
fi

echo ""
echo "=== Done ==="
echo "Cosmos endpoint: $COSMOS_ENDPOINT"
echo "Key Vault:       https://$KV_NAME.vault.azure.net/"
echo ""
echo "Secrets in $KV_NAME:"
az keyvault secret list --vault-name "$KV_NAME" --query "[].name" -o tsv
