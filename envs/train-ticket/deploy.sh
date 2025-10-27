#!/bin/bash
# Auto switch to the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

kubectl delete namespace train-ticket
kubectl create namespace train-ticket
make deploy