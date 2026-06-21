#!/bin/bash

# --- Configuration ---
REQUIRED_PACKAGES=(vim tree jq curl wget net-tools iputils-ping iperf3 htop git unzip qemu-guest-agent containerd)
LOG_FILE="/var/log/k8s_template_prep.log"

# --- Helper Functions ---
info() { echo -e "\e[32m[INFO]\e[0m $1"; }
warn() { echo -e "\e[33m[WARN]\e[0m $1"; }
error() { echo -e "\e[31m[ERROR]\e[0m $1"; exit 1; }

# Ensure script is run as root
if [[ $EUID -ne 0 ]]; then
   error "This script must be run as root (use sudo)"
fi

exec > >(tee -i $LOG_FILE) 2>&1

info "Starting K8s-Ready Template Hardening & Sanitization..."

# 1. Install missing packages
info "Updating package lists and installing required tools..."
apt-get update || warn "Apt update failed, attempting to continue..."

for pkg in "${REQUIRED_PACKAGES[@]}"; do
    if dpkg -l | grep -q "ii  $pkg "; then
        info "Package '$pkg' already exists. Skipping."
    else
        info "Installing '$pkg'..."
        apt-get install -y "$pkg" || error "Failed to install $pkg"
    fi
done

# 2. Containerd Configuration (Cgroup driver fix)
info "Configuring containerd for Kubernetes..."
mkdir -p /etc/containerd
containerd config default | tee /etc/containerd/config.toml > /dev/null
# Set SystemdCgroup to true (K8s requirement)
sed -i 's/SystemdCgroup = false/SystemdCgroup = true/g' /etc/containerd/config.toml
systemctl restart containerd
systemctl enable containerd

# 3. Apply Kubernetes Prep (Swap & Kernel)
info "Disabling swap and configuring kernel modules..."
swapoff -a
sed -i '/ swap / s/^\(.*\)$/#\1/g' /etc/fstab

cat <<EOF > /etc/modules-load.d/k8s.conf
overlay
br_netfilter
EOF

modprobe overlay
modprobe br_netfilter

# Sysctl requirements for K8s networking
cat <<EOF > /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOF
sysctl --system > /dev/null

# 4. QEMU Guest Agent & Vim Defaults
info "Hardening QEMU Guest Agent and setting Vim..."
update-alternatives --set editor /usr/bin/vim.basic || warn "Could not set default editor"

mkdir -p /etc/systemd/system/qemu-guest-agent.service.d/
cat <<EOF > /etc/systemd/system/qemu-guest-agent.service.d/override.conf
[Service]
Restart=always
RestartSec=5
EOF
systemctl daemon-reload
systemctl enable qemu-guest-agent

# 5. Cloud-Init & Networking Fixes
info "Configuring Cloud-Init and IPv4 priority..."
# Append ssh_genkeytypes ONLY if not already present
if ! grep -q "ssh_genkeytypes" /etc/cloud/cloud.cfg; then
    echo "ssh_genkeytypes: ['rsa', 'ecdsa', 'ed25519']" >> /etc/cloud/cloud.cfg
fi
rm -f /etc/cloud/cloud.cfg.d/99-installer.cfg
echo 'Acquire::ForceIPv4 "true";' > /etc/apt/apt.conf.d/99force-ipv4

# 6. Deep Sanitization (The "Blank Slate" steps)
info "Sanitizing VM identity..."
rm -f /etc/ssh/ssh_host_*
truncate -s 0 /etc/machine-id
rm -f /var/lib/dbus/machine-id
ln -s /etc/machine-id /var/lib/dbus/machine-id

apt-get autoremove --purge -y && apt-get clean
find /var/log -type f -exec truncate -s 0 {} \;
cloud-init clean --logs

info "K8s Template ready. Powering off in 5 seconds..."
sleep 5
history -c && history -w
poweroff
