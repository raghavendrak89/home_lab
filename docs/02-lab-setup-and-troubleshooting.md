# Homelab Setup: Complete Guide with Issues and Resolutions

This document covers the full homelab Kubernetes setup — every component deployed, every problem encountered, and how it was resolved. Intended as a RAG knowledge base for querying setup history and troubleshooting guidance.

---

## Environment Summary

- **Hypervisor**: Proxmox VE across 3 physical nodes
- **OS**: Talos Linux v1.13.3 (immutable, API-driven K8s OS)
- **Kubernetes**: v1.36.1, 6-node cluster (3 control-plane + 2 workers + 1 GPU worker)
- **CNI**: Flannel
- **Storage**: local-path-provisioner (all PVCs use `storageClassName: local-path`)
- **Load Balancer**: MetalLB in L2 mode
- **Ingress**: NGINX Ingress Controller
- **DNS**: Pi-hole at 192.168.0.202 (upstream DNS for `.home` names)
- **GitOps**: ArgoCD (app-of-apps pattern), repo: `raghavendrak89/home_lab` (public)
- **GPU**: NVIDIA RTX 3090 passed through to talos-gpu-worker

---

## 1. Talos Kubernetes Cluster Bootstrap

### What was done
- Created VM templates on each Proxmox node for Talos
- Provisioned 3 control-plane VMs (one per Proxmox node) and 3 worker VMs
- Used `talosctl` + `talhelper` for config generation and cluster bootstrapping
- kube-vip provides the control-plane VIP at 192.168.0.100

### Key config locations
- Talos machine configs: `/Users/raghavendra/homelab/talos/`
- kubeconfig: `~/.kube/config` (set up on Mac for `kubectl` access)

### Issue: kubectl access from Mac
**Problem**: Initially unclear whether to SSH into nodes or use local kubectl.  
**Resolution**: Use Mac's local kubeconfig and `kubectl`/`helm` commands directly. Only SSH for Proxmox-level operations (VM management, LXC config). Talos API is exposed on the network and the kubeconfig endpoint points to the kube-vip VIP.

---

## 2. MetalLB (L2 Mode)

### What was done
- Installed MetalLB via Helm
- Configured L2 IP pool: `192.168.0.200–192.168.0.210`
- Two IPs in active use:
  - `192.168.0.201` — ingress-nginx LoadBalancer
  - `192.168.0.202` — Pi-hole DNS (shared between TCP and UDP services)

### Pi-hole shared IP trick
Two separate LoadBalancer services (one TCP port 53, one UDP port 53) both assigned `192.168.0.202` using the annotation:
```yaml
metallb.universe.tf/allow-shared-ip: "pihole-dns"
```
Both services must carry the same annotation value for MetalLB to share the IP.

---

## 3. NGINX Ingress Controller

### What was done
- Installed via Helm, exposed as LoadBalancer at `192.168.0.201`
- All `.home` services route through this single IP via hostname-based routing
- Key annotation for ArgoCD (runs HTTPS internally): `nginx.ingress.kubernetes.io/backend-protocol: "HTTP"`

### Issue: 404 on raw IP access
**Problem**: Accessing `http://192.168.0.201/admin/` returned 404.  
**Cause**: NGINX routes purely by `Host:` header. No rule matches a bare IP.  
**Resolution**: Always use the hostname (e.g., `pihole.home`), never the raw MetalLB IP.

---

## 4. Pi-hole DNS

### What was done
- Deployed Pi-hole in `pihole` namespace as a Deployment
- Two LoadBalancer services share `192.168.0.202` for DNS (TCP + UDP port 53)
- ClusterIP service for admin UI (accessed via NGINX ingress at `pihole.home`)
- Admin password stored in a Kubernetes Secret (`pihole-secret`), referenced via `secretKeyRef`
- Custom DNS entries for all `.home` hostnames in a ConfigMap (`pihole-local-dns`)

### Local DNS ConfigMap (dnsmasq config)
```
address=/ai.home/192.168.0.201
address=/grafana.home/192.168.0.201
address=/prometheus.home/192.168.0.201
address=/alertmanager.home/192.168.0.201
address=/pihole.home/192.168.0.201
address=/searxng.home/192.168.0.201
address=/argocd.home/192.168.0.201
address=/ollama.home/192.168.0.201
address=/status.home/192.168.0.201
```
All `.home` names point to `192.168.0.201` (ingress-nginx). NGINX then routes by hostname.

### Issue: Mac not resolving .home domains after adding Pi-hole to router
**Problem**: Router DHCP hands out `192.168.0.202` as DNS, but Mac still couldn't resolve `.home`.  
**Cause**: Tailscale installs its own DNS resolver at `100.100.100.100` and takes priority over DHCP-assigned DNS, regardless of router settings.  
**Resolution**: Add `192.168.0.202` (Pi-hole) as an explicit nameserver in the Tailscale admin console DNS settings. This makes Tailscale forward DNS queries to Pi-hole too. Then flush the Mac DNS cache:
```bash
sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder
```

### Issue: alertmanager.home not reachable after Pi-hole DNS was working
**Problem**: After fixing DNS, alertmanager.home still didn't resolve.  
**Cause**: Negative DNS cache on the Mac (the earlier failed lookups were cached).  
**Resolution**: Flush Mac DNS cache (same commands above).

---

## 5. Monitoring Stack (kube-prometheus-stack)

### What was done
- Deployed via Helm: Prometheus, Grafana, Alertmanager, node-exporter, kube-state-metrics
- Ingress hosts: `grafana.home`, `prometheus.home`, `alertmanager.home`
- Gmail SMTP alerting configured for alertmanager
- Resource limits added to all components:
  - Grafana: 200m–1 CPU, 256Mi–512Mi RAM
  - Prometheus: 500m–2 CPU, 1Gi–3Gi RAM
  - Alertmanager: light limits

### Secrets management for Helm values
Two-tier approach for public repo:
- `kube-prometheus-stack-values.yaml` — committed, dummy passwords (`changeme`, `sopn...`)
- `kube-prometheus-stack-values.secret.yaml` — gitignored (matched by `*.secret.yaml`), real passwords
- Helm upgrade always uses the `.secret.yaml` file:
  ```bash
  helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
    -n monitoring \
    -f kubernetes/monitoring/kube-prometheus-stack-values.yaml \
    -f kubernetes/monitoring/kube-prometheus-stack-values.secret.yaml
  ```

### Issue: Alertmanager "field body not found in type config.plain"
**Problem**: Alertmanager pod CrashLoopBackOff with config parse error.  
**Cause**: Used `body:` field in email_configs instead of the correct field name.  
**Resolution**: Changed `body:` to `text:` in the alertmanager email config section.

### Issue: Alertmanager 503 Service Temporarily Unavailable
**Problem**: `alertmanager.home` returned 503.  
**Cause**: Alertmanager was in CrashLoopBackOff due to the config error above.  
**Resolution**: Fixed the `text:` field, pod recovered.

### Issue: Grafana Loki datasource not appearing after Helm upgrade
**Problem**: Added Loki as `additionalDataSources` in Helm values. After `helm upgrade`, the datasource didn't appear in Grafana.  
**Cause**: Grafana's post-upgrade hook tries to reload datasources by calling the Grafana API with the values-file password (`changeme`), but the real Grafana password is different (`@@Dtdefault1`). Authentication fails silently.  
**Resolution**: Manually trigger Grafana datasource reload:
```bash
curl -X POST http://admin:@@Dtdefault1@grafana.home/api/admin/provisioning/datasources/reload
```

---

## 6. DCGM Exporter (GPU Metrics)

### What was done
- Deployed NVIDIA DCGM Exporter as a DaemonSet on the GPU node
- Scraped by Prometheus for GPU utilization, memory, temperature metrics
- Grafana DCGM dashboard added

### Issue: GPU metrics appeared to stop
**Problem**: GPU metrics stopped appearing in Grafana after resource limits were applied to DCGM exporter.  
**Root cause**: Adding resource limits caused the DCGM pod to restart. Each restart creates a new pod IP. The Grafana DCGM dashboard has an "instance" dropdown that shows `IP:9400`. The old pod IP (10.244.4.53) had historical data; the new pod IP (10.244.4.71) had fresh data.  
**Resolution**: Select the new instance IP in the Grafana dashboard dropdown. Old metrics from the previous pod IP remain in Prometheus for the 15-day retention period.

---

## 7. Loki + Promtail (Log Aggregation)

### What was done
- Deployed Loki via ArgoCD (Helm, `loki` chart, `SingleBinary` mode)
- Deployed Promtail via ArgoCD (Helm, DaemonSet on all nodes)
- 7-day log retention configured
- 10Gi PVC for Loki storage (`local-path`)
- Loki added as Grafana datasource

### Key Loki config decisions
- `deploymentMode: SingleBinary` — single process, no scalability complexity
- `replication_factor: 1` — single replica
- Backend/read/write component replicas all set to 0 (SingleBinary handles everything)
- Filesystem storage (no S3/object store needed for homelab)

### Issue: Loki compactor error on startup
**Problem**: Loki logs showed: `compactor.delete-request-store should be configured when retention is enabled`.  
**Resolution**: Added to Loki config:
```yaml
compactor:
  retention_enabled: true
  delete_request_store: filesystem
```

### Promtail tolerations
Promtail DaemonSet needs tolerations to run on the GPU node (which has a GPU taint):
```yaml
tolerations:
  - operator: Exists
    effect: NoSchedule
  - operator: Exists
    effect: NoExecute
```

---

## 8. SearXNG (Privacy-Respecting Meta Search Engine)

### What was done
- Deployed in `searxng` namespace
- Exposed at `searxng.home` via NGINX ingress
- Integrated with Open WebUI as a web search tool
- `secret_key` stored in Kubernetes Secret, referenced via `secretKeyRef`

### Issue: SearXNG pod fails with "Invalid value for --port: 'tcp://...' is not a valid integer"
**Problem**: SearXNG container couldn't start because its startup argument `--port` received a URL instead of a number.  
**Root cause**: Kubernetes automatically injects environment variables for every Service in the same namespace. If you name the Service `searxng`, K8s injects `SEARXNG_PORT=tcp://10.x.x.x:8080`. SearXNG's own startup script reads `$SEARXNG_PORT` and passes it as `--port`, getting the URL instead of a port number.  
**Resolution**: Renamed the Kubernetes Service from `searxng` to `searxng-svc`. This stops K8s from injecting `SEARXNG_PORT` and SearXNG uses its built-in default port.

### Note on search result freshness
Open WebUI shows web search results from SearXNG, but the model's response combining those results with its training data may look stale. To verify web search is active, ask the model explicitly to search for a current event. The `SEARXNG_SECRET` must match between the SearXNG deployment and Open WebUI configuration.

---

## 9. Open WebUI + Ollama (AI Interface)

### What was done
- Ollama deployed in `ai` namespace, pinned to GPU node (`talos-zlt-fqg`) via `nodeSelector`
- GPU passthrough to VM via Proxmox `hostpci0` device
- Models stored on NVMe hostPath (`/var/local/ollama-models`) for persistence across pod restarts
- Open WebUI deployed as frontend, connected to Ollama
- Three personas configured: Sunny (family-friendly), Aria (creative), CodeBot (technical)
- SearXNG integrated as web search backend

### GPU scheduling: Recreate strategy
**Problem**: When updating Ollama (new image, config change), rolling update deadlocks. The old pod holds the single GPU, the new pod can't schedule, old pod never terminates.  
**Resolution**: Added to Ollama Deployment:
```yaml
spec:
  strategy:
    type: Recreate
```
Recreate terminates the old pod completely before starting the new one, freeing the GPU.

### Resource limits for Ollama
```yaml
resources:
  requests:
    cpu: "2"
    memory: "8Gi"
  limits:
    cpu: "6"
    memory: "40Gi"
    nvidia.com/gpu: "1"
```
`nvidia.com/gpu: "1"` is exclusive — only one pod can hold it at a time.

### Models in use
- `qwen2.5-coder:32b` — coding assistant
- `deepseek-r1:32b` — reasoning
- `gemma2:27b` — general use
- (pull with `ollama pull <model>` via exec into the Ollama pod)

---

## 10. ArgoCD (GitOps)

### What was done
- Deployed ArgoCD in `argocd` namespace via Helm
- Exposed at `argocd.home` via NGINX ingress (HTTP, not HTTPS)
- `argocd-server` configured in insecure mode (no TLS on the server itself)
- App-of-apps pattern: root Application watches `kubernetes/argocd-apps/` directory
- All child apps auto-discovered and synced
- Automated sync with `prune: true` and `selfHeal: true`

### Insecure mode config
ArgoCD by default serves HTTPS. For plain HTTP ingress:
1. Add ConfigMap:
   ```yaml
   apiVersion: v1
   kind: ConfigMap
   metadata:
     name: argocd-cmd-params-cm
     namespace: argocd
   data:
     server.insecure: "true"
   ```
2. Add ingress annotation:
   ```yaml
   nginx.ingress.kubernetes.io/backend-protocol: "HTTP"
   ```

### Issue: ArgoCD 307 redirect after insecure mode applied
**Problem**: After applying the insecure ConfigMap, ArgoCD still redirected to HTTPS.  
**Cause**: The `argocd-server` deployment was already running and hadn't reloaded the ConfigMap.  
**Resolution**: `kubectl -n argocd rollout restart deployment/argocd-server`

### Issue: New ArgoCD Application files not auto-discovered
**Problem**: After pushing new Application YAML files to `kubernetes/argocd-apps/`, they didn't appear in ArgoCD.  
**Cause**: The root Application needs a manual sync trigger the first time (it only auto-syncs on a schedule, not on push).  
**Resolution**:
```bash
kubectl -n argocd patch application root --type merge \
  -p '{"operation":{"sync":{"revision":"HEAD"}}}'
```

### Secrets with GitOps
The repo is public on GitHub. Pattern used:
1. `*.secret.yaml` in `.gitignore` — for Helm values containing real passwords
2. `kubernetes/secrets/` in `.gitignore` — for raw Kubernetes Secret manifests
3. Committed manifests use `secretKeyRef` to reference Secret names (not values)
4. Secrets applied manually once: `kubectl apply -f kubernetes/secrets/`
5. `kubernetes/SECRETS.md` (committed) documents how to recreate secrets

ArgoCD manages everything except Secrets. Secrets are applied out-of-band. This is a simplified approach; a production setup would use Sealed Secrets or External Secrets Operator.

---

## 11. Tailscale Subnet Router Migration (pve-node-01 VM → pve-ai-01 LXC)

### What was done
- Original tsrouter was VM 101 on pve-node-01 (Ubuntu VM)
- Migrated to LXC container 110 on pve-ai-01 (`ts-router-2`, hostname: ts-router-2)
- LXC runs Debian, uses Tailscale to advertise the 192.168.0.0/24 subnet
- VM 101 stopped and `onboot=0` set (pending deletion)

### LXC TUN device configuration
Tailscale requires the `/dev/net/tun` device inside the LXC. The correct way:

In `/etc/pve/lxc/110.conf`:
```
lxc.cgroup2.devices.allow: c 10:200 rwm
lxc.mount.entry: /dev/net/tun dev/net/tun none bind,create=file
features: nesting=1
```

**Do NOT use** `pct set 110 --dev0 /dev/net/tun` — this creates a `dev0:` entry that conflicts with the manual `lxc.mount.entry` lines and causes container startup failures.

### Issue: tailscaled failing inside LXC (socket not created)
**Problem**: `tailscale up` failed saying socket not found.  
**Cause**: `tailscaled` wasn't running yet.  
**Resolution**: Start the daemon first:
```bash
systemctl start tailscaled && sleep 2 && tailscale up --advertise-routes=192.168.0.0/24
```

### Post-migration steps
1. In Tailscale admin console: approve the advertised route for the LXC
2. Remove the old route advertisement from the old VM (if still active)
3. Verify Mac can reach homelab IPs via Tailscale subnet routing

---

## 12. Uptime Kuma (Status Page)

### What was done
- Deployed in `uptime-kuma` namespace
- 1Gi PVC for persistent data (monitors, history)
- Exposed at `status.home` via NGINX ingress
- Monitors configured for all homelab services

### Monitor configuration notes

| Service | Monitor Type | Target |
|---------|-------------|--------|
| Grafana | HTTP | http://grafana.home |
| Prometheus | HTTP | http://prometheus.home |
| Alertmanager | HTTP | http://alertmanager.home |
| Open WebUI | HTTP | http://ai.home |
| SearXNG | HTTP | http://searxng.home |
| ArgoCD | HTTP | http://argocd.home |
| Ollama | HTTP | http://ollama.home |
| Pi-hole Admin | HTTP | http://pihole.home/admin |
| Pi-hole DNS | DNS (TCP) | 10.107.201.171:53 (ClusterIP of pihole-dns-udp) |

### Issue: Uptime Kuma can't resolve .home domains for monitors
**Problem**: Uptime Kuma pods run inside the cluster. CoreDNS (the in-cluster DNS) doesn't know about `.home` names — that's Pi-hole's job and Pi-hole only serves external clients.  
**Resolution**: Use the full Kubernetes service DNS name for in-cluster monitors:
- Instead of `http://grafana.home` → `http://kube-prometheus-stack-grafana.monitoring.svc.cluster.local`
- Or, alternatively, use the MetalLB IP directly: `http://192.168.0.201` with a `Host:` header
- For the public-facing check (simulating external user): use the `.home` URL only if the uptime-kuma pod's DNS is set to use Pi-hole (which it isn't by default)

In practice, the HTTP monitors targeting `.home` URLs work because Uptime Kuma resolves DNS using the node's DNS (which may include Pi-hole via the router). Test first with a simple `curl` from the pod.

### Issue: Pi-hole DNS monitor "Invalid IP address"
**Problem**: Tried to use `pihole-dns-tcp.pihole.svc.cluster.local:53` as the DNS monitor target.  
**Resolution**: Use the ClusterIP directly: `10.107.201.171` (the ClusterIP of `pihole-dns-udp` service). Uptime Kuma's DNS monitor requires a raw IP, not a hostname.

---

## 13. Resource Limits

All workloads have resource requests and limits set to prevent runaway resource consumption and improve scheduler decisions.

### Standard patterns used

**Light services** (Pi-hole, SearXNG, Uptime Kuma):
```yaml
resources:
  requests:
    cpu: "50m"–"200m"
    memory: "128Mi"–"256Mi"
  limits:
    cpu: "500m"–"1"
    memory: "256Mi"–"512Mi"
```

**AI workloads** (Ollama):
```yaml
resources:
  requests:
    cpu: "2"
    memory: "8Gi"
  limits:
    cpu: "6"
    memory: "40Gi"
    nvidia.com/gpu: "1"
```

**Monitoring** (Grafana, Prometheus, Alertmanager):
```yaml
# Grafana
requests: {cpu: "200m", memory: "256Mi"}
limits: {cpu: "1", memory: "512Mi"}
# Prometheus
requests: {cpu: "500m", memory: "1Gi"}
limits: {cpu: "2", memory: "3Gi"}
```

---

## 14. Git Repository and Secrets Management

### Repository structure
```
home_lab/                          (public GitHub repo)
├── .gitignore                     (excludes *.secret.yaml, kubernetes/secrets/)
├── kubernetes/
│   ├── apps/
│   │   ├── ai/                   (ollama.yaml, open-webui.yaml)
│   │   ├── pihole/               (pihole.yaml, local-dns.yaml)
│   │   ├── searxng/              (searxng.yaml)
│   │   └── uptime-kuma/          (uptime-kuma.yaml)
│   ├── monitoring/
│   │   ├── kube-prometheus-stack-values.yaml        (committed, dummy)
│   │   ├── kube-prometheus-stack-values.secret.yaml (gitignored, real)
│   │   └── dcgm-exporter.yaml
│   ├── argocd-apps/              (ArgoCD Application manifests)
│   │   ├── root.yaml             (root app-of-apps)
│   │   ├── pihole.yaml
│   │   ├── searxng.yaml
│   │   ├── ai.yaml
│   │   ├── loki.yaml
│   │   ├── promtail.yaml
│   │   └── uptime-kuma.yaml
│   └── secrets/                  (gitignored directory)
│       ├── pihole-secret.yaml
│       └── searxng-secret.yaml
└── docs/
```

### What is NOT in git
- Real passwords and API keys
- Kubernetes Secret manifests (in `kubernetes/secrets/` which is gitignored)
- Helm values with real credentials (`*.secret.yaml`)

### What IS in git
- All Kubernetes workload manifests (Deployments, Services, Ingresses, ConfigMaps)
- ArgoCD Application manifests
- Helm values files with placeholder credentials
- `kubernetes/SECRETS.md` documenting how to recreate secrets from scratch

---

## 15. Common DNS and Network Troubleshooting

### Mac DNS cache flush
```bash
sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder
```

### Check which DNS server is being used on Mac
```bash
scutil --dns | grep nameserver
```

### Test Pi-hole DNS directly
```bash
dig @192.168.0.202 grafana.home
```

### Check MetalLB IP assignments
```bash
kubectl get svc -A | grep LoadBalancer
```

### Check ingress routing
```bash
kubectl get ingress -A
```

### Force ArgoCD root app sync
```bash
kubectl -n argocd patch application root --type merge \
  -p '{"operation":{"sync":{"revision":"HEAD"}}}'
```

### Reload Grafana datasources manually
```bash
curl -X POST http://admin:<password>@grafana.home/api/admin/provisioning/datasources/reload
```

---

## Pending Work

- **Change ArgoCD admin password** — still using initial bootstrap password
- **cert-manager + TLS** — HTTPS for all `.home` services; prerequisite for Ollama basic auth
- **Ollama TLS + basic auth** — currently unauthenticated on the network
- **Open WebUI RAG** — pull `nomic-embed-text` embedding model, configure knowledge base
- **Vaultwarden** — self-hosted password manager
- **Delete VM 101** (ts-router) — stopped, `onboot=0`, safe to remove
- **BIOS AC power recovery** — set on pve-node-01 and pve-node-02 for auto power-on after outage
- **kube-prometheus-stack Helm upgrade with secret values** — apply resource limits to Prometheus/Grafana using `.secret.yaml`
- **Future deployments**: n8n (workflow automation), ComfyUI (image generation), Nextcloud, Paperless-ngx, Gitea
