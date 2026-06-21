# Secrets

This directory is gitignored. Create these files manually before applying manifests.

## pihole-secret.yaml
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: pihole-secret
  namespace: pihole
stringData:
  WEBPASSWORD: "your-pihole-password"
```

## searxng-secret.yaml
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: searxng-secret
  namespace: searxng
stringData:
  secret_key: "$(openssl rand -hex 32)"
```

## kube-prometheus-stack-values.secret.yaml
Copy `monitoring/kube-prometheus-stack-values.yaml` to `monitoring/kube-prometheus-stack-values.secret.yaml`
and fill in real values for:
- `alertmanager.config.global.smtp_auth_password` — Gmail app password
- `alertmanager.config.global.smtp_from` / `smtp_auth_username` — your email
- `alertmanager.config.receivers[0].email_configs[0].to` — alert recipient email
- `grafana.adminPassword` — Grafana admin password

Apply with:
```bash
kubectl apply -f kubernetes/secrets/
helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  -n monitoring -f kubernetes/monitoring/kube-prometheus-stack-values.secret.yaml
```
