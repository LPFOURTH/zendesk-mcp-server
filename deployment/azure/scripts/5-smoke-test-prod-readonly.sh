#!/usr/bin/env bash
# 5-smoke-test-prod-readonly.sh
# Post-deploy smoke checks for v3.8.0 (Cosmos OAuth state + /mcp/dev → PROD Zendesk).
# Read-only: only `show`, `list`, `query`, `logs show`, and HTTP GETs.
# Continues past failures so it can report every check, then exits non-zero if any failed.
# See: docs/superpowers/specs/2026-04-29-prod-zendesk-readonly-test-design.md (Smoke tests).

set -uo pipefail

# --- Defaults (env overridable) -------------------------------------------------
APP_NAME="${APP_NAME:-fourth-zendesk-mcp-server}"
RESOURCE_GROUP="${RESOURCE_GROUP:-fourth-ai-prod}"
COSMOS_ACCOUNT="${COSMOS_ACCOUNT:-cosmos-db-ai-enablement}"
COSMOS_DB="${COSMOS_DB:-mcp}"
COSMOS_CONTAINER="${COSMOS_CONTAINER:-oauth_state}"
PUBLIC_URL="${PUBLIC_URL:-https://zendesk-mcp.fourth.com}"
EXPECTED_TAG="${EXPECTED_TAG:-v3.8.0}"

PASSED=0
FAILED=0
WARNINGS=0

pass() {
    echo "[OK]   $1"
    PASSED=$((PASSED + 1))
}

fail() {
    echo "[FAIL] $1: $2"
    FAILED=$((FAILED + 1))
}

warn() {
    echo "[WARN] $1: $2"
    WARNINGS=$((WARNINGS + 1))
}

# --- Prereq checks --------------------------------------------------------------
if ! command -v curl >/dev/null 2>&1; then
    echo "[FATAL] curl not found on PATH"
    exit 2
fi
if ! command -v az >/dev/null 2>&1; then
    echo "[FATAL] az CLI not found on PATH"
    exit 2
fi

echo "=== Smoke test: $APP_NAME (RG=$RESOURCE_GROUP, expected image tag=$EXPECTED_TAG) ==="
echo ""

# --- 1. Health endpoint ---------------------------------------------------------
HEALTH_BODY=$(curl -sf --max-time 10 "$PUBLIC_URL/health" 2>&1) || HEALTH_BODY="__CURL_ERROR__"
if [ "$HEALTH_BODY" = "__CURL_ERROR__" ]; then
    fail "health endpoint" "curl to $PUBLIC_URL/health failed"
elif echo "$HEALTH_BODY" | grep -q '"status"[[:space:]]*:[[:space:]]*"healthy"'; then
    pass "health endpoint reports healthy"
else
    fail "health endpoint" "response did not contain '\"status\": \"healthy\"' (body: $(echo "$HEALTH_BODY" | head -c 200))"
fi

# --- 2. OAuth protected-resource metadata ---------------------------------------
META_BODY=$(curl -sf --max-time 10 "$PUBLIC_URL/.well-known/oauth-protected-resource" 2>&1) || META_BODY="__CURL_ERROR__"
if [ "$META_BODY" = "__CURL_ERROR__" ]; then
    fail "oauth-protected-resource metadata" "curl failed (non-200 or network error)"
elif [ -z "$META_BODY" ]; then
    fail "oauth-protected-resource metadata" "200 OK but empty body"
else
    pass "oauth-protected-resource metadata returns 200 with body"
fi

# --- 3. Container App active revision uses expected image tag -------------------
REV_OUT=$(az containerapp revision list \
    --name "$APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query "[?properties.active].{name:name, image:properties.template.containers[0].image}" \
    -o tsv 2>&1) || REV_OUT="__AZ_ERROR__"
if [ "$REV_OUT" = "__AZ_ERROR__" ] || [ -z "$REV_OUT" ]; then
    fail "active revision lookup" "az containerapp revision list returned no active revision (output: $REV_OUT)"
elif echo "$REV_OUT" | grep -q "$EXPECTED_TAG"; then
    pass "active revision image tag contains $EXPECTED_TAG"
    echo "       $REV_OUT"
else
    fail "active revision image tag" "expected to contain '$EXPECTED_TAG', got: $REV_OUT"
fi

# --- 4. Mode log lines (last 200) -----------------------------------------------
LOGS_OUT=$(az containerapp logs show \
    --name "$APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --tail 200 2>&1) || LOGS_OUT="__AZ_ERROR__"

if [ "$LOGS_OUT" = "__AZ_ERROR__" ]; then
    fail "log inspection" "az containerapp logs show failed"
else
    if echo "$LOGS_OUT" | grep -q "OAuth state: Cosmos DB"; then
        pass "log line: 'OAuth state: Cosmos DB' present"
    else
        fail "log line 'OAuth state: Cosmos DB'" "not found in last 200 log lines"
    fi

    if echo "$LOGS_OUT" | grep -q "Dev server: Zendesk OAuth (PROD)"; then
        pass "log line: 'Dev server: Zendesk OAuth (PROD)' present"
    else
        fail "log line 'Dev server: Zendesk OAuth (PROD)'" "not found in last 200 log lines"
    fi
fi

# --- 5. Cosmos collection counts (informational) --------------------------------
echo ""
echo "--- Cosmos collection counts (informational) ---"
COSMOS_OUT=$(az cosmosdb sql query \
    --account-name "$COSMOS_ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    --database-name "$COSMOS_DB" \
    --container-name "$COSMOS_CONTAINER" \
    --query-text "SELECT c.collection, COUNT(1) AS n FROM c GROUP BY c.collection" \
    -o table 2>&1) || COSMOS_OUT="__AZ_ERROR__"

if [ "$COSMOS_OUT" = "__AZ_ERROR__" ]; then
    warn "cosmos query" "az cosmosdb sql query failed (this can be a permissions/data-plane issue, not necessarily a deploy failure)"
else
    echo "$COSMOS_OUT"
    if echo "$COSMOS_OUT" | grep -q "token_storage"; then
        pass "cosmos contains token_storage rows (an OAuth flow has run)"
    else
        warn "cosmos token_storage" "no token_storage rows yet — expected before any user has signed in"
    fi
    if echo "$COSMOS_OUT" | grep -q "jti_storage"; then
        pass "cosmos contains jti_storage rows"
    else
        warn "cosmos jti_storage" "no jti_storage rows yet — expected before any user has signed in"
    fi
fi

# --- Summary --------------------------------------------------------------------
echo ""
echo "=== Summary: $PASSED passed, $FAILED failed (warnings: $WARNINGS) ==="

if [ "$FAILED" -gt 0 ]; then
    exit 1
fi
exit 0
