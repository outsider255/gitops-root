# najtanszaplansza.pl deployment

Argo CD applies the manifests in this directory. Secrets are provisioned out of band and must
exist before an image requiring them is deployed.

Required Secrets in namespace `planszomat`:

- `ghcr-pull`: registry credentials used by every application workload.
- `planszomat-db`: `POSTGRES_PASSWORD` and `PLANSZOMAT_DB`.
- `planszomat-identity`: `ZITADEL_ISSUER`, `OIDC_AUDIENCE`, and `ZITADEL_ROLE_CLAIM`.
- `planszomat-bgg`: `BGG_API_TOKEN`.
- `planszomat-openrouter`: `OPENROUTER_API_KEY` (check-shipping only).
- `planszomat-typesafe`: `TYPESAFE_API_KEY` (classify-names-worker, Jev).

The API accepts only access tokens issued by the configured Planszomat ZITADEL instance for the
configured audience. Administrator routes additionally require the `planszomat.admin` project
role in the configured role claim. The legacy `planszomat-supabase` Secret is no longer consumed;
removing that Secret or deleting the external Supabase project is a separate operational action.
