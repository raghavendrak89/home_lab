```
Internet / Laptop
        ↓
   Tailscale VPN
        ↓
 Ubuntu VM (Subnet Router)
        ↓
   192.168.0.0/24 Network
        ↓
 Proxmox Cluster
        ↓
 Kubernetes Cluster
        ↓
 Ingress (NGINX)
        ↓
 Applications
        ↓
 Prometheus → Grafana
```