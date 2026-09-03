param(
    [string] $ManifestPath = (Join-Path $PSScriptRoot 'ingress.yaml')
)

$ErrorActionPreference = 'Stop'
$manifest = Get-Content -Raw $ManifestPath

function Require-Match([string] $Pattern, [string] $Description) {
    if ($manifest -notmatch $Pattern) {
        throw "Missing $Description"
    }
}

function Require-Count([string] $Pattern, [int] $Expected, [string] $Description) {
    $actual = [regex]::Matches($manifest, $Pattern).Count
    if ($actual -ne $Expected) {
        throw "$Description expected $Expected match(es), found $actual"
    }
}

Require-Match 'name:\s+zitadel-public-request-headers' 'public routing-header middleware'
foreach ($header in @('X-Zitadel-Instance-Host', 'X-Zitadel-Public-Host', 'X-Zitadel-Forward-Host')) {
    Require-Match ('(?m)^[\t ]+' + [regex]::Escape($header) + ':[\t ]+""[\t ]*\r?$') "empty removal value for $header"
}

Require-Match 'router\.middlewares:\s+zitadel-zitadel-public-request-headers@kubernetescrd,zitadel-zitadel-rate-limit@kubernetescrd' 'sanitizer before public rate limit'
Require-Count 'name:\s+zitadel-public-request-headers\s*\r?\n\s+- name:\s+zitadel-public-metrics-deny' 2 'metrics deny sanitizer chain'
Require-Count 'PathRegexp\(`\^/debug\(\?:/\|\(\?i:%2f\)\)metrics\(\?:\$\|/\|\(\?i:%2f\)\)`\)' 2 'bounded metrics routes'
Require-Count 'priority:\s+200' 2 'metrics route priorities'

foreach ($hostName in @('identity.najtanszaplansza.pl', 'login.najtanszaplansza.pl')) {
    Require-Match "host:\s+$([regex]::Escape($hostName))" "ordinary public host $hostName"
    Require-Match ([regex]::Escape(('Host(`' + $hostName + '`)'))) "metrics deny host $hostName"
}

if ($manifest -match '(?m)^\s+Host:\s+') {
    throw 'The edge middleware must preserve Host rather than replace it.'
}

Write-Output 'PASS: public routing-header sanitizer, public hosts, and metrics defense-in-depth are present.'
