# ArgoCD public surface

ArgoCD's **installation** is hand-applied and deliberately not in this repo — it cannot
bootstrap itself. Only its public surface is tracked here: the Ingress and the server
parameters that decide where the UI answers.

Before this, `argocd-server-ingress` had been applied by hand on 2026-06-22 and left
untracked for 77 days. It served the UI at `ns3098488.ip-54-36-172.eu/argocd`, with the
local admin password as the only thing in front of a control plane that can deploy
anything to the cluster.

## Ordering

DNS must resolve before ArgoCD syncs this, or cert-manager cannot solve the HTTP-01
challenge and the new hostname has no certificate:

```
A  argocd  54.36.172.108   DNS only (grey cloud)
```

The Ingress reuses `secretName: argocd-tls`, so cert-manager re-issues into the existing
Secret for the new name. Expect a NotReady Certificate for a few minutes; it retries on
its own.

## The restart

`server.basehref` and `server.rootpath` are startup parameters. Syncing the ConfigMap does
not restart anything, so the UI keeps serving under the old prefix until:

```
ssh ubuntu@ns3098488.ip-54-36-172.eu \
  "sudo k3s kubectl -n argocd rollout restart deploy/argocd-server"
```

Until that runs, `argocd.stocznia.dev` answers with a UI whose links still point at
`/argocd`. Both `/argocd` on the old host and the new host are unreachable in between —
short, and SSH is unaffected.

## SSO

ArgoCD is ZITADEL's first OIDC client. The application lives in project **Internal Tools**
on the first instance, `identity.stocznia.dev` — not on a dedicated internal-tools instance
as the platform design proposes, because creating a virtual instance needs the System API
and the operator-held signing key. Moving it later is re-registering one OIDC client.

`argocd-cm` **is** adopted here now. Its nine `resource.customizations` /
`resource.exclusions` keys are verbatim from the upstream install manifest and were checked
byte-for-byte against the live ConfigMap before adoption, so the only change is `url` and
`oidc.config`. The cost is that those defaults no longer move on an ArgoCD upgrade —
re-diff them against upstream when upgrading.

### The client secret

It is not in this repo, and `oidc.config` refers to it as `$oidc.zitadel.clientSecret`,
which ArgoCD resolves from Secret `argocd-secret`. Create it out of band, piped over stdin
so it is never a process argument or a shell-history line on the node:

```
$body = '{"stringData":{"oidc.zitadel.clientSecret":"<secret>"}}'
$body | ssh ubuntu@ns3098488.ip-54-36-172.eu `
  "sudo k3s kubectl -n argocd patch secret argocd-secret --type merge --patch-file /dev/stdin"
```

ZITADEL shows the secret exactly once, at application creation. If it is lost, regenerate
it in the console and re-run the patch — the client ID does not change.

### Ordering

The Secret must exist before `argocd-server` restarts, or the server starts with an empty
client secret and every login fails at the token exchange. Then:

```
ssh ubuntu@ns3098488.ip-54-36-172.eu \
  "sudo k3s kubectl -n argocd rollout restart deploy/argocd-server"
```

### RBAC

`argocd-rbac-cm` was empty, which is not "everyone is an admin" — it is the opposite. A
user who authenticates with no matching policy sees an empty UI and no error. It now
matches on the `email` claim, because ZITADEL's default claim set has no `groups`, which is
what ArgoCD looks for otherwise.

Local admin stays enabled: it is the way back in if OIDC breaks. Disabling it
(`admin.enabled: "false"` in `argocd-cm`) is worth doing only once a second person can log
in via SSO, so a single lost account cannot lock everyone out of the control plane.

### Quote the client ID

ZITADEL client IDs are all digits. `oidc.config` is a YAML block scalar that ArgoCD parses
itself, so an unquoted ID becomes a *number* and the server rejects the whole block:

```
invalid oidc config: cannot unmarshal number into Go struct field OIDCConfig.clientID of type string
```

This is a `warning`, not an error, and the server starts anyway — with `sso: false` in its
startup line and no login button. That log line is the only symptom.
