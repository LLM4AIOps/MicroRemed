from chaos.failures import stop_chaos

import os
import json
import subprocess
from kubernetes import client, config


def inject_failure(failure_type, target_pod, target_namespace):
    """
    Inject a specified failure into the target workload.
    Supports two modes:
      - 'pod-config-error': Dynamically patch the Deployment's container resources to simulate misconfiguration.
      - Other types: Apply a pre-defined chaos experiment YAML template.
    """
    if failure_type == "pod-config-error":
        try:
            KUBECONFIG_PATH = "/etc/rancher/k3s/k3s.yaml"
            config.load_kube_config(config_file=KUBECONFIG_PATH)
            apps_api = client.AppsV1Api()
            core_api = client.CoreV1Api()

            # 1️⃣ Locate the Deployment associated with the target Pod via its labels
            pods = core_api.list_namespaced_pod(
                namespace=target_namespace,
                label_selector=f"app={target_pod}"
            ).items
            if not pods:
                print(f"[ERROR] No pod found with label app={target_pod} in namespace {target_namespace}")
                return False
            pod = pods[0]

            # Traverse ownerReferences to find the top-level Deployment
            owner_refs = pod.metadata.owner_references
            deployment_name = None
            for ref in owner_refs or []:
                if ref.kind == "ReplicaSet":
                    # Fetch the ReplicaSet and inspect its owner
                    rs_name = ref.name
                    rs = apps_api.read_namespaced_replica_set(rs_name, target_namespace)
                    for rs_ref in rs.metadata.owner_references or []:
                        if rs_ref.kind == "Deployment":
                            deployment_name = rs_ref.name
                            break
            if not deployment_name:
                print(f"[ERROR] Failed to trace Deployment from pod {pod.metadata.name}")
                return False

            # 2️⃣ Retrieve the Deployment and patch its container resource limits/requests
            deployment = apps_api.read_namespaced_deployment(
                name=deployment_name, namespace=target_namespace
            )

            containers = deployment.spec.template.spec.containers
            if not containers:
                print(f"[ERROR] Deployment {deployment_name} contains no containers")
                return False

            # Modify resource configuration of the first container to induce performance issues
            container = containers[0]
            container_name = container.name
            patch = {
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [{
                                "name": container_name,
                                "resources": {
                                    "requests": {"cpu": "1m", "memory": "100Mi"},
                                    "limits": {"cpu": "2m", "memory": "200Mi"}
                                }
                            }]
                        }
                    }
                }
            }

            patch_str = json.dumps(patch)
            _ = apps_api.patch_namespaced_deployment(
                name=deployment_name,
                namespace=target_namespace,
                body=json.loads(patch_str)
            )

            print(f"[INFO] Successfully injected resource misconfiguration into Deployment {deployment_name}")
            return True
        except Exception as e:
            print(f"[ERROR] Exception during config error injection: {e}")
            return False
    else:
        # Prepare chaos YAML by replacing placeholders [target_pod] and [target_namespace]
        template_path = f"chaos/templates/{failure_type}.yaml"
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"[ERROR] Chaos template not found: {template_path}")

        with open(template_path, "r") as f:
            template_content = f.read()
        updated_content = template_content.replace("[target_pod]", target_pod)
        updated_content = updated_content.replace("[target_namespace]", target_namespace)

        inject_file = f"chaos/templates/{failure_type}.yaml.injecting"
        with open(inject_file, "w") as f:
            f.write(updated_content)
        print(f"[INFO] Generated injection manifest: {inject_file}")

        # Apply the chaos experiment
        try:
            result = subprocess.run(
                ["kubectl", "apply", "-f", inject_file],
                capture_output=True,
                text=True,
                timeout=10
            )
        except subprocess.TimeoutExpired:
            print(f"[ERROR] Injection command timed out for failure type: {failure_type}")
            return False

        if result.returncode != 0:
            print(f"[ERROR] Failed to apply chaos YAML:\n{result.stderr}")
            return False
        return True


def stop_injection(failure_type, target_namespace):
    """
    Stop the injected failure and clean up temporary resources.
    For 'pod-config-error', no immediate rollback is performed—recovery is handled externally.
    For other chaos types, execute the corresponding stop command and remove the temporary manifest.
    """
    if failure_type == "pod-config-error":
        # Configuration errors are not reverted here; recovery is managed by a separate reconciliation process
        pass
    else:
        inject_file = f"chaos/templates/{failure_type}.yaml.injecting"
        # Stop the chaos experiment if a stop command is defined
        if failure_type in stop_chaos:
            stop_cmd = stop_chaos[failure_type].replace("[target_namespace]", target_namespace)
            try:
                subprocess.run(
                    stop_cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=10
                )
            except subprocess.TimeoutExpired:
                pass  # Ignore timeout during cleanup
            print("[INFO] Chaos experiment stopped successfully.")
        # Clean up the temporary injection file
        if os.path.exists(inject_file):
            os.remove(inject_file)
