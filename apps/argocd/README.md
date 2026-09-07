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

## Stage two: SSO

`argocd-cm` currently has **no `oidc.config`**. Local admin is the only credential.

Once the ZITADEL instance at `identity.stocznia.dev` is provisioned, ArgoCD becomes its
first OIDC client: add `oidc.config` and `url: https://argocd.stocznia.dev` to `argocd-cm`,
then disable the local admin. ArgoCD is a better first client than Planszomat — no user
migration, small blast radius, and it retires a password-only public admin panel.

`argocd-cm` is not adopted here on purpose. It carries the whole `resource.customizations`
and `resource.exclusions` set, and a partial declaration would prune it. Both keys land
together in stage two.
