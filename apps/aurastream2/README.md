# aurastream2 — v2, deployed alongside v1

v2 runs in its own namespace, with its own SQL Server and its own database. **v1 (`apps/aurastream`)
is untouched** and keeps publishing until it is deliberately stood down at the end of
`docs/ops/cutover-runbook.md` in the aurastream2 repo.

Manifests are ported from `aurastream2/deploy/` with the cluster-specific placeholders resolved.
The reasoning behind each one (why the media PVC is RWO, why the streamer is `replicas: 1` +
`Recreate`, why the Api limit is 4Gi, the full config/secret inventory) lives in that repo's
`deploy/README.md` and in the comments here — those are not repeated.

## v2's own hostname (and the prefix route it replaced)

v2 is served from `aurastream.stocznia.dev`, at the root, with its own certificate:

```
browser  https://aurastream.stocznia.dev/api/health
Traefik  Host(`aurastream.stocznia.dev`)  → aurastream2-web
nginx    /api/health                      → aurastream2-api:80
```

Until this move, v2 shared v1's hostname `ns3098488.ip-54-36-172.eu` and owned `/aurastream2`
there, with Traefik stripping the prefix. **That route is still live**, deliberately: media URLs
Buffer already holds carry the old base. Both routes serve the same `aurastream2-web` Service, so
the old one keeps working for media even though the console it serves now asks for assets at the
root and will not render there.

Retire the old route — the `PathPrefix` IngressRoute and the `strip-aurastream2` Middleware,
together — at least 24 hours after `Publish__PublicMediaBaseUrl` changed to the new host, once no
scheduled post still points at the old base.

Two things must agree, or the console breaks in ways that look unrelated:

| Piece | Value | Set in |
|---|---|---|
| SPA asset base | `/` | `VITE_BASE_PATH` build arg (CI) |
| Router basename | `/` | read from the same build via `import.meta.env.BASE_URL` |

`Publish__PublicMediaBaseUrl` (`configmap.yaml`) is a third, independent value: Buffer fetches
published media **by URL from the public internet**, so it must be a host that resolves from
Buffer's servers, not a cluster-internal name.

## Cluster-side prerequisites

This Application runs `automated: {prune, selfHeal}` (see `clusters/prod/53-aurastream2.yaml`);
image tags are CI-managed (aurastream2's `bump-gitops` job). What cannot live in git:

1. **`aurastream2-secrets`** — from `deploy/secrets.example.yaml`. The Gemini/Veo/Suno keys are
   **boot-required**: without them the Api CrashLoopBackOffs rather than failing later on first
   use. No JWT secret is needed: prod validates tokens against ZITADEL's JWKS, discovered from
   `Oidc__Issuer`.
2. **`ghcr-pull`** — GHCR packages are private and pull secrets are namespaced, so v1's copy is not
   visible here.
3. **The ZITADEL application** — `Oidc__Audience` in `configmap.yaml` is its client ID. It is a
   PKCE public client (no secret), and two of its non-default settings are load-bearing: **Auth
   Token Type must be JWT** (ZITADEL issues opaque tokens otherwise, which the Api cannot
   validate) and **"Include user's profile info in the ID Token"** must be on (or the token
   carries no `email` claim).

CI's web build also needs the repo variables `VITE_BASE_PATH=/`, `VITE_OIDC_AUTHORITY` and
`VITE_OIDC_CLIENT_ID` — Vite inlines them at build time, so a missing one produces a silently
misconfigured image rather than a build failure. `VITE_API_URL` is deliberately unset: the console
calls the Api at a same-origin relative path.

Register `https://aurastream.stocznia.dev/api/youtube/callback` as a redirect URI on the Google
OAuth client before connecting a channel, or the connect popup fails at the callback.

## Known gaps carried from the aurastream2 repo

Both are documented there and are unchanged by this deployment — worth settling before this
hostname serves v2 in earnest:

- The **Data Protection key ring persists unencrypted** in the database, protecting the encrypted
  credential columns with an unencrypted key.
- **Authentication is the only authorization** — the Api's fallback policy is
  `RequireAuthenticatedUser` and nothing narrows it, so **any user who can sign in to the ZITADEL
  Internal Tools instance is a full operator**, including the Hangfire dashboard and every stored
  credential. ZITADEL's "Only authorized users can authenticate" project setting is the control
  that would fix this; ArgoCD shares that project, so grant roles before ticking it.
