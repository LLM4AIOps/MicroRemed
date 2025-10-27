#!/bin/bash
ENV_NAME=$1
if [ -z "$ENV_NAME" ]; then
  echo "Usage: bash run.sh <env_name> <log_dir> <model>"
  exit 1
fi

LOG_DIR=$2
if [ -z "$LOG_DIR" ]; then
  echo "Usage: bash run.sh <env_name> <log_dir> <model>"
  exit 1
fi

MODEL=$3
if [ -z "$MODEL" ]; then
  echo "Usage: bash run.sh <env_name> <log_dir> <model>"
  exit 1
fi

# Create or reuse log directory
mkdir -p "$LOG_DIR"

echo "=== [Init] Environment: $ENV_NAME ==="
echo "=== [Step 1] Stopping any existing chaos experiments ==="
bash scripts/stop_chaos.sh "$ENV_NAME"

# Function to deploy environment (runs in envs/$ENV_NAME)
deploy_env() {
  echo "=== [Deploy] Deploying environment: $ENV_NAME ==="
  pushd "envs/$ENV_NAME" > /dev/null
  bash deploy.sh
  popd > /dev/null

  echo "=== [Check] Waiting for all pods in namespace '$ENV_NAME' to become Running, Ready, and Metrics-Available ==="

  MAX_RETRIES=60    # Wait up to ~5 min (60 * 5s)
  RETRY_INTERVAL=5

  for i in $(seq 1 $MAX_RETRIES); do
    POD_STATUS=$(kubectl get pods -n "$ENV_NAME" --no-headers 2>/dev/null)

    if [ -z "$POD_STATUS" ]; then
      echo "[WARN] No pods found in namespace '$ENV_NAME' (attempt $i/$MAX_RETRIES)"
      sleep $RETRY_INTERVAL
      continue
    fi

    # Check if any pod is not fully running or partially running
    NOT_READY=$(echo "$POD_STATUS" | grep -Ev 'Running' || true)
    PARTIAL_RUNNING=$(echo "$POD_STATUS" | awk '{print $2}' | grep -E '^[0-9]+/[0-9]+$' | awk -F'/' '$1 != $2' || true)

    if [ -z "$NOT_READY" ] && [ -z "$PARTIAL_RUNNING" ]; then
      echo "[INFO] All pods are Running and Ready — checking metrics availability..."

      # Check that 'kubectl top pod' succeeds and no metrics error appears
      METRICS_OUTPUT=$(kubectl top pod -n "$ENV_NAME" 2>&1 || true)
      if echo "$METRICS_OUTPUT" | grep -q "error: metrics not available"; then
        echo "[WARN] Metrics not yet available for some pods (attempt $i/$MAX_RETRIES)"
        sleep $RETRY_INTERVAL
        continue
      fi
      if echo "$METRICS_OUTPUT" | grep -q "No resources found"; then
        echo "[WARN] Metrics-server returned no pods (attempt $i/$MAX_RETRIES)"
        sleep $RETRY_INTERVAL
        continue
      fi

      echo "✅ All pods are Running, Ready, and have available metrics in namespace '$ENV_NAME'"
      return 0
    fi

    echo "[INFO] Waiting... (attempt $i/$MAX_RETRIES)"
    sleep $RETRY_INTERVAL
  done

  echo "❌ Timeout: Some pods did not reach Running & Ready state or metrics unavailable within expected time."
  echo "--- Pod status ---"
  kubectl get pods -n "$ENV_NAME"
  echo "--- Metrics status ---"
  kubectl top pod -n "$ENV_NAME" 2>&1 || true
  return 1
}

# Function to run each experiment
run_experiment() {
  local method=$1
  local difficulty=$2

  echo "=== [Run] Starting $method ($difficulty) ==="
  env PYTHONUNBUFFERED=1 python3 inject_and_remediate.py \
    --experiments 50 \
    --namespace "$ENV_NAME" \
    --wait-interval 10 \
    --injection-timeout 60 \
    --env "$ENV_NAME" \
    --save-path conversations \
    --manifest-path "envs/source-config/${ENV_NAME}-config.yaml" \
    --remediate-method "$method" \
    --experiment-path "experiments/${difficulty}.txt" \
    --model "$MODEL" \
    > "${LOG_DIR}/${method}_${difficulty}.log" 2>&1

  echo "=== [Run] Completed $method ($difficulty) ==="
}

# === Full experiment sequence ===
deploy_env
run_experiment "SoloGen" "easy"
deploy_env
run_experiment "ThinkRemed" "easy"
deploy_env
run_experiment "SoloGen" "medium"
deploy_env
run_experiment "ThinkRemed" "medium"
deploy_env
run_experiment "SoloGen" "hard"
deploy_env
run_experiment "ThinkRemed" "hard"

echo "=== ✅ All experiments completed successfully! Logs saved in ${LOG_DIR}/ ==="