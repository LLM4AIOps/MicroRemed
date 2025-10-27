import json
import os
import time
import argparse

from config import set_config
from methods.remediate import remediate
from chaos import check_status
from chaos.deployment import restore_by_original_manifest
from envs.env import get_random_service, get_random_failure, deploy_env
from chaos.injection import inject_failure, stop_injection


def _save_conversation(save_path: str, log_data: list, **metadata):
    """
    Save conversation log and metadata to a JSON file.
    """
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    full_log = {
        "metadata": {
            "generated_at": time.time(),
            **metadata
        },
        "conversation": log_data
    }
    with open(save_path, 'w', encoding='utf-8') as f:
        json.dump(full_log, f, ensure_ascii=False, indent=2)
    print(f"✅ Conversation log saved to: {save_path}")


def estimate_token_count(conversations: list) -> int:
    """
    Roughly estimate the number of tokens in the conversation.
    Approximation: 1 token ≈ 4 characters.
    """
    total_chars = sum(len(json.dumps(msg, ensure_ascii=False)) for msg in conversations)
    return total_chars // 4


def run_experiments(args):
    """
    Conduct automated failure injection and remediation experiments.
    """

    success_count = 0
    total_remediation_tries = 0
    total_token_count = 0
    total_remediation_time = 0
    success_token_count = 0
    success_remediation_time = 0
    current_experiment_no = 1
    failure_injection_failures = 0
    failure_type_success_remediation_dict = {}
    failure_type_success_injection_dict = {}

    print(f"\n[INFO] Starting experiment series...")

    # Initialize target environment if not provided
    target_env = args.env or "default-env"
    print(f"[INFO] Target environment: {target_env}")

    # === Load failure list from experiment file (if provided) ===
    if args.experiment_path and os.path.exists(args.experiment_path):
        with open(args.experiment_path, "r") as f:
            failure_list = [
                line.strip() for line in f.readlines()
                if line.strip() and not line.strip().startswith("#")
            ]
        print(f"[INFO] Loaded {len(failure_list)} failure types from {args.experiment_path}")
    else:
        failure_list = None

    # Determine experiment count
    total_experiments = len(failure_list) if failure_list else args.experiments
    print(f"[INFO] Total experiments to execute: {total_experiments}")

    while current_experiment_no <= total_experiments:
        print(f"\n=== Experiment {current_experiment_no} / {total_experiments} ===")

        # Select failure type
        if failure_list:
            failure_type = failure_list[current_experiment_no - 1]
        else:
            failure_type = get_random_failure(target_env)
        target_pod = get_random_service(target_env, failure_type)
        print(f"[INFO] Injecting failure '{failure_type}' on target pod '{target_pod}'")

        if not check_status.check(args.namespace, f"app={target_pod}", "pod-fail"):
            print(f"[INFO] Unable to get a health service, restarting whole system...")
            deploy_env(target_env)
            continue

        injection_status = inject_failure(failure_type, target_pod, args.namespace)
        if not injection_status:
            failure_injection_failures += 1
            current_experiment_no += 1
            continue

        print(f"[INFO] Chaos YAML applied successfully. Monitoring injection status...")

        # Wait for chaos injection to take effect
        start_time_injection = time.time()
        injected = False
        while True:
            if time.time() - start_time_injection > args.injection_timeout:
                print(f"[WARN] Injection timeout for {failure_type} on {target_pod}")
                if args.enable_strict_restart:
                    print(f"[INFO] In strict restart mode, restarting whole system...")
                    deploy_env(target_env)
                    continue
                break
            if not check_status.check(args.namespace, f"app={target_pod}", failure_type, 5):
                injected = True
                break
            time.sleep(args.wait_interval)

        if not injected:
            # Stop the chaos experiment
            stop_injection(failure_type, args.namespace)

            failure_injection_failures += 1
            current_experiment_no += 1
            continue

        print(f"[INFO] Failure '{failure_type}' on '{target_pod}' successfully injected.")
        failure_type_success_injection_dict[failure_type] = failure_type_success_injection_dict.get(failure_type, 0) + 1

        # Start remediation process
        print("[INFO] Initiating failure remediation sequence...")
        start_time_remediation = time.time()
        conversations, try_time = remediate(
            runtime_envs="This microservice system runs on k3s.",
            namespace=args.namespace,
            root_cause=target_pod,
            failure_category=failure_type,
            remediate_method=args.remediate_method
        )
        elapsed_time = time.time() - start_time_remediation

        # Estimate token usage from conversation
        token_count = estimate_token_count(conversations)
        total_token_count += token_count
        total_remediation_time += elapsed_time

        # Check final status
        success = check_status.check(
            namespace=args.namespace,
            label=f"app={target_pod}",
            type=failure_type
        )

        full_log_path = os.path.join(args.save_path, f"{target_pod}_{failure_type}_{int(time.time())}.json")
        # Save conversation log
        _save_conversation(
            full_log_path,
            conversations,
            final_status="success" if success else "failed",
            retries=try_time,
            token_count=token_count,
            remediation_time=elapsed_time
        )
        print(f"[INFO] Conversation log saved to: {full_log_path}")
        print(f"[RESULT] Experiment {current_experiment_no}: success={success}, attempts={try_time}, "
              f"elapsed={elapsed_time:.2f}s, tokens≈{token_count}")

        if success:
            success_count += 1
            total_remediation_tries += try_time
            success_token_count += token_count
            success_remediation_time += elapsed_time
            failure_type_success_remediation_dict[failure_type] = failure_type_success_remediation_dict.get(
                failure_type,
                0) + 1

        # Stop the chaos experiment
        stop_injection(failure_type, args.namespace)

        # Restore the environment to its original state
        print("[INFO] Restoring system to original configuration...")
        restore_by_original_manifest(args.namespace, target_pod, args.manifest_path)
        time.sleep(5)

        current_experiment_no += 1

    # Summary
    print("\n" + "=" * 60)
    print("[SUMMARY] Experiment Series Completed")
    print(f"  Total Experiments: {total_experiments}")
    print(f"  Injection Failures: {failure_injection_failures}")
    print(f"  Successful Remediations: {success_count}")
    if success_count > 0:
        avg_tries = total_remediation_tries / success_count
        avg_success_time = success_remediation_time / success_count
        avg_success_token = success_token_count / success_count
        avg_time = total_remediation_time / (total_experiments - failure_injection_failures)
        avg_token = total_token_count / (total_experiments - failure_injection_failures)
        success_rate = success_count / (total_experiments - failure_injection_failures)
        print(f"  Success Rate: {success_rate:.2%}")
        print(f"  Average Attempts per Success: {avg_tries:.2f}")
        print(f"  Average Remediation Time per Success: {avg_success_time:.2f}s")
        print(f"  Average Estimated Tokens Used per Success: {avg_success_token:.2f}")
        print(f"  Average Remediation Time: {avg_time:.2f}s")
        print(f"  Average Estimated Tokens Used: {avg_token:.2f}")
        print(f"  Failure Types Success Ratio:")
        for key in failure_type_success_injection_dict.keys():
            print(
                f"    {key}: {failure_type_success_remediation_dict.get(key, 0) / failure_type_success_injection_dict[key]: .2f}")
    else:
        print("  No successful remediations — average attempts/time unavailable.")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Automated failure injection and remediation experiment runner.")

    parser.add_argument("--experiments", type=int, default=100, help="Number of experiments to run.")
    parser.add_argument("--namespace", type=str, default="default", help="Kubernetes namespace.")
    parser.add_argument("--wait-interval", type=int, default=10, help="Interval (seconds) between status checks.")
    parser.add_argument("--injection-timeout", type=int, default=30, help="Timeout (seconds) for failure injection.")
    parser.add_argument("--env", type=str, default="train-ticket", help="Target environment identifier.")
    parser.add_argument("--save-path", type=str, default="conversations", help="Directory to store conversation logs.")
    parser.add_argument("--manifest-path", type=str, default="envs/source-config/train-ticket-config.yaml",
                        help="Path to original service config for restoration.")
    parser.add_argument("--remediate-method", type=str, default="ThinkRemed",
                        help="Remediation method to use: ThinkRemed / SoloGen")
    parser.add_argument("--experiment-path", type=str, default=None,
                        help="Path to experiment config setting.")
    parser.add_argument("--enable-strict-restart", type=bool, default=False,
                        help="Restart to try in every injection timeout.")
    parser.add_argument("--model", type=str, default="",
                        help="Applied LLM backbone.")

    args = parser.parse_args()
    set_config(args)
    run_experiments(args)
