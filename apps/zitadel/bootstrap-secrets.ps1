<#
.SYNOPSIS
Creates the five out-of-band ZITADEL Secrets on the k3s cluster. Idempotent.

.DESCRIPTION
Every value ZITADEL needs at bring-up is generated, never fetched from a third-party
dashboard, so this runs unattended. It creates only the Secrets that are missing; a
second run with all five present writes nothing.

Values are generated in this process, encoded, and piped to the cluster over the SSH
access the operator already has. They are never passed as command arguments (so they
never reach a shell history or a process list), never written to a file on the node,
and never committed. The one file this writes is the escrow bundle: the material that
cannot be regenerated after the fact, for the operator password manager.

Non-secret resources stay owned by ArgoCD. This touches Secrets only.

.EXAMPLE
  pwsh apps/zitadel/bootstrap-secrets.ps1
#>
[CmdletBinding()]
param(
    [string] $SshTarget = 'ubuntu@ns3098488.ip-54-36-172.eu',
    [string] $Namespace = 'zitadel',

    # First human administrator of the System instance. Signs in once, then must
    # change the password (PasswordChangeRequired).
    [string] $AdminUserName = 'zitadel-admin',
    [Parameter(Mandatory = $false)][string] $AdminEmail = 'giffcik.pl@gmail.com',

    [string] $PostgresHost = 'zitadel-postgres.zitadel.svc.cluster.local',

    [string] $EscrowPath = (Join-Path $HOME ('zitadel-escrow-{0:yyyyMMdd-HHmmss}.txt' -f (Get-Date)))
)

$ErrorActionPreference = 'Stop'

# Passwords that end up inside a connection string or YAML use letters and digits
# only. Percent-encoding a DSN password correctly is a real hazard; not generating
# a password that needs encoding removes it.
$Alphanumeric = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
$Symbols = '!@#$%^&*_-+='

function New-RandomString {
    param([int] $Length, [string] $Alphabet)
    $chars = $Alphabet.ToCharArray()
    -join (1..$Length | ForEach-Object {
        $chars[[System.Security.Cryptography.RandomNumberGenerator]::GetInt32($chars.Length)]
    })
}

function New-HumanPassword {
    # ZITADEL's default complexity policy wants upper, lower, digit and symbol.
    do {
        $candidate = New-RandomString -Length 24 -Alphabet ($Alphanumeric + $Symbols)
    } until (
        $candidate -cmatch '[A-Z]' -and $candidate -cmatch '[a-z]' -and
        $candidate -match '[0-9]' -and $candidate -match '[!@#$%^&*_+=-]'
    )
    $candidate
}

function Invoke-Cluster {
    param([string] $Arguments, [string] $Stdin)
    if ($PSBoundParameters.ContainsKey('Stdin')) {
        $Stdin | ssh -o BatchMode=yes $SshTarget "sudo k3s kubectl -n $Namespace $Arguments"
    }
    else {
        ssh -o BatchMode=yes $SshTarget "sudo k3s kubectl -n $Namespace $Arguments"
    }
}

function Test-Secret {
    param([string] $Name)
    Invoke-Cluster -Arguments "get secret $Name" 2>&1 | Out-Null
    $LASTEXITCODE -eq 0
}

function Get-SecretValue {
    param([string] $Name, [string] $Key)
    # jsonpath keys containing a dot need escaping; none of the keys read back here do.
    $encoded = Invoke-Cluster -Arguments "get secret $Name -o jsonpath={.data.$Key}"
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($encoded)) {
        throw "could not read $Name/$Key back from the cluster"
    }
    [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encoded))
}

function New-Secret {
    param([string] $Name, [hashtable] $Data)

    $entries = foreach ($key in $Data.Keys) {
        '  {0}: {1}' -f $key, [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Data[$key]))
    }

    # Piped to `create` on stdin: no plaintext argument, no file on the node, no
    # committed manifest. `create` rather than `apply` so an existing Secret is
    # never silently overwritten.
    $manifest = @"
apiVersion: v1
kind: Secret
metadata:
  name: $Name
  namespace: $Namespace
type: Opaque
data:
$($entries -join "`n")
"@

    Invoke-Cluster -Arguments 'create -f -' -Stdin $manifest | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "creating Secret $Name failed" }
    Write-Host "  + $Name created" -ForegroundColor Green
}

Write-Host "ZITADEL secret bootstrap -> $SshTarget, namespace $Namespace" -ForegroundColor Cyan

Invoke-Cluster -Arguments 'get serviceaccount default' 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "namespace $Namespace is not reachable; ArgoCD creates it, do not create it here" }

$escrow = [ordered]@{}

# --- zitadel-db -------------------------------------------------------------
if (Test-Secret 'zitadel-db') {
    Write-Host '  = zitadel-db exists, unchanged'
    $postgresPassword = Get-SecretValue -Name 'zitadel-db' -Key 'POSTGRES_PASSWORD'
    $zitadelPassword = Get-SecretValue -Name 'zitadel-db' -Key 'ZITADEL_PASSWORD'
}
else {
    $postgresPassword = New-RandomString -Length 32 -Alphabet $Alphanumeric
    $zitadelPassword = New-RandomString -Length 32 -Alphabet $Alphanumeric
    New-Secret -Name 'zitadel-db' -Data @{
        POSTGRES_PASSWORD = $postgresPassword
        ZITADEL_PASSWORD  = $zitadelPassword
    }
    $escrow['postgres superuser password'] = $postgresPassword
    $escrow['zitadel database role password'] = $zitadelPassword
}

# --- zitadel-masterkey ------------------------------------------------------
# Exactly 32 printable ASCII bytes. It cannot be rotated after initialization and
# a surviving database is unreadable without it.
if (Test-Secret 'zitadel-masterkey') {
    Write-Host '  = zitadel-masterkey exists, unchanged'
}
else {
    $masterkey = New-RandomString -Length 32 -Alphabet $Alphanumeric
    New-Secret -Name 'zitadel-masterkey' -Data @{ masterkey = $masterkey }
    $escrow['masterkey (unrecoverable if lost)'] = $masterkey
}

# --- zitadel-runtime-config -------------------------------------------------
# Overlaid after the Git-tracked ConfigMap, so it must repeat FirstInstance.Skip:
# false. Retiring bootstrap access later replaces this Secret with an overlay that
# drops the whole FirstInstance mapping. See README.md.
if (Test-Secret 'zitadel-runtime-config') {
    Write-Host '  = zitadel-runtime-config exists, unchanged'
}
else {
    $adminPassword = New-HumanPassword
    $runtimeConfig = @"
Database:
  postgres:
    Host: $PostgresHost
    Port: 5432
    Database: zitadel
    MaxOpenConns: 20
    MaxIdleConns: 10
    User:
      Username: zitadel
      Password: "$zitadelPassword"
      SSL:
        Mode: disable
    Admin:
      Username: postgres
      Password: "$postgresPassword"
      ExistingDatabase: postgres
      SSL:
        Mode: disable
FirstInstance:
  Skip: false
  Org:
    Human:
      UserName: $AdminUserName
      Password: "$adminPassword"
      PasswordChangeRequired: true
      Email:
        Address: $AdminEmail
        Verified: true
"@
    New-Secret -Name 'zitadel-runtime-config' -Data @{ 'config-yaml' = $runtimeConfig }
    $escrow['first admin username'] = $AdminUserName
    $escrow['first admin email'] = $AdminEmail
    $escrow['first admin password (change on first sign-in)'] = $adminPassword
}

# --- zitadel-login-service-key ----------------------------------------------
# RSA keypair for the login-client System API user. The chart mounts tls.crt into
# ZITADEL and tls.key into the Login V2 container, which signs RS256 JWTs with it.
if (Test-Secret 'zitadel-login-service-key') {
    Write-Host '  = zitadel-login-service-key exists, unchanged'
}
else {
    $loginKey = [System.Security.Cryptography.RSA]::Create(2048)
    $request = [System.Security.Cryptography.X509Certificates.CertificateRequest]::new(
        'CN=login-client', $loginKey,
        [System.Security.Cryptography.HashAlgorithmName]::SHA256,
        [System.Security.Cryptography.RSASignaturePadding]::Pkcs1)
    $certificate = $request.CreateSelfSigned(
        [DateTimeOffset]::UtcNow.AddDays(-1), [DateTimeOffset]::UtcNow.AddYears(10))

    New-Secret -Name 'zitadel-login-service-key' -Data @{
        'tls.crt' = $certificate.ExportCertificatePem()
        'tls.key' = $loginKey.ExportPkcs8PrivateKeyPem()
    }
    $escrow['login-client private key'] = $loginKey.ExportPkcs8PrivateKeyPem()
}

# --- zitadel-system-api-public ----------------------------------------------
# Only the public half reaches the cluster. The private half is the credential the
# instance-provisioning tool signs System API JWTs with; it stays with the operator.
if (Test-Secret 'zitadel-system-api-public') {
    Write-Host '  = zitadel-system-api-public exists, unchanged'
}
else {
    $systemKey = [System.Security.Cryptography.RSA]::Create(2048)
    New-Secret -Name 'zitadel-system-api-public' -Data @{
        'system-user.pub' = $systemKey.ExportSubjectPublicKeyInfoPem()
    }
    $escrow['system-bootstrap private key (never goes to the cluster)'] = $systemKey.ExportPkcs8PrivateKeyPem()
}

# --- escrow -----------------------------------------------------------------
if ($escrow.Count -eq 0) {
    Write-Host 'Nothing generated; every Secret was already present.' -ForegroundColor Cyan
    return
}

$report = foreach ($name in $escrow.Keys) { "## $name`n$($escrow[$name])`n" }
@"
ZITADEL operator escrow - generated $((Get-Date).ToUniversalTime().ToString('u'))
Cluster: $SshTarget, namespace $Namespace

Move every value below into the password manager, then delete this file.
There is no off-node backup of the ZITADEL database; these values are the only
copies outside the cluster.

$($report -join "`n")
"@ | Set-Content -Path $EscrowPath -Encoding utf8

Write-Host ''
Write-Host "Escrow written to $EscrowPath" -ForegroundColor Yellow
Write-Host 'Move it into the password manager and delete the file.' -ForegroundColor Yellow
Invoke-Cluster -Arguments 'get secret'
