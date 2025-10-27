helm repo add chaos-mesh https://charts.chaos-mesh.org
kubectl create ns chaos-mesh
helm list -n chaos-mesh -q | xargs -r -n1 helm uninstall -n chaos-mesh
helm install chaos-mesh chaos-mesh/chaos-mesh -n=chaos-mesh --set chaosDaemon.runtime=containerd --set chaosDaemon.socketPath=/run/k3s/containerd/containerd.sock --version 2.7.3
kubectl get pods -n chaos-mesh -l app.kubernetes.io/instance=chaos-mesh