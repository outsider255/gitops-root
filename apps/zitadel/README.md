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

## Metrics exposure

The public Traefik route explicitly denies the `/debug/metrics` endpoint on both
ZITADEL hosts before it reaches the core Service. Its boundary-aware matcher covers both
the literal separator and case-insensitive encoded `%2F`, so an encoded slash cannot be
decoded by the backend into a metrics request. It leaves unrelated `/debug/*` endpoints
and the System/Product Login V2 routes unchanged. Prometheus must scrape core metrics
directly through the rendered `zitadel` Service and its ServiceMonitor; it must not use
either public hostname.

## Public routing-header boundary

Before forwarding either public hostname, Traefik removes client-supplied
`X-Zitadel-Instance-Host`, `X-Zitadel-Public-Host`, and
`X-Zitadel-Forward-Host` request headers. The Headers middleware uses empty
`customRequestHeaders` values, which remove the listed headers; it deliberately
does not change `Host`, so the actual requested hostname remains available to
ZITADEL. The same sanitizer precedes the metrics-deny middleware as defense in
depth.

Login V2's `ZITADEL_API_URL=http://zitadel:8080` is a cluster-local Service call,
not a public Traefik route. It therefore bypasses this edge sanitizer and keeps
the trusted routing headers synthesized on ZITADEL's internal Login-to-core path.

After both issuer hosts are provisioned, prove the edge boundary without mutation:

```powershell
$identity = 'https://identity.najtanszaplansza.pl'
$product = 'https://login.najtanszaplansza.pl'

function Assert-SpoofedIssuer([string] $url, [string] $expectedIssuer, [string] $spoofedHost) {
  $headers = @{
    'X-Zitadel-Instance-Host' = $spoofedHost
    'X-Zitadel-Public-Host' = $spoofedHost
    'X-Zitadel-Forward-Host' = $spoofedHost
  }
  $document = Invoke-RestMethod "$url/.well-known/openid-configuration" -Headers $headers
  if ($document.issuer -ne $expectedIssuer) {
    throw "Spoofed routing headers changed $url issuer to $($document.issuer)"
  }
}

Assert-SpoofedIssuer $identity $identity 'login.najtanszaplansza.pl'
Assert-SpoofedIssuer $product $product 'identity.najtanszaplansza.pl'
```

The first check proves the System host cannot be routed to the product issuer;
the second proves the product host cannot be routed to the System or another issuer.

Create these Secrets out of band. Secret values and rendered Secret manifests must
remain outside Git.

```text
zitadel-db
  POSTGRES_PASSWORD
  ZITADEL_PASSWORD

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

`zitadel-db/POSTGRES_PASSWORD` is the bootstrap-only PostgreSQL administrator
password. `zitadel-db/ZITADEL_PASSWORD` is the separate raw runtime DSN password
for the non-superuser `zitadel` LOGIN role; both values are created out of band and
must not appear in Git. On an empty data directory, the repository-owned single
executable init script creates or updates the role and creates the `zitadel`
database idempotently. PostgreSQL's official entrypoint runs that script only
during first initialization; changing either password later requires an
operator-managed PostgreSQL role rotation.

The provisioning wizard must put the raw `ZITADEL_PASSWORD` in the Kubernetes
Secret and PostgreSQL init environment unchanged. When constructing the ZITADEL
runtime PostgreSQL DSN, percent-encode the password as URI userinfo (for example,
raw `p@ss:word#1` becomes `p%40ss%3Aword%231`) and YAML-quote the complete DSN.
Do not percent-encode the Kubernetes Secret value itself, and do not place a raw
password containing `:`, `@`, `#`, `%`, `?`, or `/` unquoted in YAML.

The PostgreSQL image is pinned to the official multi-architecture image
`postgres:16.15-alpine3.24@sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685`.
Patch upgrades can change the image
base and PostgreSQL binaries; review the official image release notes, test
compatibility, and update this pin deliberately. Existing data directories are
not reinitialized by the init script.

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

When changing either `zitadel-login-service-key` or the external
`zitadel-runtime-config` Secret, replace it out of band, then increment the
matching Git-tracked `zitadel.najtanszaplansza.pl/external-secret-revision`
value in both `podAnnotations` and `login.podAnnotations` in
`apps/zitadel/values.yaml`. Commit and push the values change through the normal
GitOps flow; ArgoCD updates both Pod templates, which performs the rollout
without a manual restart. After ArgoCD reports Synced and Healthy, verify core
readiness and a complete Login V2 flow before declaring the rotation complete.

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

DNS egress from runtime, bootstrap Jobs, and Login V2 combines the
`kube-system` namespace selector with CoreDNS' live stable
`k8s-app=kube-dns` pod label and permits only TCP/UDP port 53.

PostgreSQL accepts port 5432 only from the init, setup, and runtime core pods.
Traefik in `kube-system` reaches core on 8080 and Login V2 on 3000. Prometheus in
`monitoring` reaches the rendered metrics ports (core 8080 and Login V2 9464).
Login V2 can reach the core Service on 8080, matching the chart-rendered
`ZITADEL_API_URL=http://zitadel:8080` configuration. Runtime egress is limited to
DNS, PostgreSQL, outbound HTTPS, and SMTP STARTTLS on port 587. Bootstrap Jobs
need only DNS and PostgreSQL: disabling the chart machine/PAT writers removes
their Kubernetes API dependency.

Core, init, and setup use the repository-owned `zitadel-runtime` ServiceAccount;
Login V2 uses `zitadel-login`; PostgreSQL uses the separate repository-owned
`zitadel-postgres` ServiceAccount. All three set `automountServiceAccountToken: false`.
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

The PostgreSQL egress policy is deny-all by design (`policyTypes: Egress` with no
egress rules); database pods do not need outbound network access. Both the
PostgreSQL ingress allow-list and this deny-all egress policy are applied at sync
wave `-2`, before the StatefulSet at wave `-1`, avoiding an unrestricted first-sync
window.

### Bounded database credential rotation

This is bounded maintenance, not a zero-downtime procedure: one `zitadel` role
cannot accept old and new passwords simultaneously. Do not discard the old value
until every verification below passes.

1. Generate a new random password and retain both old and new values only in the
   operator password manager. The PostgreSQL admin password
   `zitadel-db/POSTGRES_PASSWORD` is unchanged by this procedure.
2. Prepare the raw new value as `zitadel-db/ZITADEL_PASSWORD`. Prepare the matching
   runtime `config-yaml` DSN with the password percent-encoded as URI userinfo and
   the complete DSN YAML-quoted. Keep the raw value unchanged in the Secret.
3. In a secure operator shell, load the new value from the password manager into an
   environment variable (never a command argument or shell-history assignment), then
   run an interactive `psql` session over TCP as the admin and execute:

   ```sql
   \getenv new_password NEW_PASSWORD
   ALTER ROLE zitadel PASSWORD :'new_password';
   ```

   Do not paste the password into SQL, a command line, or shell history.
4. Replace both external Secrets out of band: `zitadel-db/ZITADEL_PASSWORD` with the
   raw new value and `zitadel-runtime-config/config-yaml` with the new encoded,
   YAML-quoted DSN. Do not replace the admin password.
5. In one reviewed GitOps change, increment both revision annotations: the PostgreSQL
   Pod template annotation in `postgres.yaml` and core `podAnnotations` in
   `values.yaml`. Push through the normal Git/ArgoCD flow; do not claim completion
   from a Git commit alone.
6. Wait for ArgoCD to report the rollout complete, then wait for the PostgreSQL
   authenticated startup/readiness probe and core readiness. Verify positive TCP
   authentication with the new password and a complete ZITADEL application flow.
   Verify negative TCP authentication with the old password is rejected. These
   checks must use secure environment input, never argv or history.
7. Only after all positive and negative checks pass, remove the old value from the
   password manager and any secure temporary environment.

If verification fails, rollback is also bounded maintenance: restore the old role
password using the same secure `\getenv` method, restore both external Secrets, and
increment both revision annotations again in one reviewed GitOps change. Wait for
PostgreSQL and core readiness, then verify old-password TCP authentication and the
application flow before retiring the new value. Rollback does not claim uninterrupted
availability.

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
