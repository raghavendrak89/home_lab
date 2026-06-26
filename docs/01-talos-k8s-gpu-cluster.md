# Talos Kubernetes Cluster — Complete Build Guide

> This document covers the full journey of building a 3-node control plane + 1 GPU worker Kubernetes cluster
> on Proxmox using Talos Linux. It includes every issue encountered and the exact fixes applied.
> Follow this guide if rebuilding from scratch or adding new nodes.

---

## What We Built

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Proxmox Cluster                              │
│                                                                     │
│  pve-node-01 (192.168.0.13)     pve-node-02 (192.168.0.14)         │
│  ┌──────────────────────┐       ┌──────────────────────┐           │
│  │  talos-cp-01 (VM105) │       │  talos-cp-02 (VM106) │           │
│  │  192.168.0.110       │       │  192.168.0.111       │           │
│  │  2vCPU / 4GB / 20GB  │       │  2vCPU / 4GB / 20GB  │           │
│  │  Control Plane       │       │  Control Plane       │           │
│  └──────────────────────┘       └──────────────────────┘           │
│  ┌──────────────────────┐       ┌──────────────────────┐           │
│  │  talos-worker-01     │       │  talos-worker-02     │           │
│  │  (VM108)             │       │  (VM109)             │           │
│  │  192.168.0.114       │       │  192.168.0.115       │           │
│  │  4vCPU / 8GB / 50GB  │       │  4vCPU / 8GB / 50GB  │           │
│  │  Worker              │       │  Worker              │           │
│  └──────────────────────┘       └──────────────────────┘           │
│                                                                     │
│  pve-ai-01 (192.168.0.11)                                           │
│  ┌──────────────────────┐       ┌──────────────────────┐           │
│  │  talos-cp-03 (VM107) │       │  talos-gpu-worker    │           │
│  │  192.168.0.112       │       │  (VM125)             │           │
│  │  2vCPU / 4GB / 20GB  │       │  192.168.0.113       │           │
│  │  Control Plane       │       │  8vCPU / 48GB / 200GB│           │
│  └──────────────────────┘       │  RTX 3090 (PCIe PT)  │           │
│                                 └──────────────────────┘           │
│                                                                     │
│  Cluster VIP: 192.168.0.100:6443 (kube-vip)                        │
└─────────────────────────────────────────────────────────────────────┘
```

**Talos version:** v1.13.3
**Kubernetes version:** v1.36.1 (bundled with Talos)
**GPU:** NVIDIA RTX 3090 (24GB VRAM) via PCIe passthrough
**NVIDIA Talos schematic:** `6eb33b9811189e6859ee90bc1a5903e8baa8b86dba91a3c43fbd2ec76380e2c5`
(extensions: `nonfree-kmod-nvidia-lts` + `nvidia-container-toolkit`)

### Node Map

| K8s Node | IP | Proxmox Host | VMID | Role | MAC |
|---|---|---|---|---|---|
| talos-2j2-s88 | 192.168.0.110 | pve-node-01 | 105 | control-plane | `BC:24:11:FA:56:D7` |
| talos-nqx-4u7 | 192.168.0.111 | pve-node-02 | 106 | control-plane | `BC:24:11:23:7B:91` |
| talos-i8m-1mm | 192.168.0.112 | pve-ai-01 | 107 | control-plane | `BC:24:11:EA:9E:1D` |
| talos-zlt-fqg | 192.168.0.113 | pve-ai-01 | 125 | gpu-worker | `BC:24:11:23:53:2E` |
| talos-76j-w0h | 192.168.0.114 | pve-node-01 | 108 | worker | `BC:24:11:50:5D:0D` |
| talos-97a-ilz | 192.168.0.115 | pve-node-02 | 109 | worker | `BC:24:11:40:AB:62` |

> **Note on hostnames:** Talos auto-generates hostnames from machine identity. If you wipe STATE on a node,
> it gets a new identity and a new hostname. The cp-03 hostname changed from original after a full reset.

### Infrastructure Host Map

| Host | Role | IP | MAC |
|---|---|---|---|
| pve-node-01 | Proxmox hypervisor | 192.168.0.13 | `d0:8e:79:15:0e:28` |
| pve-node-02 | Proxmox hypervisor | 192.168.0.14 | `d0:8e:79:15:0e:4c` |
| pve-ai-01 | Proxmox hypervisor (GPU) | 192.168.0.11 | `74:86:e2:04:c1:ea` |
| lab-eye (VM111) | Proxmox MCP server | 192.168.0.134 | `BC:24:11:ED:71:E1` |
| kube-vip | K8s API VIP (floating) | 192.168.0.100 | N/A — no fixed MAC |

### DHCP Reservation Notes (Tenda router)

All IPs above must be reserved via **Address Reservation** on the Tenda router (`192.168.0.1`).

**Important:** Change DHCP pool from `100~200` → `101~200` to protect the kube-vip address
(`.100`) from being handed to a random device. kube-vip uses `.100` as a floating L2 VIP —
it has no fixed MAC, so it cannot be reserved; it must simply be outside the pool.

---

## Prerequisites — Mac

```bash
brew install siderolabs/tap/talosctl
brew install kubectl
brew install helm
```

### IMPORTANT: talosctl must run from pve-node-01, not your Mac

Due to Tailscale routing on this network, `talosctl` cannot reach the Talos API (port 50000)
from the Mac directly. All `talosctl` commands in this guide must be run via SSH on pve-node-01:

```bash
ssh root@192.168.0.13
export TALOSCONFIG=/root/talos-cluster/configs/talosconfig
```

`kubectl` works fine from your Mac via the VIP (192.168.0.100:6443). Copy kubeconfig to your Mac:
```bash
scp root@192.168.0.13:/root/talos-cluster/configs/kubeconfig ~/.kube/config
```

---

## Phase 1 — Download ISOs to Proxmox Nodes

SSH to each Proxmox node and download the ISO.

### pve-node-01
```bash
ssh root@192.168.0.13
wget -O /var/lib/vz/template/iso/talos-v1.13.3-metal-amd64.iso \
  https://github.com/siderolabs/talos/releases/download/v1.13.3/metal-amd64.iso
```

### pve-node-02
```bash
ssh root@192.168.0.14
wget -O /var/lib/vz/template/iso/talos-v1.13.3-metal-amd64.iso \
  https://github.com/siderolabs/talos/releases/download/v1.13.3/metal-amd64.iso
```

### pve-ai-01 (needs two ISOs)
```bash
ssh root@192.168.0.11

# Standard ISO for talos-cp-03
wget -O /var/lib/vz/template/iso/talos-v1.13.3-metal-amd64.iso \
  https://github.com/siderolabs/talos/releases/download/v1.13.3/metal-amd64.iso

# NVIDIA factory ISO for GPU worker (includes nvidia drivers baked in)
wget -O /var/lib/vz/template/iso/talos-v1.13.3-nvidia-metal-amd64.iso \
  "https://factory.talos.dev/image/6eb33b9811189e6859ee90bc1a5903e8baa8b86dba91a3c43fbd2ec76380e2c5/v1.13.3/metal-amd64.iso"
```

> **What is the NVIDIA ISO?**
> Built via https://factory.talos.dev — a custom Talos image with two system extensions pre-installed:
> - `nonfree-kmod-nvidia-lts` — NVIDIA LTS kernel driver (supports RTX 3090)
> - `nvidia-container-toolkit` — Makes containers GPU-aware (replaces apt install nvidia-docker2)
>
> The schematic ID `6eb33b98...` encodes exactly which extensions to include.
> Without this, the GPU is invisible to Kubernetes even with PCIe passthrough working.

---

## Phase 2 — Create Control Plane VMs

### talos-cp-01 on pve-node-01 (VMID 105)
```bash
ssh root@192.168.0.13

qm create 105 \
  --name talos-cp-01 \
  --memory 4096 \
  --cores 2 \
  --cpu host \
  --machine q35 \
  --bios ovmf \
  --efidisk0 local-lvm:0,efitype=4m,pre-enrolled-keys=0 \
  --scsihw virtio-scsi-single \
  --scsi0 local-lvm:20,format=raw \
  --ide2 local:iso/talos-v1.13.3-metal-amd64.iso,media=cdrom \
  --boot "order=ide2;scsi0" \
  --net0 virtio,bridge=vmbr0 \
  --ostype l26

qm start 105
```

### talos-cp-02 on pve-node-02 (VMID 106)
```bash
ssh root@192.168.0.14

qm create 106 \
  --name talos-cp-02 \
  --memory 4096 \
  --cores 2 \
  --cpu host \
  --machine q35 \
  --bios ovmf \
  --efidisk0 local-lvm:0,efitype=4m,pre-enrolled-keys=0 \
  --scsihw virtio-scsi-single \
  --scsi0 local-lvm:20,format=raw \
  --ide2 local:iso/talos-v1.13.3-metal-amd64.iso,media=cdrom \
  --boot "order=ide2;scsi0" \
  --net0 virtio,bridge=vmbr0 \
  --ostype l26

qm start 106
```

### talos-cp-03 on pve-ai-01 (VMID 107)
```bash
ssh root@192.168.0.11

qm create 107 \
  --name talos-cp-03 \
  --memory 4096 \
  --cores 2 \
  --cpu host \
  --machine q35 \
  --bios ovmf \
  --efidisk0 local-lvm:0,efitype=4m,pre-enrolled-keys=0 \
  --scsihw virtio-scsi-single \
  --scsi0 local-lvm:20,format=raw \
  --ide2 local:iso/talos-v1.13.3-metal-amd64.iso,media=cdrom \
  --boot "order=ide2;scsi0" \
  --net0 virtio,bridge=vmbr0 \
  --ostype l26

qm start 107
```

### GPU Worker on pve-ai-01 (VMID 125)

The GPU worker VM already existed as `ai-compute-core`. We repurposed it:
```bash
ssh root@192.168.0.11

qm stop 125
qm set 125 --name talos-gpu-worker

# Swap ISO to NVIDIA version
qm set 125 --ide2 local:iso/talos-v1.13.3-nvidia-metal-amd64.iso,media=cdrom

# Boot from CDROM first
qm set 125 --boot "order=ide2;virtio0"

# Verify GPU passthrough is still configured
qm config 125 | grep hostpci
# Expected: hostpci0: 0000:65:00,pcie=1

qm start 125
```

After each VM boots, open the Proxmox console to see the Talos maintenance screen showing the DHCP IP.
You will need these IPs in the next phase.

---

## Phase 3 — Generate Talos Configuration (on pve-node-01)

```bash
ssh root@192.168.0.13
mkdir -p /root/talos-cluster/configs
cd /root/talos-cluster

talosctl gen config homelab-k8s https://192.168.0.100:6443 \
  --output-dir ./configs
```

This creates:
- `configs/controlplane.yaml` — base config for all CP nodes
- `configs/worker.yaml` — base config for all worker nodes
- `configs/talosconfig` — client credentials for talosctl

### Create patch files

**cp-01-patch.yaml**
```yaml
machine:
  network:
    interfaces:
      - interface: ens18
        addresses:
          - 192.168.0.110/24
        routes:
          - network: 0.0.0.0/0
            gateway: 192.168.0.1
        dhcp: false
    nameservers:
      - 192.168.0.1
      - 8.8.8.8
```

**cp-02-patch.yaml**
```yaml
machine:
  network:
    interfaces:
      - interface: ens18
        addresses:
          - 192.168.0.111/24
        routes:
          - network: 0.0.0.0/0
            gateway: 192.168.0.1
        dhcp: false
    nameservers:
      - 192.168.0.1
      - 8.8.8.8
```

**cp-03-patch.yaml**
```yaml
machine:
  network:
    interfaces:
      - interface: ens18
        addresses:
          - 192.168.0.112/24
        routes:
          - network: 0.0.0.0/0
            gateway: 192.168.0.1
        dhcp: false
    nameservers:
      - 192.168.0.1
      - 8.8.8.8
```

**gpu-worker-patch.yaml**
```yaml
machine:
  install:
    disk: /dev/vda
    image: factory.talos.dev/installer/6eb33b9811189e6859ee90bc1a5903e8baa8b86dba91a3c43fbd2ec76380e2c5:v1.13.3
  network:
    interfaces:
      - interface: ens18
        addresses:
          - 192.168.0.113/24
        routes:
          - network: 0.0.0.0/0
            gateway: 192.168.0.1
        dhcp: false
    nameservers:
      - 192.168.0.1
      - 8.8.8.8
  kernel:
    modules:
      - name: nvidia
      - name: nvidia_uvm
      - name: nvidia_drm
      - name: nvidia_modeset
```

> **Why `machine.install.image` on the GPU worker only?**
> Control plane nodes use the standard Talos installer image embedded in the ISO.
> The GPU worker needs the factory image with NVIDIA extensions baked in — if you don't set this,
> Talos will reinstall with the standard image on next upgrade and lose the NVIDIA extensions.
>
> **Why `kernel.modules`?**
> Talos does not auto-load kernel modules. Without these 4 lines, the NVIDIA driver is installed
> but the GPU is never initialized — it stays invisible to Kubernetes.

---

## Phase 4 — Apply Configs and Bootstrap

Replace `<DHCP_IP_*>` with the IPs from the Talos console screens.

```bash
# On pve-node-01
export TALOSCONFIG=/root/talos-cluster/configs/talosconfig
cd /root/talos-cluster

# Apply to control plane nodes (--insecure because no certs yet — maintenance mode)
talosctl apply-config \
  --nodes <DHCP_IP_CP01> \
  --file configs/controlplane.yaml \
  --config-patch @cp-01-patch.yaml \
  --insecure

talosctl apply-config \
  --nodes <DHCP_IP_CP02> \
  --file configs/controlplane.yaml \
  --config-patch @cp-02-patch.yaml \
  --insecure

talosctl apply-config \
  --nodes <DHCP_IP_CP03> \
  --file configs/controlplane.yaml \
  --config-patch @cp-03-patch.yaml \
  --insecure

# Apply to GPU worker
talosctl apply-config \
  --nodes <DHCP_IP_WORKER> \
  --file configs/worker.yaml \
  --config-patch @gpu-worker-patch.yaml \
  --insecure
```

Each node reboots, installs Talos to disk, comes back up at the static IP. Wait ~90 seconds.

### Bootstrap etcd (once, on one CP node only)

```bash
talosctl config endpoint 192.168.0.110
talosctl config node 192.168.0.110

# This starts etcd and the Kubernetes control plane — run ONCE and ONLY ONCE
talosctl bootstrap --nodes 192.168.0.110
```

> **Warning:** Running bootstrap twice breaks etcd. Only ever run it on a fresh cluster.

### Wait for cluster health

```bash
talosctl health \
  --nodes 192.168.0.110,192.168.0.111,192.168.0.112 \
  --control-plane-nodes 192.168.0.110,192.168.0.111,192.168.0.112 \
  --worker-nodes 192.168.0.113
```

### Get kubeconfig

```bash
# On pve-node-01
talosctl kubeconfig ./configs/kubeconfig --nodes 192.168.0.110

# On your Mac (copy it over)
scp root@192.168.0.13:/root/talos-cluster/configs/kubeconfig ~/.kube/config

kubectl get nodes -o wide
```

Expected:
```
NAME            STATUS   ROLES           AGE   VERSION   INTERNAL-IP
talos-2j2-s88   Ready    control-plane   3m    v1.36.1   192.168.0.110
talos-nqx-4u7   Ready    control-plane   3m    v1.36.1   192.168.0.111
talos-i8m-1mm   Ready    control-plane   3m    v1.36.1   192.168.0.112
talos-zlt-fqg   Ready    <none>          3m    v1.36.1   192.168.0.113
```

---

## Phase 5 — Install kube-vip (HA Control Plane VIP)

kube-vip provides the floating VIP (192.168.0.100) so kubectl works even if one CP node is down.

```bash
# Apply RBAC first
kubectl apply -f https://kube-vip.io/manifests/rbac.yaml
```

Save this as `/Users/raghavendra/homelab/k8s/kube-vip.yaml` and apply:
```bash
kubectl apply -f /Users/raghavendra/homelab/k8s/kube-vip.yaml
```

Then update kubeconfig to use the VIP:
```bash
kubectl config set-cluster homelab-k8s --server=https://192.168.0.100:6443
kubectl get nodes   # verify it works through the VIP
```

---

## Phase 6 — NVIDIA GPU Setup

### Apply containerd CRI config (machine.files)

The NVIDIA device plugin needs `default_runtime_name = "nvidia"` in containerd's config.
**This MUST be generated with Python** — shell heredocs strip double-quotes from TOML.

On pve-node-01:
```bash
python3 << 'PYEOF'
import yaml

content = '[plugins."io.containerd.cri.v1.runtime".containerd]\n  default_runtime_name = "nvidia"\n'
patch = {
    "machine": {
        "files": [{
            "path": "/etc/cri/conf.d/20-customization.part",
            "content": content,
            "op": "create",
            "permissions": 0
        }]
    }
}
with open("/tmp/cri-patch.yaml", "w") as f:
    yaml.dump(patch, f, default_flow_style=False, allow_unicode=True)

print("Generated /tmp/cri-patch.yaml")
PYEOF

cat /tmp/cri-patch.yaml   # verify quotes are preserved as \"
```

Expected output (quotes preserved):
```yaml
machine:
  files:
  - content: "[plugins.\"io.containerd.cri.v1.runtime\".containerd]\n  default_runtime_name\
      \ = \"nvidia\"\n"
    op: create
    path: /etc/cri/conf.d/20-customization.part
    permissions: 0
```

Apply both patches to the GPU worker:
```bash
talosctl apply-config \
  --nodes 192.168.0.113 \
  --file configs/worker.yaml \
  -p @gpu-worker-patch.yaml \
  -p @/tmp/cri-patch.yaml
```

Node reboots. Wait ~90 seconds.

### Install NVIDIA Device Plugin

```bash
helm repo add nvdp https://nvidia.github.io/k8s-device-plugin
helm repo update

helm install nvdp nvdp/nvidia-device-plugin \
  --namespace kube-system \
  --version 0.17.0
```

### Verify GPU visible to Kubernetes

```bash
kubectl describe node talos-zlt-fqg | grep -A5 "Capacity"
# Should show: nvidia.com/gpu: 1

kubectl get node talos-zlt-fqg -o jsonpath='{.status.capacity.nvidia\.com/gpu}'
# Should output: 1
```

---

## Phase 7 — Deploy AI Stack

All manifests stored at `/Users/raghavendra/homelab/k8s/ai/`.

### Namespace (with privileged PodSecurity)

```bash
kubectl apply -f /Users/raghavendra/homelab/k8s/ai/namespace.yaml
```

### Ollama (GPU-pinned)

```bash
kubectl apply -f /Users/raghavendra/homelab/k8s/ai/ollama.yaml
```

Models are stored at `hostPath: /var/local/ollama-models` on the GPU worker's NVMe disk.
They survive pod restarts as long as the node is alive.

### Open WebUI

```bash
kubectl apply -f /Users/raghavendra/homelab/k8s/ai/open-webui.yaml
```

Access at: `http://192.168.0.113:30080`

### Pull models

Via kubectl exec:
```bash
kubectl exec -n ai -it deploy/ollama -- ollama pull gemma2:9b
kubectl exec -n ai -it deploy/ollama -- ollama pull qwen2.5-coder:32b
kubectl exec -n ai -it deploy/ollama -- ollama pull gemma2:27b
kubectl exec -n ai -it deploy/ollama -- ollama pull deepseek-r1:32b
```

Or via Open WebUI → Settings → Models → pull by name.

### Recommended models per family member

| User | Model | Reason |
|---|---|---|
| Raghavendra | `qwen2.5-coder:32b` | Best for coding/debugging |
| Raghavendra | `deepseek-r1:32b` | Best for complex reasoning |
| Wife | `gemma2:27b` | General assistant, excellent quality |
| Daughter (age 7) | `gemma2:9b` | Fast, friendly, low-latency |

> **Concurrency:** Ollama loads one model in VRAM at a time. Switching models takes 30-60s.
> Multiple users on the same model → requests queue automatically (no data mixing).

---

## Phase 8 — Adding Plain Worker Nodes

To run regular (non-GPU) apps, add worker VMs to pve-node-01 and pve-node-02.

### Create worker VMs

**talos-worker-01 on pve-node-01 (VMID 108)**
```bash
ssh root@192.168.0.13

qm create 108 \
  --name talos-worker-01 \
  --memory 8192 \
  --cores 4 \
  --cpu host \
  --machine q35 \
  --bios ovmf \
  --efidisk0 local-lvm:0,efitype=4m,pre-enrolled-keys=0 \
  --scsihw virtio-scsi-single \
  --scsi0 local-lvm:50,format=raw \
  --ide2 local:iso/talos-v1.13.3-metal-amd64.iso,media=cdrom \
  --boot "order=ide2;scsi0" \
  --net0 virtio,bridge=vmbr0 \
  --ostype l26

qm start 108
```

**talos-worker-02 on pve-node-02 (VMID 109)**
```bash
ssh root@192.168.0.14

qm create 109 \
  --name talos-worker-02 \
  --memory 8192 \
  --cores 4 \
  --cpu host \
  --machine q35 \
  --bios ovmf \
  --efidisk0 local-lvm:0,efitype=4m,pre-enrolled-keys=0 \
  --scsihw virtio-scsi-single \
  --scsi0 local-lvm:50,format=raw \
  --ide2 local:iso/talos-v1.13.3-metal-amd64.iso,media=cdrom \
  --boot "order=ide2;scsi0" \
  --net0 virtio,bridge=vmbr0 \
  --ostype l26

qm start 109
```

### Create worker patch files

**worker-01-patch.yaml**
```yaml
machine:
  network:
    interfaces:
      - interface: ens18
        addresses:
          - 192.168.0.114/24
        routes:
          - network: 0.0.0.0/0
            gateway: 192.168.0.1
        dhcp: false
    nameservers:
      - 192.168.0.1
      - 8.8.8.8
```

**worker-02-patch.yaml**
```yaml
machine:
  network:
    interfaces:
      - interface: ens18
        addresses:
          - 192.168.0.115/24
        routes:
          - network: 0.0.0.0/0
            gateway: 192.168.0.1
        dhcp: false
    nameservers:
      - 192.168.0.1
      - 8.8.8.8
```

### Apply configs and join cluster

```bash
# On pve-node-01
export TALOSCONFIG=/root/talos-cluster/configs/talosconfig
cd /root/talos-cluster

# Note: get DHCP IPs from Proxmox console after VMs boot
talosctl apply-config \
  --nodes <DHCP_IP_WORKER01> \
  --file configs/worker.yaml \
  --config-patch @worker-01-patch.yaml \
  --insecure

talosctl apply-config \
  --nodes <DHCP_IP_WORKER02> \
  --file configs/worker.yaml \
  --config-patch @worker-02-patch.yaml \
  --insecure
```

Wait ~90 seconds, then verify from your Mac:
```bash
kubectl get nodes -o wide
```

Expected (all 6 nodes Ready):
```
NAME            STATUS   ROLES           AGE   VERSION   INTERNAL-IP
talos-2j2-s88   Ready    control-plane   Xd    v1.36.1   192.168.0.110
talos-nqx-4u7   Ready    control-plane   Xd    v1.36.1   192.168.0.111
talos-i8m-1mm   Ready    control-plane   Xd    v1.36.1   192.168.0.112
talos-zlt-fqg   Ready    <none>          Xd    v1.36.1   192.168.0.113  ← GPU worker
talos-XXXX      Ready    <none>          2m    v1.36.1   192.168.0.114  ← new worker 01
talos-XXXX      Ready    <none>          2m    v1.36.1   192.168.0.115  ← new worker 02
```

> **Worker nodes join automatically** — no separate join command needed.
> Talos uses the cluster token embedded in the worker.yaml config to discover and join the control plane.

---

## Lessons Learned — Real Issues We Hit

### 1. talosctl must run from pve-node-01, not Mac

**Problem:** Mac couldn't reach Talos API port 50000 on the Talos VMs through Tailscale.

**Fix:** SSH to pve-node-01 and run all `talosctl` commands from there.
`kubectl` from Mac works fine because it goes through kube-vip (192.168.0.100:6443).

---

### 2. Talos API is on port 50000, not 50001

**Problem:** Wasted time checking port 50001 — it doesn't exist.

**Fix:** Talos API is always on port **50000** in both maintenance mode (insecure) and running mode (mTLS).

---

### 3. `machine.files: []` empty list patch is a no-op

**Problem:** Tried to clear bad `machine.files` entries by patching with an empty list `[]`.
Talos strategic merge ignores empty lists — the existing entries stayed.

**Fix:** Use `talosctl apply-config --file worker.yaml -p @patch.yaml` which replaces the entire
machine config, clearing bad entries completely.

---

### 4. JSON6902 patches not supported for Talos multi-document configs

**Problem:** `talosctl patch mc --patch-file fix.json` → "JSON6902 patches are not supported
for multi-document machine configuration"

**Fix:** Always use YAML strategic merge patches with `talosctl apply-config` or `talosctl patch mc --patch`.

---

### 5. EPHEMERAL wipe doesn't fix config issues

**Problem:** Ran `talosctl reset --system-labels-to-wipe EPHEMERAL` thinking it would clear bad config.
EPHEMERAL only wipes `/var` (data). The machine config lives in STATE partition.
After reboot, Talos re-applied the bad config from STATE.

**Fix:** Bad config requires replacing the entire machine config via `talosctl apply-config`,
or a full reset (`--system-labels-to-wipe STATE,EPHEMERAL`) if the node is unrecoverable.

---

### 6. Shell heredocs strip double-quotes from TOML in machine.files

**Problem:** All attempts to write TOML content via shell/JSON stripped the double-quotes:
```
[plugins."io.containerd.cri.v1.runtime".containerd]
```
became:
```
[plugins.io.containerd.cri.v1.runtime.containerd]
```
This is invalid TOML and causes containerd's CRIConfigPartsController to fail with `toml: expected 'nan'`.

**Fix:** Generate the YAML patch using Python's `yaml.dump()` which correctly escapes as `\"`.
Never use shell heredocs or echo to write TOML content into Talos machine.files patches.

---

### 7. NVIDIA device plugin "auto" strategy requires containerd default runtime

**Problem:** NVIDIA device plugin v0.17.0 detected "Incompatible strategy detected: auto".
Setting `DEVICE_LIST_STRATEGY=envvar` env var was ignored (overridden by embedded config).
CLI flags like `--device-list-strategy=cdi` were invalid in v0.17.0.

**Root cause:** The plugin's "auto" strategy requires the containerd `default_runtime_name` to be
set to `"nvidia"` — otherwise it can't confirm the runtime is available.

**Fix:** Add the containerd CRI config via `machine.files` with the Python-generated patch.
The `nvidia-container-toolkit` extension (from the factory ISO) registers the nvidia runtime,
but does NOT set it as the default — you must do that yourself.

---

### 8. Talos ISO boot halts with "halt_if_installed"

**Problem:** When booting the GPU worker from ISO after it already had Talos installed,
it showed `talos.halt_if_installed` and halted before opening port 50000 for maintenance mode.

**Fix:** Switched back to disk boot and caught the API port 50000 during the brief boot window
before Talos fully started (when it's briefly in a less-restricted mode).

---

### 9. Tenda router gives wrong IP to talos-cp-03 on DHCP

**Problem:** The Tenda router's DHCP assigns a different IP (.129) to talos-cp-03 (MAC BC:24:11:EA:9E:1D)
even though it should be stable. Only the static IP from the Talos machine config patch gives it .112.

**Fix:** Always apply the static IP patch. Never rely on DHCP for Talos nodes.

---

### 10. PodSecurity blocks hostPath volumes

**Problem:** Ollama couldn't mount the NVMe hostPath volume:
"violates PodSecurity 'baseline:latest': hostPath volumes"

**Fix:** Add `pod-security.kubernetes.io/enforce: privileged` label to the namespace.
The `ai` namespace needs privileged mode for GPU + hostPath access.

---

### 11. nvidia-device-plugin crashes on plain worker nodes

**Problem:** After adding plain worker nodes, the `nvidia-device-plugin` DaemonSet spreads to all
nodes automatically. Non-GPU nodes have no GPU so the plugin crashes → CrashLoopBackOff.

**Fix:** Add a nodeSelector so the DaemonSet only runs on the GPU worker. Apply via Helm upgrade
so it persists across future upgrades:
```bash
helm upgrade nvdp nvdp/nvidia-device-plugin \
  --namespace kube-system \
  --version 0.17.0 \
  --set nodeSelector."node-role\.kubernetes\.io/gpu-worker"=""
```

**Note:** A raw `kubectl patch` also works immediately but gets overwritten on next `helm upgrade`.

---

### 12. Open WebUI data lost on pod restart (emptyDir)

**Problem:** Open WebUI was deployed with `emptyDir` for its data volume — all user accounts,
conversation history and settings are lost every time the pod restarts.

**Fix:** Deploy `local-path-provisioner` (Rancher) as the storage class and use a 10Gi PVC.
Better than Longhorn for SQLite (no replication overhead). Must patch `local-path-storage` namespace
with `privileged` PodSecurity label or the helper pod fails to provision.

```bash
# Patch namespace (required for hostPath volumes)
kubectl label namespace local-path-storage \
  pod-security.kubernetes.io/enforce=privileged \
  pod-security.kubernetes.io/warn=privileged \
  pod-security.kubernetes.io/audit=privileged
```

Default provisioner path `/opt/local-path-provisioner` is read-only on Talos. Must override to
`/var/local-path-provisioner` via a ConfigMap patch.

---

### 13. Proxmox cluster split due to corosync token timeout

**Problem:** pve-node-02 loses Proxmox cluster quorum periodically, causing VMs on that node
to become unreachable (K8s nodes get `node.kubernetes.io/unreachable` taint). The journal shows:
```
corosync: [TOTEM] A processor failed, forming new configuration: token timed out (3125ms)
pmxcfs: [dcdb] crit: cpg_join failed: CS_ERR_EXIST
pvescheduler: replication: cfs-lock error: no quorum!
```

**Root cause:** Default corosync token timeout is 3000ms + (125ms × nodes). For a 3-node cluster
that's 3125ms — too tight for a consumer home network where any transient packet delay triggers a
false cluster split.

**Fix:** Add `token: 10000` (10 seconds) to the `totem` section in `/etc/pve/corosync.conf`,
increment `config_version`, then restart corosync one node at a time:

```bash
# On pve-node-01 — edits shared cluster filesystem, all nodes see it
# Backup first
cp /etc/pve/corosync.conf /etc/pve/corosync.conf.bak

# Edit: add token: 10000 to [totem] and bump config_version by 1
# Then restart corosync on each node one at a time (wait for quorum to restore between each)
ssh root@192.168.0.14 "systemctl restart corosync"  # pve-node-02
# wait ~10s, verify: pvecm status | grep Quorate  → Yes
ssh root@192.168.0.13 "systemctl restart corosync"  # pve-node-01
# wait ~10s, verify quorum
ssh root@192.168.0.11 "systemctl restart corosync"  # pve-ai-01
```

---

### 14. pve-node-01 appearing dead due to flaky switch port (physical NIC link drop)

**Problem:** pve-node-01 became completely unreachable — no ping, no SSH, no Proxmox API.
Force restarting the node brought it back briefly then it died again. Corosync showed:
```
[KNET] link: host: 2 link: 0 is down
[KNET] host: host: 2 has no active links
[TOTEM] A processor failed, forming new configuration: token timed out (10125ms)
```

**Root cause:** Physical NIC link loss — the switch port was intermittently dropping carrier:
```
e1000e 0000:00:1f.6 nic0: NIC Link is Down   ← switch port died
e1000e 0000:00:1f.6 nic0: NIC Link is Up     ← cable re-seated, link restored
```
The node itself never crashed. The NIC losing physical link caused corosync to declare the
other nodes unreachable, making the whole node appear offline.

**Fix:** Re-seat the ethernet cable on pve-node-01 and move it to a different switch port.
Faulty switch ports can intermittently drop carrier, especially after vibration or temperature changes.

**Diagnosis tip:** When a Proxmox node appears dead but there's no obvious kernel panic:
```bash
# Check for NIC link events on the suspected node (from another node's journal if needed)
journalctl -b 0 --no-pager | grep -E "NIC Link|KNET|carrier"
```

---

### 15. MetalLB speaker pods blocked by PodSecurity (ai.home unreachable)

**Problem:** `http://ai.home` and `http://192.168.0.201` were completely unreachable even though
MetalLB controller was running and the ingress-nginx service had `EXTERNAL-IP: 192.168.0.201`.
The MetalLB speaker DaemonSet showed `DESIRED: 6, CURRENT: 0` — no speaker pods running at all.

**Root cause:** The `metallb-system` namespace has `baseline` PodSecurity enforcement by default.
The speaker pod requires privileges that violate baseline policy:
- `NET_RAW` capability (for ARP advertisement)
- `hostNetwork: true`
- host ports (7946, 9120)

Without the speaker pods, no node does ARP/L2 announcement for the VIP — so the IP exists in
Kubernetes but is invisible to the LAN. Every device trying to reach it gets silence.

**Diagnosis:**
```bash
kubectl describe daemonset metallb-speaker -n metallb-system
# Look for Events → "violates PodSecurity baseline:latest: non-default capabilities (NET_RAW)..."
```

**Fix:** Label `metallb-system` namespace as privileged, then restart the DaemonSets:
```bash
kubectl label namespace metallb-system \
  pod-security.kubernetes.io/enforce=privileged \
  pod-security.kubernetes.io/warn=privileged \
  pod-security.kubernetes.io/audit=privileged \
  --overwrite

kubectl rollout restart daemonset/metallb-speaker daemonset/metallb-frr-k8s -n metallb-system
```

**Verify:**
```bash
kubectl get pods -n metallb-system   # all 6 speakers should be Running
curl -H "Host: ai.home" http://192.168.0.201   # should return 200
```

**Pattern:** Any system namespace that runs pods needing host networking, host ports, or
`NET_RAW`/`NET_ADMIN` capabilities (MetalLB, Calico, Cilium, etc.) needs `privileged` PodSecurity.
This is a recurring pattern on Talos clusters — label the namespace before installing such components.

---

## Useful Day-2 Commands

```bash
# Check all nodes
kubectl get nodes -o wide

# Check cluster etcd health (from pve-node-01)
talosctl health --nodes 192.168.0.110,192.168.0.111,192.168.0.112

# Check GPU allocation
kubectl describe node talos-zlt-fqg | grep -A5 "Allocated resources"

# See what's running in the AI namespace
kubectl get all -n ai

# Check which models Ollama has loaded
kubectl exec -n ai deploy/ollama -- ollama list

# Check Ollama running model and VRAM usage
kubectl exec -n ai deploy/ollama -- ollama ps

# Talos GPU driver check
talosctl dmesg --nodes 192.168.0.113 | grep -i nvidia

# Check Talos machine config on a node (from pve-node-01)
talosctl get machineconfig --nodes 192.168.0.113 -o yaml

# Check containerd config part (verify TOML quotes)
talosctl read /etc/cri/conf.d/20-customization.part --nodes 192.168.0.113

# --- Monitoring ---
# Check all monitoring pods
kubectl get pods -n monitoring

# GPU metrics directly from DCGM exporter
kubectl port-forward -n monitoring daemonset/dcgm-exporter 9400:9400 &
curl -s http://localhost:9400/metrics | grep -E "DCGM_FI_DEV_(GPU_TEMP|POWER_USAGE|FB_USED|FB_FREE)"

# Prometheus targets (verify scraping)
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090 &
# then open http://localhost:9090/targets

# Grafana — http://grafana.home (admin / your-password)
# NVIDIA DCGM dashboard: set instance=10.244.4.51:9400, gpu=0
# Alertmanager — kubectl port-forward svc/kube-prometheus-stack-alertmanager 9093:9093 -n monitoring
```

---

## Next Steps (Homelab Roadmap)

| Priority | Component | Purpose | Status |
|---|---|---|---|
| 1 | Plain worker nodes (.114, .115) | Run non-GPU apps | ✅ Done |
| 2 | MetalLB (L2 mode, pool 201-220) | Real LAN IPs for services | ✅ Done |
| 3 | Ingress-NGINX (192.168.0.201) | Route `ai.home` → Open WebUI | ✅ Done |
| 4 | local-path-provisioner | Persistent storage for Open WebUI SQLite | ✅ Done |
| 5 | Corosync token timeout (10s) | Prevent false Proxmox cluster splits | ✅ Done |
| 6 | GPU power cap (290W) | Protect Dell 5820 power rails under load | ✅ Done |
| 7 | kube-prometheus-stack + DCGM | Prometheus + Grafana + GPU metrics at `grafana.home` | ✅ Done |
| 8 | BIOS AC power recovery | Auto power-on after outage (needs physical access) | ⬜ Not yet done |
| 9 | DHCP reservations (Tenda) | Lock IPs for all nodes incl. kube-vip .100 | ⬜ Pending |
| 10 | Pi-hole DNS | `ai.home` / `grafana.home` on all devices (not just Mac) | ⬜ Pending |
| 11 | Open WebUI family personas | Per-user system prompts (daughter, wife, self) | ⬜ Pending |
| 12 | SearXNG | Self-hosted web search for Open WebUI | ⬜ Pending |
| 13 | ArgoCD | GitOps — deploy from Git automatically | ⬜ Pending |

---

## Reference

- [Talos Documentation](https://www.talos.dev/v1.13/introduction/getting-started/)
- [Talos Factory (custom images)](https://factory.talos.dev)
- [Talos NVIDIA Guide](https://www.talos.dev/v1.13/talos-guides/configuration/nvidia-gpu/)
- [NVIDIA Device Plugin](https://github.com/NVIDIA/k8s-device-plugin)
- [kube-vip](https://kube-vip.io)
- [Ollama](https://ollama.com)
- [Open WebUI](https://github.com/open-webui/open-webui)
