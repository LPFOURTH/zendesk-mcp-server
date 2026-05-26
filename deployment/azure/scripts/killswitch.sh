#!/usr/bin/env bash
# killswitch.sh — one-command revert to the last-known-good revision.
#
# What it does:
#   Shifts 100% of /mcp/dev (and /mcp/prod) traffic back to the documented
#   "good" revision, deactivating whatever revision is currently active.
#   This is the big-red-button after a bad audit-fix deploy.
#
# What it does NOT do:
#   - Does not delete the bad revision (you can inspect it later)
#   - Does not redeploy from source (Container Apps keeps revisions warm)
#   - Does not change Cosmos / Key Vault / Blob — only ingress traffic
#
# Time to revert: ~10 seconds.
#
# Usage:
#   ./killswitch.sh                 # interactive — confirms before flipping
#   ./killswitch.sh --force         # no confirmation — for CI / scripts
#   ./killswitch.sh --status        # show current vs known-good revision, no change
#   GOOD_REVISION=<name> ./killswitch.sh    # override the known-good target
#
# Updating the known-good revision:
#   When you've deployed a new version that's been verified-healthy for a while,
#   update GOOD_REVISION_DEFAULT below. Commit the change. The killswitch now
#   targets the new known-good.

set -euo pipefail

RG="${RG:-fourth-ai-prod}"
APP="${APP:-fourth-zendesk-mcp-server}"

# The revision we always want to be able to return to.
# Update this when a new release has been verified-healthy for >24h in prod.
# Last updated: 2026-05-20 (v3.10.5 — Architecture C revert; commit 9fe2975 on fourth/main)
GOOD_REVISION_DEFAULT="fourth-zendesk-mcp-server--0000111"
GOOD_REVISION="${GOOD_REVISION:-$GOOD_REVISION_DEFAULT}"

MODE="interactive"
case "${1:-}" in
  --force)  MODE="force" ;;
  --status) MODE="status" ;;
  --help|-h)
    sed -n '1,30p' "$0"
    exit 0
    ;;
  "") ;;
  *)
    echo "Unknown option: $1" >&2
    echo "See $0 --help"
    exit 2
    ;;
esac

bold()  { printf "\033[1m%s\033[0m\n" "$*"; }
red()   { printf "\033[31m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }
yellow(){ printf "\033[33m%s\033[0m\n" "$*"; }

# -----------------------------------------------------------------------------
# Preflight: Azure CLI present, logged in, target revision exists and is healthy
# -----------------------------------------------------------------------------
if ! command -v az >/dev/null 2>&1; then
  red "ERROR: az CLI not found. Install it first: https://aka.ms/installazcli"
  exit 1
fi

if ! az account show >/dev/null 2>&1; then
  red "ERROR: not logged in to Azure. Run: az login"
  exit 1
fi

bold "=== Killswitch preflight ==="
echo "Resource group: $RG"
echo "Container app:  $APP"
echo "Target good revision: $GOOD_REVISION"
echo

# Get current active revision and traffic weights
CURRENT_STATE=$(az containerapp revision list \
  --name "$APP" --resource-group "$RG" \
  --query "[?properties.active==\`true\`].{name:name, traffic:properties.trafficWeight, healthState:properties.healthState, image:properties.template.containers[0].image, createdTime:properties.createdTime}" \
  -o json 2>/dev/null) || {
    red "ERROR: failed to query revisions. Wrong RG/app name or no permission?"
    exit 1
  }

echo "Currently active revisions:"
echo "$CURRENT_STATE" | python3 -c "
import json, sys
revs = json.load(sys.stdin)
for r in revs:
    marker = '⬅ TARGET' if r['name'] == '$GOOD_REVISION' else ''
    print(f\"  {r['name']:50s}  traffic={r['traffic']:>3}%  health={r['healthState']:8s}  {marker}\")
"
echo

# Verify the known-good revision exists
GOOD_EXISTS=$(az containerapp revision show \
  --name "$APP" --resource-group "$RG" \
  --revision "$GOOD_REVISION" \
  --query "properties.healthState" -o tsv 2>/dev/null || echo "NOTFOUND")

if [ "$GOOD_EXISTS" = "NOTFOUND" ]; then
  red "ERROR: known-good revision '$GOOD_REVISION' does not exist."
  red "       Maybe Container Apps garbage-collected it (default keeps 100)."
  red "       Edit GOOD_REVISION_DEFAULT in this script, or set GOOD_REVISION env."
  exit 1
fi

if [ "$GOOD_EXISTS" != "Healthy" ]; then
  yellow "WARNING: known-good revision '$GOOD_REVISION' is '$GOOD_EXISTS', not Healthy."
  yellow "         The flip will still proceed, but verify it boots."
fi

# Find the current 100%-traffic revision (the bad one we're flipping AWAY from)
BAD_REVISION=$(echo "$CURRENT_STATE" | python3 -c "
import json, sys
revs = json.load(sys.stdin)
for r in revs:
    if r['traffic'] == 100 and r['name'] != '$GOOD_REVISION':
        print(r['name'])
        break
")

if [ -z "$BAD_REVISION" ]; then
  green "INFO: $GOOD_REVISION is already at 100% traffic. Nothing to do."
  exit 0
fi

echo "About to:"
echo "  - Shift $BAD_REVISION  100% → 0%"
echo "  - Shift $GOOD_REVISION 0% → 100%"
echo
echo "Side effects:"
echo "  - Active users on /mcp/dev (Arch C) keep working; their tokens stay valid."
echo "  - Active users on /mcp/prod (Arch B) keep working; no auth change."
echo "  - The bad revision stays in the revision list — you can inspect it later."
echo "  - L1 env-var killswitches set on the bad revision do NOT carry forward."
echo

if [ "$MODE" = "status" ]; then
  bold "Status only — no changes. To revert, re-run without --status."
  exit 0
fi

if [ "$MODE" = "interactive" ]; then
  read -r -p "Proceed? Type 'revert' to confirm: " confirm
  if [ "$confirm" != "revert" ]; then
    yellow "Aborted. No changes made."
    exit 0
  fi
fi

# -----------------------------------------------------------------------------
# Execute the flip
# -----------------------------------------------------------------------------
bold "=== Flipping traffic ==="
START_TS=$(date +%s)

az containerapp ingress traffic set \
  --name "$APP" --resource-group "$RG" \
  --revision-weight "$GOOD_REVISION=100" "$BAD_REVISION=0" \
  --output none

END_TS=$(date +%s)
ELAPSED=$((END_TS - START_TS))

green "✓ Traffic flipped in ${ELAPSED}s."
echo
bold "=== Post-flip state ==="
az containerapp revision list \
  --name "$APP" --resource-group "$RG" \
  --query "[?properties.active==\`true\`].{name:name, traffic:properties.trafficWeight, health:properties.healthState}" \
  -o table

echo
echo "Verify it's actually live:"
echo "  curl -s -o /dev/null -w 'HTTP %{http_code}\n' https://fourth-zendesk-mcp-server.bluewave-95f931ef.northeurope.azurecontainerapps.io/mcp/dev"
echo "  curl -s -o /dev/null -w 'HTTP %{http_code}\n' https://fourth-zendesk-mcp-server.bluewave-95f931ef.northeurope.azurecontainerapps.io/mcp/prod"
echo
echo "Forensics on the bad revision:"
echo "  az containerapp logs show --name $APP --resource-group $RG --revision $BAD_REVISION --tail 100"
echo
green "Done. Architecture C is back on $GOOD_REVISION."
