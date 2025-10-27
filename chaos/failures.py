failures = [
    "cpu-stress",
    "memory-stress",
    "pod-fail",
    "network-loss",
    "network-delay",
    "disk-io",
    "pod-config-error"
]

stop_chaos = {
    "cpu-stress": "kubectl delete stresschaos cpu-stress -n [target_namespace]",
    "memory-stress": "kubectl delete stresschaos memory-stress -n [target_namespace]",
    "pod-fail": "kubectl delete podchaos pod-fail -n [target_namespace]",
    "network-loss": "kubectl delete networkchaos network-loss -n [target_namespace]",
    "network-delay": "kubectl delete networkchaos network-delay -n [target_namespace]",
    "disk-io": "timeout 5s kubectl delete iochaos disk-io -n [target_namespace] || kubectl patch iochaos disk-io -p '{\"metadata\":{\"finalizers\":[]}}' --type=merge -n [target_namespace]",
    "pod-config-error": ""
}
