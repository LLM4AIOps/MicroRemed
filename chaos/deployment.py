import os
import subprocess
from kubernetes import client, config
import yaml
from typing import Dict, Optional, Tuple

from chaos.check_status import check_pod_ready_recovered

# Global cache: app_label -> (kind, name, yaml_str)
_app_to_resource_cache: Optional[Dict[str, Tuple[str, str, str]]] = None
KUBECONFIG_PATH = "/etc/rancher/k3s/k3s.yaml"


def _load_original_resources(manifest_path: str):
    """
    Load original YAML manifest and index resources by their 'app' label.
    """
    global _app_to_resource_cache
    if _app_to_resource_cache is not None:
        return

    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"Manifest file not found: {manifest_path}")

    _app_to_resource_cache = {}

    with open(manifest_path, "r") as f:
        docs = yaml.safe_load_all(f)
        for doc in docs:
            if not doc or "kind" not in doc or "metadata" not in doc:
                continue

            kind = doc["kind"]
            name = doc["metadata"].get("name", "unknown")

            try:
                if kind in ("Deployment", "StatefulSet", "DaemonSet"):
                    app_label = doc["spec"]["template"]["metadata"]["labels"]["app"]
                elif kind == "Pod":
                    app_label = doc["metadata"]["labels"]["app"]
                else:
                    continue
            except (KeyError, TypeError):
                print(f"⚠️  Skipped {kind}/{name}: missing 'app' label")
                continue

            yaml_str = yaml.dump(doc, default_flow_style=False, indent=2)
            _app_to_resource_cache[app_label] = (kind, name, yaml_str)

    print(f"✅ Loaded {len(_app_to_resource_cache)} restorable resources from {manifest_path}")


def get_original_resource_by_app(app_label: str, manifest_path: str) -> Optional[Tuple[str, str, str]]:
    """
    Retrieve the (kind, name, YAML string) tuple of a given app label.
    """
    if _app_to_resource_cache is None:
        _load_original_resources(manifest_path)
    return _app_to_resource_cache.get(app_label)


def _extract_container_resources_from_yaml(yaml_str: str, container_name: str) -> Optional[Dict]:
    try:
        obj = yaml.safe_load(yaml_str)
        containers = obj.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        for c in containers:
            if c.get("name") == container_name:
                return c.get("resources", {})
        return None
    except Exception:
        return None


def _normalize_resource_value(val) -> str:
    if not val:
        return ""
    s = str(val).strip()
    if s.endswith("m"):
        try:
            num = int(s[:-1])
            return f"{num / 1000:.3f}".rstrip("0").rstrip(".")
        except ValueError:
            pass
    return s


def _normalize_resources(resources: dict) -> dict:
    if not resources:
        return {}
    norm = {}
    for section in ["requests", "limits"]:
        if section in resources:
            norm[section] = {
                k: _normalize_resource_value(v)
                for k, v in resources[section].items()
                if k in ("cpu", "memory")
            }
    return norm


def _resources_equal(res1: dict, res2: dict) -> bool:
    return _normalize_resources(res1) == _normalize_resources(res2)


def _get_current_pod_resources(namespace: str, app_label: str, container_name: str) -> Optional[Dict]:
    try:
        config.load_kube_config(config_file=KUBECONFIG_PATH)
        v1 = client.CoreV1Api()
        pods = v1.list_namespaced_pod(
            namespace=namespace,
            label_selector=f"app={app_label}"
        ).items

        if not pods:
            return None

        pod = next((p for p in pods if p.status.phase == "Running"), pods[0])

        for c in pod.spec.containers:
            if c.name == container_name:
                res = c.resources
                if not res:
                    return {}
                return {
                    "requests": dict(res.requests or {}),
                    "limits": dict(res.limits or {}),
                }
        return None
    except Exception:
        return None


def _is_pod_abnormal(pod: any) -> bool:
    """
    Check if the pod is in an abnormal state such as ImagePullBackOff, ErrImagePull, or CrashLoopBackOff.
    """
    try:
        if pod.status.phase != "Running":
            print(f"⚠️ Pod {pod.metadata.name} in phase={pod.status.phase}")
            return True
        for condition in pod.status.conditions:
            if condition.type == "Ready" and condition.status != "True":
                print(f"⚠️ Pod {pod.metadata.name} in phase=Running, but not ready")
                return True
        return False
    except Exception as e:
        print(f"⚠️ Error checking pod state: {e}")
        return False


def restore_by_original_manifest(namespace: str, app_label: str,
                                 manifest_path: str) -> bool:
    """
    Restore a workload by reapplying its original manifest.

    Workflow:
    1. For each pod under this app, check if it is abnormal or its resources differ from the original.
       - If so, delete the pod.
    2. Apply the original YAML manifest.
    3. Wait for all pods to recover and become Ready.
    """
    result = get_original_resource_by_app(app_label, manifest_path)
    if not result:
        print(f"❌ No definition found for app={app_label} in original manifest.")
        return False

    kind, name, yaml_str = result
    print(f"🔄 Restoring {kind}/{name} (app={app_label}) ...")

    # Load K8s client
    config.load_kube_config(config_file=KUBECONFIG_PATH)
    api = client.CoreV1Api()

    # Get all pods for this app
    try:
        pods = api.list_namespaced_pod(namespace, label_selector=f"app={app_label}").items
    except Exception as e:
        print(f"⚠️ Failed to list pods: {e}")
        return False

    target_resources = _extract_container_resources_from_yaml(yaml_str, container_name=app_label)

    # Step 1: Check each pod
    for pod in pods:
        pod_name = pod.metadata.name
        pod_abnormal = _is_pod_abnormal(pod)

        # Check resource differences
        if not pod_abnormal and target_resources is not None:
            current_resources = _get_current_pod_resources(namespace, app_label, container_name=app_label)
            if current_resources is not None and not _resources_equal(target_resources, current_resources):
                pod_abnormal = True
                print(f"⚠️ Pod {pod_name} resources differ from original manifest")

        # Delete pod if abnormal
        if pod_abnormal:
            try:
                print(f"🗑️ Deleting abnormal pod {pod_name} ...")
                api.delete_namespaced_pod(name=pod_name, namespace=namespace)
            except Exception as e:
                print(f"⚠️ Failed to delete pod {pod_name}: {e}")

    # Step 2: Apply original manifest
    try:
        cmd = ["kubectl", "apply", "-f", "-", "-n", namespace]
        result_proc = subprocess.run(
            cmd,
            input=yaml_str,
            text=True,
            capture_output=True,
            timeout=30
        )

        if result_proc.returncode != 0:
            print(f"⚠️ Apply failed: {result_proc.stderr}")
            return False

        print(f"✅ Successfully applied {kind}/{name}. Waiting for pod recovery ...")
    except subprocess.TimeoutExpired:
        print("⚠️ Timeout while executing kubectl apply.")
        return False
    except Exception as e:
        print(f"⚠️ Exception during apply: {e}")
        return False

    # Step 3: Wait for all pods to recover
    if check_pod_ready_recovered(api, namespace, f"app={app_label}"):
        print("✅ Pod successfully recovered and ready.")
        return True
    else:
        print("⚠️ Pod did not reach Ready state after apply.")
        return False
