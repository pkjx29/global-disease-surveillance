#!/usr/bin/env bash
# Deploy the platform to Azure Kubernetes Service.
#
#   ./infra/azure/deploy.sh          # plan (default): renders the manifests, lists what would be created, creates nothing
#   az login                         # once, with your own account
#   ./infra/azure/deploy.sh apply    # creates resource group, ACR, AKS; builds images; deploys
#   ./infra/azure/teardown.sh        # deletes everything again (stops the billing)
#
# Everything is created inside one resource group, so teardown is a single delete.
# Override any setting through the environment, e.g.  LOCATION=southindia ./infra/azure/deploy.sh
set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-disease-surveillance}"
LOCATION="${LOCATION:-centralindia}"
AKS_NAME="${AKS_NAME:-aks-disease-surveillance}"
NODE_COUNT="${NODE_COUNT:-2}"
NODE_SIZE="${NODE_SIZE:-Standard_B2ms}"            # 2 vCPU / 8 GiB: the stack needs roughly 4 GiB in total
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M)}"
NAMESPACE="surveillance"
MODE="${1:-plan}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

case "$MODE" in
  plan|apply) ;;
  *) echo "usage: $0 [plan|apply]"; exit 1 ;;
esac
command -v kubectl >/dev/null || { echo "kubectl not found (az aks install-cli)"; exit 1; }

if [[ "$MODE" == plan ]]; then
  # dry run: no Azure login, no API calls, nothing created
  echo "==> plan only, nothing is created"
  echo "Would create : resource group $RESOURCE_GROUP ($LOCATION), a Basic container registry,"
  echo "               AKS $AKS_NAME ($NODE_COUNT x $NODE_SIZE, free tier, Azure CNI with network policy)"
  echo "Would build  : backend, dashboard and flink images tagged $IMAGE_TAG"
  echo "Would create : Secrets surveillance-db and surveillance-api with random values"
  echo "Kubernetes resources from k8s/overlays/azure:"
  kubectl kustomize k8s/overlays/azure \
    | awk '/^kind:/ { kind = $2 } /^  name:/ && kind { print "  " kind "/" $2; kind = "" }'
  echo "Run '$0 apply' to create these billable resources."
  exit 0
fi

command -v az >/dev/null || { echo "Azure CLI not found: https://learn.microsoft.com/cli/azure/install-azure-cli"; exit 1; }
az account show >/dev/null 2>&1 || { echo "Not signed in. Run: az login"; exit 1; }

SUBSCRIPTION="$(az account show --query name -o tsv)"
# ACR names are global and alphanumeric: derive a stable one from the subscription id
ACR_NAME="${ACR_NAME:-acrsurv$(az account show --query id -o tsv | tr -d '-' | cut -c1-12)}"
echo "Subscription : $SUBSCRIPTION"
echo "Resources    : $RESOURCE_GROUP ($LOCATION) -> $ACR_NAME, $AKS_NAME ($NODE_COUNT x $NODE_SIZE)"
echo "Image tag    : $IMAGE_TAG"
read -r -p "This creates billable Azure resources. Continue? [y/N] " answer
[[ "$answer" =~ ^[Yy]$ ]] || exit 0

echo "==> resource group"
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none

echo "==> container registry"
az acr show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1 \
  || az acr create --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" --sku Basic --output none
ACR_LOGIN_SERVER="$(az acr show --name "$ACR_NAME" --query loginServer -o tsv)"

echo "==> building images in ACR (linux/amd64)"
az acr build --registry "$ACR_NAME" --image "disease-surveillance/backend:$IMAGE_TAG"   backend  --output none
az acr build --registry "$ACR_NAME" --image "disease-surveillance/dashboard:$IMAGE_TAG" frontend --output none
az acr build --registry "$ACR_NAME" --image "disease-surveillance/flink:$IMAGE_TAG"     flink    --output none

echo "==> AKS cluster (this takes several minutes the first time)"
az aks show --name "$AKS_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1 \
  || az aks create \
       --name "$AKS_NAME" \
       --resource-group "$RESOURCE_GROUP" \
       --node-count "$NODE_COUNT" \
       --node-vm-size "$NODE_SIZE" \
       --tier free \
       --network-plugin azure \
       --network-policy azure \
       --enable-app-routing \
       --attach-acr "$ACR_NAME" \
       --generate-ssh-keys \
       --output none
az aks get-credentials --name "$AKS_NAME" --resource-group "$RESOURCE_GROUP" --overwrite-existing

echo "==> namespace, database and API-key secrets"
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
if ! kubectl -n "$NAMESPACE" get secret surveillance-db >/dev/null 2>&1; then
  DB_PASSWORD="$(openssl rand -hex 24)"
  kubectl -n "$NAMESPACE" create secret generic surveillance-db \
    --from-literal=POSTGRES_USER=surveillance \
    --from-literal=POSTGRES_PASSWORD="$DB_PASSWORD" \
    --from-literal=DATABASE_URL="postgresql+psycopg2://surveillance:${DB_PASSWORD}@postgres:5432/disease_surveillance" \
    --from-literal=JDBC_URL="jdbc:postgresql://postgres:5432/disease_surveillance"
fi
if ! kubectl -n "$NAMESPACE" get secret surveillance-api >/dev/null 2>&1; then
  DASHBOARD_API_KEY="$(openssl rand -hex 24)"
  kubectl -n "$NAMESPACE" create secret generic surveillance-api \
    --from-literal=API_KEYS="$DASHBOARD_API_KEY" \
    --from-literal=DASHBOARD_API_KEY="$DASHBOARD_API_KEY"
fi

echo "==> applying manifests"
kubectl kustomize k8s/overlays/azure \
  | sed -e "s|ACR_LOGIN_SERVER|${ACR_LOGIN_SERVER}|g" -e "s|IMAGE_TAG|${IMAGE_TAG}|g" \
  | kubectl apply -f -

echo "==> waiting for the pipeline to load data and train the model"
kubectl -n "$NAMESPACE" wait --for=condition=complete job/pipeline-bootstrap --timeout=20m
kubectl -n "$NAMESPACE" rollout status deployment/api --timeout=5m
kubectl -n "$NAMESPACE" rollout status deployment/dashboard --timeout=5m

echo "==> public address"
for _ in $(seq 1 30); do
  IP="$(kubectl -n "$NAMESPACE" get ingress dashboard -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)"
  [[ -n "$IP" ]] && break
  sleep 10
done
echo "Dashboard : http://${IP:-<pending: kubectl -n $NAMESPACE get ingress dashboard>}"
echo "API docs  : http://${IP:-<pending>}/api/v1/docs"
echo "Flink UI  : kubectl -n $NAMESPACE port-forward svc/flink-jobmanager 8081:8081"
