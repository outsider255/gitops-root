# ZITADEL prerequisites

Create these Secrets out of band. Secret values and rendered Secret manifests must
remain outside Git.

```text
zitadel-db
  POSTGRES_PASSWORD

zitadel-masterkey
  masterkey

zitadel-runtime-config
  config-yaml
```

`config-yaml` contains the PostgreSQL DSN, the first-instance human administrator,
and the first-login password-change requirement. It must not appear in Git.

The System API public-key Secret is also created out of band:

```text
zitadel-system-api-public
  system-user.pub
```

Keep the corresponding private key only in the password manager/operator workspace.
