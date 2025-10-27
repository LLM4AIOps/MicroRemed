curl –sfL https://rancher-mirror.rancher.cn/k3s/k3s-install.sh | INSTALL_K3S_MIRROR=cn sh -s - --system-default-registry "registry.cn-hangzhou.aliyuncs.com"
sudo systemctl enable k3s
sudo systemctl start k3s
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $(id -u):$(id -g) ~/.kube/config
cat > "/etc/rancher/k3s/registries.yaml" <<EOF
mirrors:
  docker.io:
    endpoint:
      - "https://docker.m.daocloud.io"
EOF
sudo systemctl restart k3s
sudo snap install helm --classic
echo "K3s and Helm CLI installed successfully!"