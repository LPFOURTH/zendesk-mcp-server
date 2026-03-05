#!/bin/bash
set -euo pipefail

# ============================================================
# Step 3: Set up custom domain with managed TLS certificate
# Run AFTER you've created the DNS records.
# ============================================================

RESOURCE_GROUP="fourth-zendesk-prod"
ENVIRONMENT_NAME="fourth-zendesk-env"
APP_NAME="fourth-zendesk-mcp-server"
CUSTOM_DOMAIN="${1:-zendesk-mcp.fourth.com}"

FQDN=$(az containerapp show \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query "properties.configuration.ingress.fqdn" -o tsv)

echo "=== Custom Domain Setup ==="
echo ""
echo "Before running this script, create these DNS records:"
echo ""
echo "  CNAME:  $CUSTOM_DOMAIN  →  $FQDN"
echo "  TXT:    asuid.$CUSTOM_DOMAIN  →  (get value from Azure after adding hostname)"
echo ""
echo "If your domain has a CAA record, also add:"
echo "  CAA:    0 issue \"digicert.com\""
echo ""
read -p "Have you created the CNAME record? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "Create the DNS records first, then re-run this script."
  exit 1
fi

echo ""
echo "=== Adding hostname to Container App ==="
az containerapp hostname add \
  --hostname "$CUSTOM_DOMAIN" \
  --resource-group "$RESOURCE_GROUP" \
  --name "$APP_NAME"

echo ""
echo "=== Binding managed TLS certificate ==="
az containerapp hostname bind \
  --hostname "$CUSTOM_DOMAIN" \
  --resource-group "$RESOURCE_GROUP" \
  --name "$APP_NAME" \
  --environment "$ENVIRONMENT_NAME" \
  --validation-method CNAME

echo ""
echo "=== Custom Domain Configured ==="
echo "URL: https://$CUSTOM_DOMAIN"
echo "Certificate: Azure-managed (auto-renewed by DigiCert)"
echo ""
echo "Test: curl https://$CUSTOM_DOMAIN/health"
