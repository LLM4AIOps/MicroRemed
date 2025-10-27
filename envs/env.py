import random

import subprocess
import time
import sys

MAX_RETRIES = 60  # up to ~5 min (60 * 5s)
RETRY_INTERVAL = 5


def run_cmd(cmd, capture_output=True):
    """Run shell command and return output or error"""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=capture_output, text=True, check=False
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except Exception as e:
        return "", str(e), 1


def deploy_env(env_name):
    print(f"=== [Deploy] Deploying environment: {env_name} ===")

    # run deploy.sh
    deploy_cmd = f"bash envs/{env_name}/deploy.sh"
    out, err, code = run_cmd(deploy_cmd)
    if code != 0:
        print(f"❌ Deployment failed: {err or out}")
        sys.exit(1)

    print(f"=== [Check] Waiting for all pods in namespace '{env_name}' "
          f"to become Running, Ready, and Metrics-Available ===")

    for i in range(1, MAX_RETRIES + 1):
        out, err, code = run_cmd(f"kubectl get pods -n {env_name} --no-headers 2>/dev/null")
        pod_status = out.strip()

        if not pod_status:
            print(f"[WARN] No pods found in namespace '{env_name}' (attempt {i}/{MAX_RETRIES})")
            time.sleep(RETRY_INTERVAL)
            continue

        # check running/ready
        not_ready = any("Running" not in line for line in pod_status.splitlines())
        partial_running = any(
            (len(cols := line.split()) > 1 and "/" in cols[1] and cols[1].split("/")[0] != cols[1].split("/")[1])
            for line in pod_status.splitlines()
        )

        if not not_ready and not partial_running:
            print(f"[INFO] All pods are Running and Ready — checking metrics availability...")

            metrics_out, metrics_err, _ = run_cmd(f"kubectl top pod -n {env_name} 2>&1 || true")

            if "error: metrics not available" in metrics_out or "error: metrics not available" in metrics_err:
                print(f"[WARN] Metrics not yet available for some pods (attempt {i}/{MAX_RETRIES})")
                time.sleep(RETRY_INTERVAL)
                continue

            if "No resources found" in metrics_out:
                print(f"[WARN] Metrics-server returned no pods (attempt {i}/{MAX_RETRIES})")
                time.sleep(RETRY_INTERVAL)
                continue

            print(f"✅ All pods are Running, Ready, and have available metrics in namespace '{env_name}'")
            return True

        print(f"[INFO] Waiting... (attempt {i}/{MAX_RETRIES})")
        time.sleep(RETRY_INTERVAL)

    # timeout
    print("❌ Timeout: Some pods did not reach Running & Ready state or metrics unavailable within expected time.")
    print("--- Pod status ---")
    run_cmd(f"kubectl get pods -n {env_name}", capture_output=False)
    print("--- Metrics status ---")
    run_cmd(f"kubectl top pod -n {env_name} 2>&1 || true", capture_output=False)
    return False


def get_random_failure(target_env):
    if target_env == "simple-micro":
        return random.choice([
            "cpu-stress",
            "memory-stress",
            "pod-fail",
            "network-loss",
            "network-delay",
            "disk-io",
            "pod-config-error"
        ])
    elif target_env == "train-ticket":
        return random.choice([
            "cpu-stress",
            "memory-stress",
            "pod-fail",
            "network-loss",
            "network-delay",
            "disk-io",
            "pod-config-error"
        ])
    elif target_env == "online-boutique":
        return random.choice([
            "cpu-stress",
            "memory-stress",
            "pod-fail",
            "network-loss",
            "network-delay",
            "disk-io",
            "pod-config-error"
        ])


def get_random_service(target_env, failure_type):
    if target_env == "simple-micro":
        return random.choice(["hello-service", "time-service"])
    elif target_env == "train-ticket":
        if failure_type == "disk-io":
            return random.choice([
                "nacosdb-mysql"
            ])
        else:
            return random.choice([
                "ts-admin-basic-info-service",
                "ts-admin-order-service",
                "ts-admin-route-service",
                "ts-admin-travel-service",
                "ts-admin-user-service",
                "ts-assurance-service",
                "ts-auth-service",
                "ts-avatar-service",
                "ts-basic-service",
                "ts-cancel-service",
                "ts-config-service",
                "ts-consign-price-service",
                "ts-consign-service",
                "ts-contacts-service",
                "ts-delivery-service",
                "ts-execute-service",
                "ts-food-delivery-service",
                "ts-food-service",
                "ts-gateway-service",
                "ts-inside-payment-service",
                "ts-news-service",
                "ts-notification-service",
                "ts-order-other-service",
                "ts-order-service",
                "ts-payment-service",
                "ts-preserve-other-service",
                "ts-preserve-service",
                "ts-price-service",
                "ts-rebook-service",
                "ts-route-plan-service",
                "ts-route-service",
                "ts-seat-service",
                "ts-security-service",
                "ts-station-food-service",
                "ts-station-service",
                "ts-ticket-office-service",
                "ts-train-food-service",
                "ts-train-service",
                "ts-travel-plan-service",
                "ts-travel-service",
                "ts-travel2-service",
                "ts-ui-dashboard",
                "ts-user-service",
                "ts-verification-code-service",
                "ts-voucher-service",
                "ts-wait-order-service"
            ])
    elif target_env == "online-boutique":
        if failure_type == "disk-io":
            return random.choice([
                "adservice",
                "cartservice",
                "checkoutservice",
                "currencyservice",
                "emailservice",
                "frontend",
                "loadgenerator",
                "paymentservice",
                "productcatalogservice",
                "recommendationservice",
                "shippingservice"
            ])
        else:
            return random.choice([
                "adservice",
                "cartservice",
                "checkoutservice",
                "currencyservice",
                "emailservice",
                "frontend",
                "loadgenerator",
                "paymentservice",
                "productcatalogservice",
                "recommendationservice",
                "redis-cart",
                "shippingservice"
            ])
