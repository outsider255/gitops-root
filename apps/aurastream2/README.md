# aurastream2 — v2, deployed alongside v1

v2 runs in its own namespace, with its own SQL Server and its own database. **v1 (`apps/aurastream`)
is untouched** and keeps publishing until it is deliberately stood down at the end of
`docs/ops/cutover-runbook.md` in the aurastream2 repo.

Manifests are ported from `aurastream2/deploy/` with the cluster-specific placeholders resolved.
The reasoning behind each one (why the media PVC is RWO, why the streamer is `replicas: 1` +
`Recreate`, why the Api limit is 4Gi, the full config/secret inventory) lives in that repo's
`deploy/README.md` and in the comments here — those are not repeated.

## How v2 shares v1's hostname

Both are served from `ns3098488.ip-54-36-172.eu`. v1 owns everything; v2 owns `/v2`.

```
browser  https://ns3098488.ip-54-36-172.eu/v2/api/health
Traefik  Host(...) && PathPrefix(`/v2`)   priority 100   → strip /v2 → aurastream2-web
nginx    /api/health                                     → aurastream2-api:80
```

Three things must agree, or the console breaks in ways that look unrelated:

| Piece | Value | Set in |
|---|---|---|
| Traefik strips | `/v2` | `ingressroute.yaml` |
| SPA asset base | `/v2/` | `VITE_BASE_PATH` build arg (CI) |
| Router basename | `/v2/` | read from the same build via `import.meta.env.BASE_URL` |

`Publish__PublicMediaBaseUrl` (`configmap.yaml`) also carries the `/v2` prefix, because Buffer
fetches published media **by URL from the public internet** — dropping the prefix there yields links
that 404 for Buffer while working fine inside the cluster.

## Before the first sync

This Application is deliberately **manual-sync** (see `clusters/prod/53-aurastream2.yaml`). Four
things must be in place first — none of them can live in git:

1. **`aurastream2-secrets`** — from `deploy/secrets.example.yaml`. The Gemini/Veo/Suno keys and
   `Supabase__JwtSecret` are **boot-required**: without them the Api CrashLoopBackOffs rather than
   failing later on first use.
2. **`ghcr-pull`** — GHCR packages are private and pull secrets are namespaced, so v1's copy is not
   visible here.
3. **Image tags** — the three `REPLACE_WITH_SHA` placeholders. aurastream2's `main` must be pushed
   so CI publishes `aurastream2-{api,streamer,web}`; then set all three to that commit's full SHA.
4. **`Supabase__Issuer`** in `configmap.yaml` — still `REPLACE_WITH_SUPABASE_ISSUER_URL`.

CI's web build also needs the repo variables `VITE_BASE_PATH=/v2/`, `VITE_API_URL`,
`VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` — Vite inlines them at build time, so a missing one
produces a silently misconfigured image rather than a build failure.

Register `https://ns3098488.ip-54-36-172.eu/v2/api/youtube/callback` as a redirect URI on the Google
OAuth client before connecting a channel, or the connect popup fails at the callback.

## Known gaps carried from the aurastream2 repo

Both are documented there and are unchanged by this deployment — worth settling before this
hostname serves v2 in earnest:

- The **Data Protection key ring persists unencrypted** in the database, protecting the encrypted
  credential columns with an unencrypted key.
- **Supabase signups have no allowlist** — any authenticated user is a full operator, including the
  Hangfire dashboard and every stored credential.
