kubectl delete stresschaos cpu-stress -n $1
kubectl delete stresschaos memory-stress -n $1
kubectl delete podchaos pod-fail -n $1
kubectl delete networkchaos network-loss -n $1
kubectl delete networkchaos network-delay -n $1
timeout 5s kubectl delete iochaos disk-io -n $1 || kubectl patch iochaos disk-io -p '{"metadata":{"finalizers":[]}}' --type=merge -n $1