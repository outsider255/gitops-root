# najtanszaplansza.pl deployment

Argo CD applies the manifests in this directory. Secrets are provisioned out of band and must
exist before an image requiring them is deployed.

Required Secrets in namespace `planszomat`:

- `ghcr-pull`: registry credentials used by every application workload.
- `planszomat-db`: `POSTGRES_PASSWORD` and `PLANSZOMAT_DB`.
- `planszomat-identity`: `ZITADEL_ISSUER`, `OIDC_AUDIENCE`, and `ZITADEL_ROLE_CLAIM`.
- `planszomat-typesafe`: `TYPESAFE_API_KEY` (catalog-nightly, Jev family judge).
- `planszomat-backup`: R2 endpoint and access key, rclone crypt password and salt (backup and
  restore-test CronJobs). Created by `Planszomat/scripts/bootstrap-backup-secret.ps1`; the crypt
  password and salt are also escrowed in the password manager — without them the R2 copies are
  unreadable.

No longer consumed, safe to delete: `planszomat-bgg`, `planszomat-openrouter`, `planszomat-gemini`.

The API accepts only access tokens issued by the configured Planszomat ZITADEL instance for the
configured audience. Administrator routes additionally require the `planszomat.admin` project
role in the configured role claim. The legacy `planszomat-supabase` Secret is no longer consumed;
removing that Secret or deleting the external Supabase project is a separate operational action.
