# Infrastructure Reference: IPs, MACs, and Kubernetes Deployments

This is the authoritative reference for all physical and virtual infrastructure in the homelab. Use this as a quick lookup for IPs, MACs, service URLs, and deployment details.

---

## Physical Proxmox Nodes

| Hostname | IP Address | CPU Cores | RAM | Storage | Role |
|----------|-----------|-----------|-----|---------|------|
| pve-node-01 | 192.168.0.13 | 16 | 32 GB | 100 GB | Proxmox hypervisor, runs K8s CP + worker |
| pve-node-02 | 192.168.0.14 | 16 | 32 GB | 100 GB | Proxmox hypervisor, runs K8s CP + worker |
| pve-ai-01 | 192.168.0.11 | 12 | 64 GB | 100 GB | Proxmox hypervisor, GPU node, runs K8s CP + GPU worker |

All 3 nodes form a Proxmox VE cluster. Proxmox web UI accessible at `https://<node-ip>:8006`.

---

## Virtual Machines and LXC Containers

### Running VMs

| VMID | Name | Proxmox Node | MAC Address | IP | vCPU | RAM | Disk | Role |
|------|------|-------------|-------------|-----|------|-----|------|------|
| 105 | talos-cp-01 | pve-node-01 | BC:24:11:FA:56:D7 | 192.168.0.110 or .112 | 2 | 4 GB | 20 GB | Talos K8s control plane |
| 106 | talos-cp-02 | pve-node-02 | BC:24:11:23:7B:91 | 192.168.0.110 or .112 | 2 | 4 GB | 20 GB | Talos K8s control plane |
| 107 | talos-cp-03 | pve-ai-01 | BC:24:11:EA:9E:1D | 192.168.0.110 or .112 | 2 | 4 GB | 20 GB | Talos K8s control plane |
| 108 | talos-worker-01 | pve-node-01 | BC:24:11:50:5D:0D | 192.168.0.114 or .115 | 4 | 8 GB | 50 GB | Talos K8s worker |
| 109 | talos-worker-02 | pve-node-02 | BC:24:11:40:AB:62 | 192.168.0.114 or .115 | 4 | 8 GB | 50 GB | Talos K8s worker |
| 111 | lab-eye | pve-ai-01 | BC:24:11:ED:71:E1 | DHCP | 2 | 4 GB | 32 GB | Ubuntu general-purpose VM |
| 125 | talos-gpu-worker | pve-ai-01 | BC:24:11:23:53:2E | 192.168.0.113 | 8 | 48 GB | 200 GB (NVMe) | Talos K8s GPU worker, RTX 3090 passthrough |

> Note: The 3 control-plane IPs are 192.168.0.110, 192.168.0.112, and one maps to the kube-vip VIP 192.168.0.100. Check router DHCP table or ARP to map VM IDs to specific IPs via MAC addresses.

### Running LXC Containers

| VMID | Name | Proxmox Node | MAC Address | IP | vCPU | RAM | Disk | Role |
|------|------|-------------|-------------|-----|------|-----|------|------|
| 110 | ts-router-2 | pve-ai-01 | BC:24:11:F8:25:9B | DHCP | 1 | 512 MB | 4 GB | Tailscale subnet router |

### Stopped / Templates

| VMID | Name | Proxmox Node | Status | Notes |
|------|------|-------------|--------|-------|
| 100 | ubuntu-server-01 | pve-node-01 | Template | Base Ubuntu template |
| 101 | ts-router | pve-node-01 | Stopped | Old Tailscale router, onboot=0, pending deletion |
| 102 | k8s-template | pve-ai-01 | Template | Talos VM template |
| 103 | k8s-template | pve-node-01 | Template | Talos VM template |
| 104 | k8s-template | pve-node-02 | Template | Talos VM template |
| 120 | ubuntu-server-01 | pve-ai-01 | Template | Base Ubuntu template |

---

## Kubernetes Cluster

### Cluster Access
- **API Server VIP**: `192.168.0.100` (kube-vip floats across control-plane nodes)
- **kubeconfig**: `~/.kube/config` on Mac
- **Talos CLI**: `talosctl` pointing at `192.168.0.100`
- **Kubernetes version**: v1.36.1
- **Talos version**: v1.13.3

### Nodes

| K8s Node Name | Role | IP | Proxmox VM | vCPU | RAM | Labels |
|--------------|------|-----|-----------|------|-----|--------|
| talos-2j2-s88 | control-plane | 192.168.0.110 | VM 105 or 106 or 107 | 2 | 4 GB | node-role.kubernetes.io/control-plane |
| talos-i8m-1mm | control-plane | 192.168.0.112 | VM 105 or 106 or 107 | 2 | 4 GB | node-role.kubernetes.io/control-plane |
| talos-nqx-4u7 | control-plane | 192.168.0.100 | VM 105 or 106 or 107 | 2 | 4 GB | node-role.kubernetes.io/control-plane |
| talos-76j-w0h | worker | 192.168.0.114 | VM 108 or 109 | 4 | 8 GB | node-role.kubernetes.io/worker |
| talos-97a-ilz | worker | 192.168.0.115 | VM 108 or 109 | 4 | 8 GB | node-role.kubernetes.io/worker |
| talos-zlt-fqg | gpu-worker | 192.168.0.113 | VM 125 | 8 | 48 GB | node-role.kubernetes.io/gpu-worker, nvidia.com/gpu=true |

---

## Network

### MetalLB IP Pool
- **Range**: `192.168.0.200–192.168.0.210`
- **Mode**: L2 (ARP-based)

### LoadBalancer IPs in Use

| IP | Service | Namespace | Protocol | Purpose |
|----|---------|-----------|----------|---------|
| 192.168.0.201 | ingress-nginx-controller | ingress-nginx | TCP 80, 443 | All HTTP/S ingress traffic |
| 192.168.0.202 | pihole-dns-tcp | pihole | TCP 53 | Pi-hole DNS (TCP) |
| 192.168.0.202 | pihole-dns-udp | pihole | UDP 53 | Pi-hole DNS (UDP) |

### DNS
- **Pi-hole IP**: `192.168.0.202`
- **All `.home` domains** resolve to `192.168.0.201` (NGINX routes by hostname)
- **Router DNS**: Set to `192.168.0.202` (Pi-hole) as primary
- **Tailscale DNS**: Add `192.168.0.202` in Tailscale admin console to allow Tailscale clients to resolve `.home` names

### Tailscale Subnet Router
- **LXC**: ts-router-2 (VMID 110, pve-ai-01)
- **Advertised route**: `192.168.0.0/24`
- **Purpose**: Remote access to all homelab services via Tailscale VPN

---

## Kubernetes Deployed Services

### Namespace: `ai`

| Component | Image | Ingress Host | Internal Service | Notes |
|-----------|-------|-------------|-----------------|-------|
| Ollama | ollama/ollama:latest | ollama.home | ollama.ai.svc.cluster.local:11434 | GPU required, strategy: Recreate |
| Open WebUI | open-webui (latest) | ai.home | open-webui.ai.svc.cluster.local:8080 | Personas: Sunny, Aria, CodeBot |

**Ollama models stored at**: `/var/local/ollama-models` on `talos-zlt-fqg` (hostPath)  
**Ollama GPU**: nvidia.com/gpu: 1 (RTX 3090, 24 GB VRAM)  
**Models loaded**: qwen2.5-coder:32b, deepseek-r1:32b, gemma2:27b

### Namespace: `pihole`

| Component | Image | Ingress Host | External IP | Notes |
|-----------|-------|-------------|------------|-------|
| Pi-hole | pihole/pihole:latest | pihole.home/admin | 192.168.0.202:53 | DNS sinkhole + ad blocker |

**Custom DNS config**: ConfigMap `pihole-local-dns` → mounted as dnsmasq config  
**Secret**: `pihole-secret` (key: WEBPASSWORD)

### Namespace: `searxng`

| Component | Image | Ingress Host | Internal Service | Notes |
|-----------|-------|-------------|-----------------|-------|
| SearXNG | searxng/searxng:latest | searxng.home | searxng-svc.searxng.svc.cluster.local:8080 | Service named `searxng-svc` (not `searxng`) to avoid K8s env var conflict |

**Secret**: `searxng-secret` (key: secret_key)

### Namespace: `monitoring`

| Component | Image/Chart | Ingress Host | Internal Service | Notes |
|-----------|------------|-------------|-----------------|-------|
| Grafana | kube-prometheus-stack | grafana.home | kube-prometheus-stack-grafana.monitoring.svc.cluster.local:80 | Admin password in secret |
| Prometheus | kube-prometheus-stack | prometheus.home | prometheus-kube-prometheus-stack-prometheus.monitoring.svc.cluster.local:9090 | 15-day retention |
| Alertmanager | kube-prometheus-stack | alertmanager.home | alertmanager-operated.monitoring.svc.cluster.local:9093 | Gmail SMTP alerts |
| DCGM Exporter | nvidia/dcgm-exporter | — | dcgm-exporter.monitoring.svc.cluster.local:9400 | GPU metrics, runs on gpu-worker |
| Loki | grafana/loki (SingleBinary) | — | loki.monitoring.svc.cluster.local:3100 | 7-day retention, 10Gi PVC |
| Promtail | grafana/promtail | — | DaemonSet | Runs on all nodes, ships logs to Loki |

**Grafana datasources**: Prometheus (default), Loki  
**Helm values**: `kubernetes/monitoring/kube-prometheus-stack-values.yaml` (dummy) + `kube-prometheus-stack-values.secret.yaml` (real, gitignored)

### Namespace: `argocd`

| Component | Ingress Host | Notes |
|-----------|-------------|-------|
| ArgoCD | argocd.home | Insecure mode (HTTP), NGINX `backend-protocol: HTTP` annotation |

**Root app**: watches `kubernetes/argocd-apps/` in `raghavendrak89/home_lab` repo (main branch)  
**Sync policy**: automated, prune=true, selfHeal=true  
**Repo**: https://github.com/raghavendrak89/home_lab.git (public)

### Namespace: `uptime-kuma`

| Component | Image | Ingress Host | Notes |
|-----------|-------|-------------|-------|
| Uptime Kuma | louislam/uptime-kuma:1 | status.home | 1Gi PVC for data |

### Namespace: `ingress-nginx`

| Component | External IP | Ports |
|-----------|------------|-------|
| ingress-nginx-controller | 192.168.0.201 | 80 (HTTP), 443 (HTTPS) |

### Namespace: `metallb-system`

- Controller + speaker DaemonSet on all nodes
- L2 advertisement of `192.168.0.200–192.168.0.210`

---

## Storage

### Storage Class
- **Name**: `local-path`
- **Provisioner**: `local-path-provisioner` (rancher/local-path-provisioner)
- **Mode**: ReadWriteOnce, single-node
- **Location**: Node-local storage (no shared filesystem)

### PVCs in Use

| PVC | Namespace | Size | Node Affinity | Used By |
|-----|-----------|------|--------------|---------|
| loki-data | monitoring | 10 Gi | Wherever Loki schedules | Loki log storage |
| uptime-kuma-data | uptime-kuma | 1 Gi | Wherever pod schedules | Uptime Kuma config/history |
| Ollama models | ai | hostPath | talos-zlt-fqg | Ollama model weights (not a PVC, hostPath) |

---

## GPU

| Attribute | Value |
|-----------|-------|
| GPU Model | NVIDIA RTX 3090 |
| VRAM | 24 GB |
| Proxmox passthrough | `hostpci0: 0000:65:00,pcie=1` on VM 125 |
| K8s node | talos-zlt-fqg (192.168.0.113) |
| K8s resource | `nvidia.com/gpu: "1"` |
| Driver plugin | nvidia-device-plugin DaemonSet |
| GPU metrics | DCGM Exporter → Prometheus → Grafana |

---

## Quick Reference: Service URLs

| Service | External URL | Internal URL |
|---------|-------------|-------------|
| Grafana | http://grafana.home | http://kube-prometheus-stack-grafana.monitoring.svc.cluster.local |
| Prometheus | http://prometheus.home | http://prometheus-kube-prometheus-stack-prometheus.monitoring.svc.cluster.local:9090 |
| Alertmanager | http://alertmanager.home | http://alertmanager-operated.monitoring.svc.cluster.local:9093 |
| Open WebUI | http://ai.home | http://open-webui.ai.svc.cluster.local:8080 |
| Ollama API | http://ollama.home | http://ollama.ai.svc.cluster.local:11434 |
| SearXNG | http://searxng.home | http://searxng-svc.searxng.svc.cluster.local:8080 |
| Pi-hole Admin | http://pihole.home/admin | http://pihole.pihole.svc.cluster.local/admin |
| ArgoCD | http://argocd.home | http://argocd-server.argocd.svc.cluster.local |
| Uptime Kuma | http://status.home | http://uptime-kuma.uptime-kuma.svc.cluster.local:3001 |
| Loki | — | http://loki.monitoring.svc.cluster.local:3100 |
| Proxmox (pve-ai-01) | https://192.168.0.11:8006 | — |
| Proxmox (pve-node-01) | https://192.168.0.13:8006 | — |
| Proxmox (pve-node-02) | https://192.168.0.14:8006 | — |

---

## Useful Commands

```bash
# Cluster overview
kubectl get nodes -o wide
kubectl get pods -A
kubectl get svc -A | grep LoadBalancer

# Check a specific namespace
kubectl get all -n monitoring

# ArgoCD apps status
kubectl get applications -n argocd

# Check GPU availability
kubectl describe node talos-zlt-fqg | grep -A5 "Allocatable"

# Exec into Ollama to pull a model
kubectl exec -it -n ai deploy/ollama -- ollama pull <model>

# Apply secrets (not managed by ArgoCD)
kubectl apply -f kubernetes/secrets/

# Force ArgoCD sync
kubectl -n argocd patch application root --type merge \
  -p '{"operation":{"sync":{"revision":"HEAD"}}}'

# Check Loki is receiving logs
kubectl logs -n monitoring loki-0 | tail -20

# Check Promtail on a specific node
kubectl logs -n monitoring -l app.kubernetes.io/name=promtail --field-selector spec.nodeName=talos-zlt-fqg
```
