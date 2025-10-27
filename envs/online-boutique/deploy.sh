#!/bin/bash
# Auto switch to the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

kubectl delete namespace online-boutique
kubectl create namespace online-boutique
kubectl apply -f kubernetes-manifests.yaml -n kubernetes-manifests.yaml -n online-boutique