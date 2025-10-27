#!/bin/bash
# Auto switch to the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

kubectl delete namespace simple-micro
kubectl create namespace simple-micro
kubectl apply -f ./k8s-deploy.yaml -n simple-micro