# Cluster Stability Tracker

Running reference of what's been fixed to keep the k8s cluster stable, and what's still
outstanding. Update this as items get resolved or new ones surface — treat it as a
checklist, not a one-time report.

---

## Fixed

### 2026-08-15 — Single-node OOM cascade
`talos-76j-w0h` had accumulated ~half the cluster's pods (54 of ~110) and was running at
~91% memory, causing the kernel OOM-killer to SIGKILL containers across unrelated
namespaces (`argocd`, `metallb-system`, `monitoring`, `plane`, `cert-manager`) — looked
like a wave of unrelated app crashes but was one node's capacity problem. Fixed by cordoning
the node and relocating stateless pods with no local storage dependency onto
`talos-zlt-fqg`/`talos-97a-ilz`. Full writeup: `rak-mcps/RCA/rca-003-talos-worker-oom-cascade.md`.

### 2026-08-15 — `plane-worker` OOMKilled independently
Even after being relocated to a node with 49GB free, `plane-worker` kept getting
`OOMKilled` — its own container limit (512Mi) was too low. Bumped to 512Mi request / 1Gi
limit (matching `plane-api`'s tier) in `kubernetes/apps/plane/plane.yaml`, pushed, ArgoCD
synced. Confirmed running with 0 restarts.

### 2026-08-15 — Deprecated MetalLB service annotations
`pihole-dns-tcp`/`pihole-dns-udp` used the legacy `metallb.universe.tf/*` annotations,
firing a `deprecatedAnnotation` warning on every reconcile. Renamed to `metallb.io/*` in
`kubernetes/apps/pihole/pihole.yaml`. Confirmed MetalLB re-allocated the same IP
(192.168.0.202) cleanly, no more warnings.

### 2026-08-15 — `atlas-chronicle` CronJob failures
Six failed job pods (spanning 40h–2d16h old) turned out to be a transient Ollama
connectivity blip, most likely tied to the node incident above — not a code bug. The
CronJob's next scheduled run succeeded on its own before I even looked at it. Cleaned up
the two stale `Job` objects (`atlas-chronicle-29776350`, `atlas-chronicle-29777790`).

### 2026-08-15 — `atlas-pg-backup` silently sat 3 days without running
Investigating "why is the backup failing" surfaced that it wasn't failing — it was
mechanically fine every time it ran — but the run scheduled 2026-08-12 21:30 didn't
actually execute until 2026-08-15 16:07, a ~67 hour gap. Root cause: `atlas-pg-backups`'
PVC is pinned via `local-path` to node `talos-zlt-fqg`, and every DaemonSet pod on that
node (flannel, kube-proxy, metallb, node-exporter, nvidia-device-plugin, promtail) shows
an identical restart timestamp at 16:07 — the signature of the whole node going down and
coming back, not a one-off pod issue. Correction to an earlier note in this doc: the
backup PVC is **not** co-located with the primary DB (`atlas-postgres-0` runs on
`talos-76j-w0h`, a different node) — that part was already fine. The actual gap was that
nothing would have told us a 3-day silent miss happened. Fixed by wiring an Uptime Kuma
push heartbeat into the CronJob (`atlas/k8s/10-postgres.yaml`, commit `321da90`) —
`status=up` after a successful dump+prune, `status=down` immediately on `pg_dump`
failure, monitor expects a heartbeat within 25h. Verified end-to-end with a manual test
run.

---

## Outstanding — needs planning

| Item | Why it matters | Effort |
|---|---|---|
| **Install `metrics-server`** | `kubectl top nodes/pods` doesn't work anywhere in the cluster. The OOM cascade took raw kubelet `stats/summary` API calls to diagnose instead of a 10-second `kubectl top` check. | Small — one manifest |
| **Add a descheduler** (`LowNodeUtilization` policy) | Nothing currently rebalances pods after initial scheduling — the imbalance that caused the OOM cascade can silently reaccumulate on any node. | Medium |
| **Local-path storage placement discipline** | `talos-76j-w0h` is permanently pinned as home to 7 stateful apps (`nextcloud`, `minio`, `idea-capture`, `n8n`, `atlas-postgres`, `vaultwarden`, `incident-commander`) because `local-path` PVs bind to whichever node they were first provisioned on. New stateful apps will keep landing there by default unless deliberately placed (`nodeSelector`) elsewhere, or the cluster moves to non-node-local storage (Longhorn/Rook). | Large if migrating storage; small if just adding nodeSelectors going forward |
| **Duplicate MetalLB config files** | `kubernetes/cluster-setup/metallb-config.yaml` (old, unreferenced) and `kubernetes/apps/metallb-config/metallb-config.yaml` (new, ArgoCD-managed) both exist per the comment in the new file — remove the old one once the new one is confirmed live. | Small, already noted in-repo |
| **`talos-zlt-fqg` unexplained ~3-day outage** | Every pod on this node (the GPU worker) restarted simultaneously around 2026-08-15 16:07, and it was apparently down/unreachable since around 2026-08-12 — discovered only as a side effect of debugging the stale backup above. In-cluster event history had already expired (1h TTL) by the time this was noticed, so the cause is unknown from `kubectl` alone. Needs `talosctl dmesg`/`talosctl logs` against that node, or checking the Proxmox host it runs on. | Unknown until investigated |
| **No app-level backups beyond Atlas Postgres** | Nextcloud, Vaultwarden, Plane (Postgres + MinIO), n8n all have zero backup coverage, and nothing existing is off-site — a homelab-wide event (fire/theft/extended outage) loses everything. Plan in progress: restic → Google Drive (rclone backend, already-paid-for storage), covering the apps with real data, explicitly excluding Prometheus/Loki/Grafana (regenerable). | Medium |

## In progress (not mine to touch — flagging for visibility)
As of 2026-08-15 the repo has uncommitted work already underway: a SOPS/secrets migration
(`.sops.yaml`, `kubernetes/secrets/`) and a MetalLB CRD restructure
(`kubernetes/apps/metallb-config/`). Left untouched during the fixes above.
