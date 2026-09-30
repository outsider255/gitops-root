<#
.SYNOPSIS
Creates the out-of-band `planszomat-identity` Secret the Planszomat API requires. Idempotent.

.DESCRIPTION
The ZITADEL-only API refuses to start without ZITADEL_ISSUER, OIDC_AUDIENCE and
ZITADEL_ROLE_CLAIM (see apps/planszomat/README.md). This creates the Secret only when it is
missing; an existing Secret is never overwritten. The values are identifiers, not credentials,
but they live in a Secret so the API manifest stays free of environment-specific settings.

The manifest is piped to `kubectl create -f -` over SSH: nothing is written on the node and
nothing is committed. Non-secret resources stay owned by ArgoCD.

.PARAMETER Audience
The Planszomat application identifier from the najtanszaplansza.pl ZITADEL instance
(the value the API validates as the access token audience). Required.

.EXAMPLE
  pwsh tools/planszomat-identity/bootstrap-secret.ps1 -Audience <planszomat-client-or-project-id>
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string] $Audience,
    [string] $Issuer = 'https://login.najtanszaplansza.pl',
    [string] $RoleClaim = 'urn:zitadel:iam:org:project:roles',
    [string] $SshTarget = 'ubuntu@ns3098488.ip-54-36-172.eu',
    [string] $Namespace = 'planszomat'
)

$ErrorActionPreference = 'Stop'

function Invoke-Cluster {
    param([string] $Arguments, [string] $Stdin)
    if ($PSBoundParameters.ContainsKey('Stdin')) {
        $Stdin | ssh -o BatchMode=yes $SshTarget "sudo -n k3s kubectl -n $Namespace $Arguments"
    }
    else {
        ssh -o BatchMode=yes $SshTarget "sudo -n k3s kubectl -n $Namespace $Arguments"
    }
}

if ($Issuer -notmatch '^https://') { throw "Issuer must be an https URL: $Issuer" }
if ([string]::IsNullOrWhiteSpace($Audience)) { throw 'Audience must not be blank.' }

Invoke-Cluster -Arguments 'get serviceaccount default' 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "namespace $Namespace is not reachable; ArgoCD creates it, do not create it here" }

Invoke-Cluster -Arguments 'get secret planszomat-identity' 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host '= planszomat-identity exists, unchanged (delete it explicitly to replace it)'
    return
}

$data = [ordered]@{
    ZITADEL_ISSUER     = $Issuer
    OIDC_AUDIENCE      = $Audience
    ZITADEL_ROLE_CLAIM = $RoleClaim
}
$entries = foreach ($key in $data.Keys) {
    '  {0}: {1}' -f $key, [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($data[$key]))
}
# `create`, not `apply`: an existing Secret is never silently overwritten.
$manifest = @"
apiVersion: v1
kind: Secret
metadata:
  name: planszomat-identity
  namespace: $Namespace
type: Opaque
data:
$($entries -join "`n")
"@

Invoke-Cluster -Arguments 'create -f -' -Stdin $manifest | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'creating Secret planszomat-identity failed' }
Write-Host '+ planszomat-identity created' -ForegroundColor Green
Invoke-Cluster -Arguments "get secret planszomat-identity -o go-template='{{range `$k, `$v := .data}}{{println `$k}}{{end}}'"
