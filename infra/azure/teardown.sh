#!/usr/bin/env bash
# Delete every Azure resource created by deploy.sh (the whole resource group).
set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-disease-surveillance}"

az account show >/dev/null 2>&1 || { echo "Not signed in. Run: az login"; exit 1; }
echo "This permanently deletes resource group '$RESOURCE_GROUP' and everything in it."
read -r -p "Type the resource group name to confirm: " answer
[[ "$answer" == "$RESOURCE_GROUP" ]] || { echo "Aborted."; exit 1; }

az group delete --name "$RESOURCE_GROUP" --yes --no-wait
echo "Deletion started. Check progress with: az group show --name $RESOURCE_GROUP"
