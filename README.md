# 🏠 Homelab Kubernetes Platform Setup

This document captures the complete setup and learning journey of building a cloud-native platform on a Proxmox-based homelab.

---

# 📦 1. Infrastructure Setup

## Hardware & Nodes

| Node        | IP           | Purpose             |
| ----------- | ------------ | ------------------- |
| pve-ai-01   | 192.168.0.11 | Future AI workloads |
| pve-node-01 | 192.168.0.13 | Primary compute     |
| pve-node-02 | 192.168.0.14 | Secondary compute   |

---

## Proxmox Cluster

* Installed Proxmox on all nodes
* Created cluster using `pvecm`
* Joined nodes into cluster
* Verified cluster health

---

# 🌐 2. Networking Setup

## IP Addressing

* Subnet: `192.168.0.0/24`
* Router: `192.168.0.1`

### Static Range

```
192.168.0.2 - 192.168.0.99
```

### DHCP Range

```
192.168.0.100 - 192.168.0.200
```

## Key Learnings

* Static IP for infrastructure
* DHCP for dynamic devices
* Avoid IP conflicts

---

# 🖥️ 3. VM & Template Setup

## Ubuntu VM Creation

* Installed Ubuntu Server
* Enabled SSH
* Installed base tools

## Hardening

* Disabled root SSH
* Enabled SSH key authentication
* Installed qemu-guest-agent

## Template Creation

* Installed cloud-init
* Cleaned machine-id
* Removed SSH host keys
* Converted VM → Template

---

# ☁️ 4. Cloud-init Integration

Configured:

* SSH keys injection
* Username
* Network config

Outcome:

* Automated VM provisioning
* No manual SSH setup required

---

# 🔐 5. Remote Access (Tailscale)

## Setup

* Installed Tailscale on Ubuntu VM
* Enabled subnet routing
* Enabled IP forwarding

## Result

* Secure access to homelab from anywhere
* No port forwarding required

---

# ⚙️ 6. Kubernetes Cluster (K3s)

## Nodes

| Node          | Role          | IP            |
| ------------- | ------------- | ------------- |
| k8s-cp-01     | Control Plane | 192.168.0.110 |
| k8s-worker-01 | Worker        | 192.168.0.111 |
| k8s-worker-02 | Worker        | 192.168.0.112 |

## Installation

### Control Plane

```
curl -sfL https://get.k3s.io | sh -
```

### Workers

```
K3S_URL=https://192.168.0.110:6443 \
K3S_TOKEN=<token> sh -
```

---

# 🧰 7. kubectl Access from Laptop

## Steps

* Copied kubeconfig from control plane
* Updated API server IP
* Configured ~/.kube/config

## Result

* Full cluster control from laptop

---

# 🌍 8. Application Exposure

## NodePort (Initial)

* Exposed services via random ports

## Ingress (Production Style)

Installed NGINX Ingress Controller

### Key Fix

* Added `ingressClassName: nginx`

## DNS Mapping

```
/etc/hosts
192.168.0.110 nginx.local
```

---

# 🚀 9. Applications Deployed

## 1. NGINX

* Basic deployment
* Exposed via NodePort

## 2. Guestbook App

* Multi-tier (frontend + Redis)
* Exposed via Ingress

## 3. Metrics App

* Exposes Prometheus metrics

---

# 📊 10. Monitoring Stack

Installed:

* Prometheus
* Grafana
* kube-state-metrics
* node-exporter

Using:

```
helm install monitoring prometheus-community/kube-prometheus-stack
```

## Access

* Grafana via Ingress
* Default dashboards available

---

# 📈 11. Observability Setup

## Prometheus Integration

* Auto-configured via Helm
* Verified via Grafana

## ServiceMonitor

* Enabled scraping of custom apps

---

# 🔄 12. End-to-End Flow

```
User
 ↓
Ingress (NGINX)
 ↓
Service
 ↓
Pod
 ↓
Metrics (/metrics)
 ↓
Prometheus
 ↓
Grafana
```

---

# 🧠 Key Learnings

## Infrastructure

* Static IP planning
* Cluster networking

## Virtualization

* Templates
* Cloud-init

## Kubernetes

* Control plane vs worker
* Services
* Ingress

## Observability

* Metrics pipeline
* Monitoring stack

---

# 🚀 Next Steps

* Add TLS (cert-manager)
* Add logging (Loki)
* Add tracing (OpenTelemetry)
* Deploy real production apps
* GPU workloads on AI node

---

# 🎯 Final Architecture

```
Proxmox Cluster
   ↓
VMs (Cloud-init)
   ↓
Kubernetes Cluster
   ↓
Ingress Controller
   ↓
Applications
   ↓
Monitoring Stack
```

---

# 💡 Summary

This homelab now represents a:

* Cloud-native platform
* Production-style architecture
* Full DevOps/SRE learning environment

---

End of Document 🚀
