import argparse
import subprocess
from kubernetes import client, config
import time

from kubernetes.client import CoreV1Api

from chaos import failures

START_TIMEOUT = 300
START_CHECK_INTERVAL = 10
TIMEOUT = 10
INTERVAL = 2


def get_pod_list(api, namespace, label_selector):
    """Retrieve a list of Pods in the specified namespace matching the given label selector."""
    try:
        ret = api.list_namespaced_pod(namespace, label_selector=label_selector)
        return ret.items
    except Exception as e:
        print(f"❌ Failed to retrieve Pod list: {e}")
        return []


def check_pod_running_and_ready(pod):
    """
    Check whether a Pod is in 'Running' phase and 'Ready' condition.
    Pods marked for deletion (i.e., in 'Terminating' state) are explicitly excluded.
    """
    try:
        # Exclude Pods that are being terminated (have a deletion timestamp)
        if pod.metadata.deletion_timestamp is not None:
            return False

        # Pod must be in 'Running' phase
        if pod.status.phase != "Running":
            return False

        # Verify that the 'Ready' condition is 'True'
        for condition in pod.status.conditions or []:
            if condition.type == "Ready" and condition.status != "True":
                return False
        return True
    except Exception as e:
        print(f"[WARN] Error checking pod {pod.metadata.name}: {e}")
        return False


def parse_cpu_to_millicores(cpu_str: str) -> int:
    """Convert CPU string like '50m' or '0.1' to millicores"""
    if cpu_str.endswith("m"):
        return int(cpu_str[:-1])
    else:
        return int(float(cpu_str) * 1000)


def get_container_cpu_limit_millicores(pod, container_name: str):
    """Get the CPU limit (millicores) for a given container in a Pod"""
    for c in pod.spec.containers:
        if c.name == container_name and c.resources and c.resources.limits:
            cpu_limit = c.resources.limits.get("cpu")
            if not cpu_limit:
                return None
            if cpu_limit.endswith("m"):
                return int(cpu_limit[:-1])
            return int(float(cpu_limit) * 1000)
    return None


def check_cpu_stress_recovered(
        api: CoreV1Api,
        namespace: str,
        label_selector: str,
        timeout: int = 300,
        cpu_usage_ratio_threshold: float = 0.5  # e.g., 50%
):
    """
    Check if CPU stress has recovered by ensuring all main containers
    have CPU usage below the given threshold relative to their limit.
    """
    print(f"🔍 Checking whether CPU stress has recovered "
          f"(usage ratio below {cpu_usage_ratio_threshold * 100:.0f}% for each container)...")

    # Wait until all pods become Running & Ready
    start_time = time.time()
    while time.time() - start_time < START_TIMEOUT:
        pods = get_pod_list(api, namespace, label_selector)
        if not pods:
            print("⚠️ No target pods found, waiting...")
            time.sleep(START_CHECK_INTERVAL)
            continue

        all_ready = all(check_pod_running_and_ready(pod) for pod in pods)
        if not all_ready:
            print("⏳ Some pods are not yet Running/Ready, waiting...")
            time.sleep(START_CHECK_INTERVAL)
            continue
        break

    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            # Fetch per-container CPU usage
            cmd = ["kubectl", "top", "pod", "-n", namespace, "--selector", label_selector, "--containers"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

            if result.returncode != 0:
                print(f"⚠️ Failed to execute kubectl top: {result.stderr.strip()}")
                time.sleep(INTERVAL)
                continue

            lines = result.stdout.strip().split('\n')
            if len(lines) < 2:
                print("⚠️ No metrics data available yet, waiting...")
                time.sleep(INTERVAL)
                continue

            all_cpu_normal = True

            for line in lines[1:]:
                parts = line.split()
                if len(parts) < 3:
                    continue
                pod_name, container_name, cpu_str = parts[0], parts[1], parts[2]

                if "sidecar" in container_name or "busybox" in container_name:
                    continue  # skip sidecar

                # Find the corresponding pod object
                pod = next((p for p in pods if p.metadata.name == pod_name), None)
                if not pod:
                    continue

                current_cpu_m = parse_cpu_to_millicores(cpu_str)
                limit_cpu_m = get_container_cpu_limit_millicores(pod, container_name)

                if not limit_cpu_m or limit_cpu_m == 0:
                    print(f"⚠️ {pod_name}/{container_name}: No CPU limit set (usage: {current_cpu_m}m)")
                    continue

                usage_ratio = current_cpu_m / limit_cpu_m
                print(f"📊 {pod_name}/{container_name}: {current_cpu_m}m / {limit_cpu_m}m = {usage_ratio:.1%}")

                if usage_ratio >= cpu_usage_ratio_threshold:
                    print(f"⚠️ High CPU usage detected in {pod_name}/{container_name}: "
                          f"{usage_ratio:.1%} ≥ {cpu_usage_ratio_threshold:.0%}")
                    all_cpu_normal = False

            if all_cpu_normal:
                print("✅ CPU stress recovered: all containers are within safe usage range.")
                return True

        except Exception as e:
            print(f"⚠️ Error while checking CPU usage: {e}")

        print("⏳ Still above threshold or metrics unavailable, retrying...")
        time.sleep(INTERVAL)

    print("❌ Timeout: CPU usage did not recover within expected time.")
    return False


def parse_memory_to_bytes(mem_str: str) -> int:
    """Convert kubectl top memory output (e.g., '120Mi', '1.5Gi') into bytes."""
    mem_str = mem_str.strip()
    if mem_str.endswith('Ki'):
        return int(float(mem_str[:-2]) * 1024)
    elif mem_str.endswith('Mi'):
        return int(float(mem_str[:-2]) * 1024 ** 2)
    elif mem_str.endswith('Gi'):
        return int(float(mem_str[:-2]) * 1024 ** 3)
    elif mem_str.endswith('Ti'):
        return int(float(mem_str[:-2]) * 1024 ** 4)
    elif mem_str.endswith('Pi'):
        return int(float(mem_str[:-2]) * 1024 ** 5)
    elif mem_str.endswith('Ei'):
        return int(float(mem_str[:-2]) * 1024 ** 6)
    elif mem_str.endswith('K'):
        return int(float(mem_str[:-1]) * 1000)
    elif mem_str.endswith('M'):
        return int(float(mem_str[:-1]) * 1000 ** 2)
    elif mem_str.endswith('G'):
        return int(float(mem_str[:-1]) * 1000 ** 3)
    elif mem_str.endswith('T'):
        return int(float(mem_str[:-1]) * 1000 ** 4)
    else:
        return int(mem_str)


def get_container_memory_limit_bytes(container) -> int | None:
    """Return memory limit (bytes) for a given container, or None if not defined."""
    if not container.resources or not container.resources.limits:
        return None
    mem_limit = container.resources.limits.get('memory')
    if not mem_limit:
        return None
    return parse_memory_to_bytes(mem_limit) if isinstance(mem_limit, str) else int(mem_limit)


def get_container_memory_usage_bytes(namespace: str, pod_name: str, container_name: str) -> int | None:
    """Fetch memory usage (bytes) for a specific container via 'kubectl top pod <pod> --containers'."""
    try:
        cmd = ["kubectl", "top", "pod", pod_name, "-n", namespace, "--containers"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            print(f"⚠️ Failed to get memory usage for {pod_name}/{container_name}: {result.stderr.strip()}")
            return None

        lines = result.stdout.strip().split('\n')
        for line in lines[1:]:
            parts = line.split()
            if len(parts) < 4:
                continue
            cname, cpu_str, mem_str = parts[1], parts[2], parts[3]
            if cname == container_name:
                return parse_memory_to_bytes(mem_str)
        return None
    except Exception as e:
        print(f"⚠️ Error getting container memory: {e}")
        return None


def check_memory_stress_recovered(
        api: CoreV1Api,
        namespace: str,
        label_selector: str,
        timeout: int = TIMEOUT,
        memory_usage_ratio_threshold: float = 0.5  # 50%
):
    """
    Check whether memory stress has recovered by comparing usage vs. limits
    for each non-sidecar container in all selected pods.
    """
    print(f"🔍 Checking memory recovery (threshold: {memory_usage_ratio_threshold * 100:.0f}%)...")

    # Wait for pods to be ready
    start_time = time.time()
    while time.time() - start_time < START_TIMEOUT:
        pods = get_pod_list(api, namespace, label_selector)
        if not pods:
            print("⚠️ No target pods found, waiting...")
            time.sleep(START_CHECK_INTERVAL)
            continue
        if all(check_pod_running_and_ready(p) for p in pods):
            break
        print("⏳ Waiting for pods to be Running/Ready...")
        time.sleep(START_CHECK_INTERVAL)

    # Begin monitoring memory recovery
    start_time = time.time()
    while time.time() - start_time < timeout:
        all_pods_normal = True

        pods = get_pod_list(api, namespace, label_selector)
        if not pods:
            print("⚠️ No pods found, skipping check cycle.")
            time.sleep(INTERVAL)
            continue

        for pod in pods:
            pod_name = pod.metadata.name
            try:
                pod_obj = api.read_namespaced_pod(name=pod_name, namespace=namespace)
                containers = [
                    c for c in pod_obj.spec.containers
                    if "busybox" not in c.name.lower() and "sidecar" not in c.name.lower()
                ]
                if not containers:
                    print(f"⚠️ Pod {pod_name} has no valid containers, skipping.")
                    continue

                pod_normal = True
                for container in containers:
                    limit_bytes = get_container_memory_limit_bytes(container)
                    if not limit_bytes:
                        print(f"⚠️ {pod_name}/{container.name} has no memory limit, skipping.")
                        continue

                    usage_bytes = get_container_memory_usage_bytes(namespace, pod_name, container.name)
                    if usage_bytes is None:
                        print(f"⚠️ Failed to get usage for {pod_name}/{container.name}.")
                        pod_normal = False
                        continue

                    usage_ratio = usage_bytes / limit_bytes
                    print(f"📊 {pod_name}/{container.name}: {usage_bytes / (1024 ** 2):.1f}MB / "
                          f"{limit_bytes / (1024 ** 2):.1f}MB = {usage_ratio:.1%}")

                    if usage_ratio >= memory_usage_ratio_threshold:
                        print(f"⚠️ High usage: {usage_ratio:.1%} ≥ {memory_usage_ratio_threshold:.0%}")
                        pod_normal = False

                if not pod_normal:
                    all_pods_normal = False

            except Exception as e:
                print(f"⚠️ Error checking Pod {pod_name}: {e}")
                all_pods_normal = False

        if all_pods_normal:
            print("✅ Memory stress has fully recovered!")
            return True

        time.sleep(INTERVAL)

    print("❌ Timeout: memory stress not fully recovered.")
    return False


def check_pod_ready_recovered(api, namespace, label_selector, timeout: int = START_TIMEOUT):
    """Check whether Pods have recovered from NotReady to Ready state."""
    print("🔍 Checking if Pods have recovered to Ready state...")
    start_time = time.time()

    while time.time() - start_time < timeout:
        pods = get_pod_list(api, namespace, label_selector)
        if not pods:
            print("⚠️ No target Pods found, waiting...")
            time.sleep(START_CHECK_INTERVAL)
            continue

        all_ready = True
        for pod in pods:
            ready = check_pod_running_and_ready(pod)
            if not ready:
                print(f"⚠️ Pod {pod.metadata.name} is NotReady")
                all_ready = False

        if all_ready:
            # 🔹 All Pods are Ready; now verify that metrics are available
            print("✅ All Pods are in Running & Ready state. Checking metrics availability...")

            try:
                result = subprocess.run(
                    ["kubectl", "top", "pod", "-n", namespace, "-l", label_selector],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=10
                )
                output = result.stdout + result.stderr

                if "error: metrics not available" in output:
                    print("⚠️ Metrics are not yet available, waiting...")
                elif "No resources found" in output:
                    print("⚠️ metrics-server returned empty results, waiting...")
                elif result.returncode != 0:
                    print(f"⚠️ Failed to retrieve metrics: {output.strip()}")
                else:
                    print("✅ Metrics are accessible. Pods have fully recovered!")
                    return True

            except subprocess.TimeoutExpired:
                print("⚠️ Metrics retrieval timed out, retrying...")

        time.sleep(START_CHECK_INTERVAL)

    print("❌ Timeout: Pods have not all become Ready within the allowed time.")
    return False


def check_ping_latency_recovered(
        api,
        namespace,
        label_selector,
        timeout: int = TIMEOUT,
        max_latency_ms=1000,
        max_loss_percent=0
):
    """
    Verify network recovery by probing latency and packet loss via ping.
    All matching Pods must meet the criteria (latency ≤ max_latency_ms and packet loss ≤ max_loss_percent)
    for the check to be considered successful.
    """
    print("🔍 Checking network recovery based on ping latency and packet loss...")

    # Wait for all Pods to become Running/Ready
    start_time = time.time()
    while time.time() - start_time < START_TIMEOUT:
        pods = get_pod_list(api, namespace, label_selector)
        if not pods:
            print("⚠️ No target Pods found, waiting...")
            time.sleep(START_CHECK_INTERVAL)
            continue
        if all(check_pod_running_and_ready(p) for p in pods):
            break
        print("⏳ Not all Pods are Running/Ready yet, continuing to wait...")
        time.sleep(START_CHECK_INTERVAL)

    # Probe ping metrics for each Pod
    start_time = time.time()
    while time.time() - start_time < timeout:
        pods = get_pod_list(api, namespace, label_selector)
        if not pods:
            print("⚠️ No target Pods found, waiting...")
            time.sleep(INTERVAL)
            continue

        all_ok = True
        for pod in pods:
            pod_name = pod.metadata.name
            # Prefer the main container for ping
            cmd = ["kubectl", "exec", pod_name, "-n", namespace, "--", "ping", "-c", "3", "-W", "2", "8.8.8.8"]

            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                output = (result.stdout + result.stderr).strip()

                # If ping is unavailable in the main container, fall back to a sidecar (e.g., sidecar-busybox)
                if "executable file not found" in output or "OCI runtime exec failed" in output:
                    cmd = [
                        "kubectl", "exec", pod_name, "-c", "sidecar-busybox", "-n", namespace, "--",
                        "ping", "-c", "3", "-W", "2", "8.8.8.8"
                    ]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                    output = result.stdout.strip()

                if result.returncode != 0 and "100% packet loss" not in output:
                    print(f"⚠️ Ping command failed for {pod_name}: {result.stderr.strip()}")
                    all_ok = False
                    continue

                # Parse packet loss percentage
                packet_loss_percent = 100
                for line in output.split('\n'):
                    if "packet loss" in line and "transmitted" in line:
                        try:
                            packet_loss_percent = float(line.split(",")[2].strip().split("%")[0])
                        except (IndexError, ValueError):
                            packet_loss_percent = 100
                        break
                if packet_loss_percent > max_loss_percent:
                    print(f"🔴 Packet loss too high for {pod_name}: {packet_loss_percent}% > {max_loss_percent}%")
                    all_ok = False
                    continue

                # Parse average round-trip latency
                avg_latency = None
                for line in output.split('\n'):
                    if "round-trip min/avg/max" in line or "rtt min/avg/max" in line:
                        try:
                            time_part = line.split("=")[1].strip().split()[0]
                            avg_latency = float(time_part.split("/")[1])
                        except (IndexError, ValueError):
                            avg_latency = None
                        break
                if avg_latency is None or avg_latency > max_latency_ms:
                    print(f"⚠️ Latency too high or parsing failed for {pod_name}: {avg_latency} ms")
                    all_ok = False
                    continue

            except Exception as e:
                print(f"❌ Ping probe failed for {pod_name}: {e}")
                all_ok = False

        if all_ok:
            print("✅ Network has recovered for all Pods (packet loss and latency within thresholds).")
            return True

        time.sleep(INTERVAL)

    print("❌ Timeout: Network latency and/or packet loss did not recover within the allowed time.")
    return False


def check_disk_io_performance(
        api,
        namespace,
        label_selector,
        timeout: int = TIMEOUT,
        min_write_speed_mb=10
):
    """
    Assess disk write performance by writing a test file in each Pod.
    Recovery is confirmed only when all matching Pods meet the minimum write speed threshold.
    """
    print("🔍 Checking if disk write performance has recovered...")

    # Wait for all Pods to become Running/Ready
    start_time = time.time()
    while time.time() - start_time < START_TIMEOUT:
        pods = get_pod_list(api, namespace, label_selector)
        if not pods:
            print("⚠️ No target Pods found, waiting...")
            time.sleep(START_CHECK_INTERVAL)
            continue
        if all(check_pod_running_and_ready(p) for p in pods):
            break
        print("⏳ Not all Pods are Running/Ready yet, continuing to wait...")
        time.sleep(START_CHECK_INTERVAL)

    # Perform disk write test on each Pod
    start_time = time.time()
    while time.time() - start_time < timeout:
        pods = get_pod_list(api, namespace, label_selector)
        if not pods:
            print("⚠️ No target Pods found, waiting...")
            time.sleep(INTERVAL)
            continue

        all_ok = True
        for pod in pods:
            pod_name = pod.metadata.name
            cmd = [
                "kubectl", "exec", pod_name, "-n", namespace, "--",
                "sh", "-c",
                "time_start=$(date +%s%3N); "
                "dd if=/dev/zero of=/var/log/mysql/test-disk-write.tmp bs=1M count=10 oflag=direct 2>&1; "
                "time_end=$(date +%s%3N); "
                "echo $((time_end - time_start))"
            ]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=INTERVAL)
                output = result.stdout.strip()
                if not output:
                    print(f"⚠️ No output from {pod_name}; execution may have failed")
                    all_ok = False
                    continue

                duration_ms = int(output.split('\n')[-1])
                if duration_ms == 0:
                    duration_ms = 1  # Avoid division by zero
                speed = 10 / (duration_ms / 1000)  # MB/s

                if speed < min_write_speed_mb:
                    print(f"⚠️ Write speed too low for {pod_name}: {speed:.2f} MB/s < {min_write_speed_mb} MB/s")
                    all_ok = False
                    continue

                # Clean up the test file
                subprocess.run(
                    ["kubectl", "exec", pod_name, "-n", namespace, "--",
                     "rm", "-f", "/var/log/mysql/test-disk-write.tmp"],
                    timeout=INTERVAL
                )
            except Exception as e:
                print(f"❌ Disk write test failed for {pod_name}: {e}")
                all_ok = False

        if all_ok:
            print("✅ Disk write performance has recovered for all Pods.")
            return True

        time.sleep(INTERVAL)

    print("❌ Timeout: Disk write performance did not recover within the allowed time.")
    return False


def check_config_error_recovered(
        api: CoreV1Api,
        namespace: str,
        label_selector: str,
        timeout: int = TIMEOUT
):
    if timeout > 0:
        return check_cpu_stress_recovered(api, namespace, label_selector, timeout) \
            and check_memory_stress_recovered(api, namespace, label_selector, timeout)
    else:
        return check_cpu_stress_recovered(api, namespace, label_selector) \
            and check_memory_stress_recovered(api, namespace, label_selector)


def check(namespace, label, type, timeout=0):
    KUBECONFIG_PATH = "/etc/rancher/k3s/k3s.yaml"
    config.load_kube_config(config_file=KUBECONFIG_PATH)
    api = client.CoreV1Api()

    if type in failures.failures:
        if timeout > 0:
            success = {
                "cpu-stress": check_cpu_stress_recovered,
                "memory-stress": check_memory_stress_recovered,
                "pod-fail": check_pod_ready_recovered,
                "network-loss": check_ping_latency_recovered,
                "network-delay": check_ping_latency_recovered,
                "disk-io": check_disk_io_performance,
                "pod-config-error": check_config_error_recovered
            }[type](api, namespace, label, timeout)
        else:
            success = {
                "cpu-stress": check_cpu_stress_recovered,
                "memory-stress": check_memory_stress_recovered,
                "pod-fail": check_pod_ready_recovered,
                "network-loss": check_ping_latency_recovered,
                "network-delay": check_ping_latency_recovered,
                "disk-io": check_disk_io_performance,
                "pod-config-error": check_config_error_recovered
            }[type](api, namespace, label)
        return success
    return False
