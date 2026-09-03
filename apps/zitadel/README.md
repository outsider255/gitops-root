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
and the first-login password-change requirement. It must not appear in Git. For
the initial empty-database install it must explicitly set
`FirstInstance.Skip: false`; the Git-tracked config sets the same value. The
chart passes its ConfigMap first and this external file second, so a later
external value wins. Treat a missing, null, or conflicting external Skip value
as a deployment blocker rather than relying on merge behavior or chart defaults.

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

### Retire bootstrap access after provisioning

Retirement is required after provisioning, but it must not start until two
independent human administrators have enrolled MFA or passkeys and each has
separately proved sign-in and System administration. Then prepare and review one
coordinated retirement change before mutating either source:

1. replace `zitadel-runtime-config/config-yaml` out of band with an overlay that
   removes the entire `FirstInstance` mapping, including `Org.Human`, its
   password, and `Skip`;
2. in the reviewed GitOps change, set the Git-tracked `FirstInstance.Skip` to
   `true`, retain `FirstInstance.Org.Machine: null` so chart machine/PAT writers
   and RBAC stay disabled, and increment the external Secret revision on the
   core Pod template;
3. before push, parse the private overlay without printing it and fail unless
   `FirstInstance` is absent; render the pinned chart and fail unless the
   ConfigMap contains `FirstInstance.Skip: true` and no Human material;
4. push only after the Secret replacement and Git change are both ready, wait
   for ArgoCD and both core replicas, then recheck both independent human-admin
   sessions before destroying the retired first-human password.

The external overlay is later in the rendered argument order. Leaving
`FirstInstance.Skip: false` there would override the Git-tracked retirement, so
removing the whole mapping is mandatory; changing only the password is not
retirement.

If an empty database must be rebuilt, use a separately reviewed recovery plan
that deliberately returns both sources to controlled bootstrap: set the
Git-tracked Skip to `false`, provide a new external `FirstInstance` Human with
`Skip: false`, stage the child Application manually, and repeat the retirement
after recovery. Never omit Skip, restore the chart's default machine, or rely on
default credentials as a recovery shortcut.

If automation remains after human bootstrap retirement, provision and test a
replacement identity with only the roles it needs. Otherwise record that no
automation depends on `system-bootstrap`, remove or de-scope its declaration and
public-key mount in a reviewed GitOps change, verify the core rollout, revoke the
old credential, delete the now-unreferenced public-key Secret, and destroy its
private key. Never delete a referenced Secret first.

### Rotate the System API user key

ZITADEL v4.17.1 constructs the System token verifier in every running core
process from `SystemAPIUsers`. It reads the mounted public-key file on first use
and caches a raw RSA key without expiry for the life of that process. Setup does
not persist this authentication key. Replacing `zitadel-system-api-public`
therefore does not update a core process that has cached the old key; a rollout
using the dedicated core-only
`zitadel.najtanszaplansza.pl/system-api-key-revision` annotation is required.

Same-subject rotation is bounded maintenance, not zero downtime. Retain the old
keypair until all checks pass, freeze unrelated GitOps changes, and prepare and
review two unpushed revision commits: a forward bump and a distinct rollback
bump. If a change freeze cannot be guaranteed, first use a reviewed GitOps
commit to make the child Application manual, and make the prepared forward
commit both bump the revision and restore automated sync. Do not pause or sync
the child through the UI.

1. generate the replacement RSA keypair in a secure operator workspace; store
   both private keys only in the password manager and never in Git, chat, argv,
   shell history, transcripts, or command output;
2. create the exact replacement for `zitadel-system-api-public/system-user.pub`
   from the new public key, but keep it unsubmitted until the forward and
   rollback revision commits have passed review;
3. replace that external Secret securely, then immediately non-force-push the
   reviewed forward revision commit through the normal GitOps approval gate;
4. wait for `kubectl -n zitadel rollout status deployment/zitadel` and verify
   exactly two Ready core Pods carry the new system-api-key revision annotation;
5. create short-lived JWTs with issuer `system-bootstrap` and audience
   `https://identity.najtanszaplansza.pl`; call the read-only
   `POST /system/v1/instances/_search` probe with the new JWT and require success, then
   call it with the old JWT and require HTTP 401 or 403;
6. clear both JWTs from memory and destroy the old private key only after the
   new-positive and old-negative checks pass on the fully rolled core Deployment.

The probe can be performed without printing either token:

```powershell
$probe = 'https://identity.najtanszaplansza.pl/system/v1/instances/_search'
$body = '{"query":{"limit":1}}'
$newJwt = (& zitadel-tools key2jwt --audience=https://identity.najtanszaplansza.pl --issuer=system-bootstrap --key $newPrivateKeyPath).Trim()
$oldJwt = (& zitadel-tools key2jwt --audience=https://identity.najtanszaplansza.pl --issuer=system-bootstrap --key $oldPrivateKeyPath).Trim()
try {
  Invoke-RestMethod $probe -Method Post -ContentType 'application/json' -Body $body -Headers @{ Authorization = "Bearer $newJwt" } | Out-Null
  $oldAccepted = $true
  try {
    Invoke-RestMethod $probe -Method Post -ContentType 'application/json' -Body $body -Headers @{ Authorization = "Bearer $oldJwt" } | Out-Null
  } catch {
    $status = [int] $_.Exception.Response.StatusCode
    if ($status -notin 401, 403) { throw }
    $oldAccepted = $false
  }
  if ($oldAccepted) { throw 'old System API JWT is still accepted' }
} finally {
  Remove-Variable newJwt, oldJwt -ErrorAction SilentlyContinue
}
```

If verification fails, replace the external Secret with the retained old public
key, push the already-reviewed rollback commit with a new revision value, wait
for both core replicas, and require the inverse checks: old JWT succeeds and new
JWT fails. Do not decrement or reuse a Pod-template revision value.

For seamless overlap, do not replace the key behind one subject. Add a temporary
second System API user such as `system-bootstrap-next`, backed by a separate
external Secret and mount, with the minimum memberships required. Roll out and
verify its JWT, migrate automation, then remove the old user/mount and roll core
again before deleting the old Secret. This is a multi-change reviewed migration,
not the bounded single-user procedure above.

`zitadel-login-service-key` must be a stable `kubernetes.io/tls` Secret whose
`tls.crt` and `tls.key` form an RSA keypair. ZITADEL uses the public certificate
to verify Login V2 JWTs and Login V2 uses the private key to sign them. Create
and rotate it out of band; the Helm chart must not generate or manage this Secret.

When changing `zitadel-runtime-config`, increment the Git-tracked
`zitadel.najtanszaplansza.pl/external-secret-revision` under core
`podAnnotations`. When changing `zitadel-login-service-key`, increment that
annotation under both core `podAnnotations` and `login.podAnnotations`, because
core verifies the public certificate and Login V2 signs with the private key.
Commit and push the values change through the normal GitOps flow; ArgoCD updates
the affected Pod templates without a manual restart. After ArgoCD reports
Synced and Healthy, verify core readiness and a complete Login V2 flow before
declaring the rotation complete.

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
3. Before maintenance, locally validate the new raw Secret payload, its
   percent-encoded DSN userinfo, and the YAML-quoted complete DSN using reserved-
   character test fixtures. Confirm operator TCP/admin access. Prepare the exact
   out-of-band replacements for both Secrets, and prepare and review/approve the
   forward GitOps revision bump for both Pod templates and the rollback revision bump
   for both Pod templates. Keep both reviewed changes unpushed; do not start
   maintenance until all of these preparations are complete.
4. In a secure operator shell, load the new value from the password manager into an
   environment variable (never a command argument or shell-history assignment), then
   run an interactive `psql` session over TCP as the admin and execute:

   ```sql
   \getenv new_password NEW_PASSWORD
   ALTER ROLE zitadel PASSWORD :'new_password';
   ```

   Do not paste the password into SQL, a command line, or shell history.
5. Immediately replace both external Secrets out of band: `zitadel-db/ZITADEL_PASSWORD` with the
   raw new value and `zitadel-runtime-config/config-yaml` with the new encoded,
   YAML-quoted DSN. Do not replace the admin password.
6. Immediately after both Secrets are replaced, push the already-reviewed forward
   GitOps change that increments both revision annotations: the PostgreSQL Pod template
   annotation in `postgres.yaml` and core `podAnnotations` in `values.yaml`. This is
   the sole forward push through the normal Git/ArgoCD flow. No approval or review step
   is allowed inside the outage bound.
7. Wait for ArgoCD to report the rollout complete, then wait for the PostgreSQL
   authenticated startup/readiness probe and core readiness. Verify positive TCP
   authentication with the new password and a complete ZITADEL application flow.
   Verify negative TCP authentication with the old password is rejected. These
   checks must use secure environment input, never argv or history.
8. Only after all positive and negative checks pass, remove the old value from the
   password manager and any secure temporary environment.

If verification fails, use the already-prepared and reviewed but still unpushed
rollback artifacts immediately (no new approval or review inside the outage): restore the old role
password using the same secure `\getenv` method, restore both external Secrets, and
push the prepared rollback revision change for both annotations (it remains unpushed
unless rollback is needed). Wait for PostgreSQL
and core readiness, then verify old-password TCP authentication and the application
flow. Also verify negative TCP authentication with the new password before retiring
it. Rollback does not claim uninterrupted availability.

## Monitoring and operator checks

The pinned chart creates `release: monitoring` ServiceMonitors for core
`/debug/metrics` and Login V2 `/metrics`. The repository PodMonitor labelled
`release: monitoring` selects the cert-manager controller in the `cert-manager`
namespace by its live stable name, instance, and component labels and scrapes
the `http-metrics` port. `honorLabels: true` preserves cert-manager's exported
certificate `namespace` and `name` labels, which the certificate alerts use.
The PodMonitor and PrometheusRule are sync wave `5`, after the wave-4 Ingresses
request their certificates.

`monitoring.yaml` adds namespace-scoped alerts for target health, certificate
expiry, certificate readiness and missing certificate expiry, container
restarts, PostgreSQL readiness and disk space, and failed Jobs. Target health
checks core and Login V2 as separate rendered Service families and uses explicit
`absent()` branches; PostgreSQL readiness likewise alerts when missing. Missing
Ready series are folded into `ZitadelCertificateNotReady`. A missing expiry
series alerts only when that certificate's Ready series equals 1. Certificate
alerts wait 15 minutes, so the normal ingress/cert-manager rollout does not
produce separate missing and not-ready alerts for the same certificate. Before
deployment, exactly two NotReady vectors and zero expiry/expiry-missing vectors
are expected because neither ZITADEL certificate exists yet.

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

First installation depends on the two ordered commits named below. Preserve both
commits; do not squash, reorder, or push them together. The live cluster has no
pre-existing `zitadel` child Application. In the bootstrap commit the GitOps root
creates namespace `zitadel` at sync wave `-1`, then creates the child Application
at wave `0` without automated sync. This makes Secret creation possible without
letting the workload race ahead.

Use these non-force preflights and pushes from the reviewed feature branch. The
first preflight pins the fetched deployment base and stops if remote `main` has
moved; the second requires remote `main` to be exactly the reviewed bootstrap
commit. Neither command permits a force update.

```powershell
git fetch origin main
$expectedRemoteMain = '34edbe46153dd5d539d72c5d71b469fa441cab25'
$remoteMain = git rev-parse origin/main
$bootstrapCommit = git rev-list --max-count=1 --grep='^ops: stage zitadel namespace$' feature/zitadel-platform
if ($remoteMain -ne $expectedRemoteMain) { throw 'origin/main moved; fetch, rebase, and review again' }
git merge-base --is-ancestor $remoteMain $bootstrapCommit
if ($LASTEXITCODE -ne 0) { throw 'origin/main is not an ancestor of the bootstrap commit' }
git show --stat $bootstrapCommit
git push origin "${bootstrapCommit}:main"
```

1. obtain deployment approval and push only commit `ops: stage zitadel
   namespace` to GitOps `main`;
2. wait until `prod-bootstrap` is Synced/Healthy, namespace `zitadel` exists,
   and `kubectl -n argocd get application zitadel -o
   jsonpath='{.spec.syncPolicy.automated}'` prints nothing;
3. create all five external Secrets in namespace `zitadel`: `zitadel-db`,
   `zitadel-masterkey`, `zitadel-runtime-config`, `zitadel-login-service-key`,
   and `zitadel-system-api-public`;
4. obtain immediate approval for the deployment push, then run the second
   preflight and push below; commit `ops: enable zitadel deployment` restores
   automated sync and lets ArgoCD deploy the child Application;
5. wait for the child Application to become Synced/Healthy before running the
   checks below.

```powershell
git fetch origin main
$remoteMain = git rev-parse origin/main
$bootstrapCommit = git rev-list --max-count=1 --grep='^ops: stage zitadel namespace$' feature/zitadel-platform
$enableCommit = git rev-list --max-count=1 --grep='^ops: enable zitadel deployment$' feature/zitadel-platform
if ($remoteMain -ne $bootstrapCommit) { throw 'origin/main is not the reviewed bootstrap commit' }
git merge-base --is-ancestor $remoteMain $enableCommit
if ($LASTEXITCODE -ne 0) { throw 'bootstrap commit is not an ancestor of the enable commit' }
git show --stat $enableCommit
git push origin "${enableCommit}:main"
```

Never manually apply repository resources or trigger an out-of-band child sync
to bypass this sequence.

If the enable commit must be rolled back, revert and push only that commit. Its
revert removes automated sync but leaves the child Application, the
`Prune=false` Namespace, Secrets, and deployed platform resources in place for
diagnosis. Verify that remote `main` contains the enable commit, create the
revert on current remote `main`, and push it without force:

```powershell
git fetch origin main
$enableCommit = git rev-list --max-count=1 --grep='^ops: enable zitadel deployment$' origin/main
git merge-base --is-ancestor $enableCommit origin/main
if ($LASTEXITCODE -ne 0) { throw 'enable commit is not on current origin/main' }
git switch --create rollback/zitadel-enable origin/main
git revert --no-edit $enableCommit
git push origin HEAD:main
```

Namespace or platform teardown is a separate destructive operation requiring
its own plan and explicit approval; it is never part of ordinary rollback.

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
