# ZITADEL prerequisites

> [!CAUTION]
> **There is no off-node backup for PostgreSQL or the ZITADEL event store.** Loss
> of the `kraken` node or its local-path volume can permanently delete every
> identity. PVC retention is not a backup. No backup-age or restore alert exists
> while this remains true.

## Temporary ingress exposure risk (2026-09-03)

There is currently no fixed operator VPN or public CIDR to allow-list. Consequently,
`identity.najtanszaplansza.pl` is temporarily publicly reachable while it provides the
neutral ZITADEL System host. No IP allow-list is attached until a stable operator path
is supplied. `login.najtanszaplansza.pl` is the Planszomat product issuer/login host
and must remain free of an operator-only allow-list. Revisit this restriction when the
operator network path is established.

Create these Secrets out of band. Secret values and rendered Secret manifests must
remain outside Git.

```text
zitadel-db
  POSTGRES_PASSWORD

zitadel-masterkey
  masterkey

zitadel-runtime-config
  config-yaml

zitadel-login-service-key
  tls.crt
  tls.key
```

`config-yaml` contains the PostgreSQL DSN, the first-instance human administrator,
and the first-login password-change requirement. It must not appear in Git.

`zitadel-masterkey/masterkey` must be exactly 32 printable ASCII bytes. Store this
value in the operator password manager as well; it must not appear in Git.

The System API public-key Secret is also created out of band:

```text
zitadel-system-api-public
  system-user.pub
```

Keep the corresponding private key only in the password manager/operator workspace.

The external `system-bootstrap` System API user is the automation identity. The
chart's default `FirstInstance.Org.Machine` is disabled, so it does not generate
`iam-admin` machine/PAT Secrets, kubectl writer containers, or namespace RBAC.
The external `config-yaml` still supplies the first human administrator.

`zitadel-login-service-key` must be a stable `kubernetes.io/tls` Secret whose
`tls.crt` and `tls.key` form an RSA keypair. ZITADEL uses the public certificate
to verify Login V2 JWTs and Login V2 uses the private key to sign them. Create
and rotate it out of band; the Helm chart must not generate or manage this Secret.

When rotating this key, replace the external Secret with a matching RSA
certificate/private-key pair, then explicitly restart both the `zitadel-login`
and `zitadel` Deployments so they reload it. Verify core readiness and a complete
Login V2 flow before declaring rotation complete.

## Network-policy contract

The policies intentionally target only labels rendered by chart `10.0.4`:

- core: `app.kubernetes.io/name=zitadel`, instance `zitadel`, component `start`;
- Login V2: `app.kubernetes.io/name=zitadel-login`, instance `zitadel`, component
  `login`;
- bootstrap Jobs: name/instance `zitadel`, component `init` or `setup`.

The live ingress source is additionally pinned to
`app.kubernetes.io/name=traefik`, instance `traefik-kube-system`; metrics ingress
is pinned to `app.kubernetes.io/name=prometheus`, instance
`monitoring-kube-prometheus-prometheus`. Both also retain their
`kubernetes.io/metadata.name` namespace selectors.

PostgreSQL accepts port 5432 only from the init, setup, and runtime core pods.
Traefik in `kube-system` reaches core on 8080 and Login V2 on 3000. Prometheus in
`monitoring` reaches the rendered metrics ports (core 8080 and Login V2 9464).
Login V2 can reach the core Service on 8080, matching the chart-rendered
`ZITADEL_API_URL=http://zitadel:8080` configuration. Runtime egress is limited to
DNS, PostgreSQL, outbound HTTPS, and SMTP STARTTLS on port 587. Bootstrap Jobs
need only DNS and PostgreSQL: disabling the chart machine/PAT writers removes
their Kubernetes API dependency.

Core, init, and setup use the repository-owned `zitadel-runtime` ServiceAccount;
Login V2 uses `zitadel-login`. Both set `automountServiceAccountToken: false`.
The chart creates neither account and renders no Role or RoleBinding, so the
shared runtime/bootstrap account is unprivileged and no workload receives an API
token. Re-enable the chart machine/PAT writer only together with a separately
reviewed bootstrap identity and narrowly scoped RBAC.

The cluster uses flannel `10.42.0.0/16`, Service CIDR `10.43.0.0/16`, and the
single node address `54.36.172.108`. k3s enforces policies with kube-router
iptables chains, where Service traffic can be evaluated after DNAT as a pod or
node destination. External HTTPS and SMTP `ipBlock` rules therefore exclude the
Service CIDR, Pod CIDR, node `/32`, loopback, and link-local ranges. Explicit
DNS, PostgreSQL, and Login-to-core peers remain allowed. Update these exclusions
if cluster networking or node addresses change. An external provider resolving
inside an excluded cluster/link-local range is intentionally unreachable; broad
RFC1918 ranges are not excluded because providers may legitimately use them.

There is deliberately no namespace-wide default-deny policy. Add one only after
re-rendering the pinned chart and accounting for every setup, runtime, Login V2,
and operational path. PostgreSQL remains a headless ClusterIP Service and must
never receive a NodePort, LoadBalancer, Ingress, or tunnel Service.

## Monitoring and operator checks

The pinned chart creates `release: monitoring` ServiceMonitors for core
`/debug/metrics` and Login V2 `/metrics`. `monitoring.yaml` adds namespace-scoped
alerts for target health, certificate expiry, container restarts, PostgreSQL
readiness and disk space, and failed Jobs. Target health checks core and Login V2
as separate rendered Service families and uses explicit `absent()` branches;
PostgreSQL readiness likewise alerts when its pod series is missing.

Before enabling Alertmanager notifications, evaluate every expression in the
existing Prometheus UI and confirm that it returns only the intended ZITADEL
series. After the first live deployment, inspect the v4.17.1 `/debug/metrics`
output and add request-latency or error-rate alerts only for metric names that
are actually exposed; do not guess chart- or release-dependent names.

SMTP delivery is a provisioning runbook check, not an automated alert. Send a
test invitation or password-reset message to an operator-controlled mailbox,
confirm receipt, and record the time and SMTP endpoint used. The cluster has no
log aggregation or mailbox probe that could produce a truthful delivery alert.

## Deployment gate and read-only verification

Creating the five external Secrets, pushing GitOps `main`, and allowing ArgoCD
to sync are operator gates. Obtain explicit approval immediately before the push;
do not use manual `kubectl apply` or an out-of-band ArgoCD sync.

After ArgoCD reports the application Synced and Healthy, verify without mutation:

```powershell
kubectl -n zitadel get pods,jobs,svc,ingress,pvc
kubectl -n zitadel get certificate
Invoke-RestMethod https://identity.najtanszaplansza.pl/.well-known/openid-configuration
Invoke-WebRequest https://identity.najtanszaplansza.pl/debug/ready
Invoke-WebRequest https://identity.najtanszaplansza.pl/ui/v2/login
```

Expect one ready PostgreSQL pod, two ready core pods, two ready Login V2 pods,
successful setup Jobs, a bound retained PVC, Ready certificates, System-instance
discovery, and HTTP 200 readiness and login responses. The Planszomat hostname
cannot return issuer-specific discovery until its virtual instance is created by
the provisioning plan.
