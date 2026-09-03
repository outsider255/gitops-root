# ZITADEL prerequisites

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

`zitadel-login-service-key` must be a stable `kubernetes.io/tls` Secret whose
`tls.crt` and `tls.key` form an RSA keypair. ZITADEL uses the public certificate
to verify Login V2 JWTs and Login V2 uses the private key to sign them. Create
and rotate it out of band; the Helm chart must not generate or manage this Secret.
