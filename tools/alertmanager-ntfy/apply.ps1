<#
Builds the Alertmanager -> ntfy webhook URL from the templates in this folder and writes it into the
Secret monitoring/alertmanager-ntfy (key `url`), which Alertmanager reads via url_file.

The topic is the only secret part (anyone who knows it can read the alerts), so it is a parameter,
never committed. The value travels over stdin, not as a process argument.

  .\apply.ps1 -Topic <topic>            # write the Secret on kraken
  .\apply.ps1 -Topic <topic> -Preview   # send one sample alert to the topic instead

Templates are ntfy inline Go templates (sprig subset) over the Alertmanager webhook payload.
ntfy rejects a title template that is too long and any rendered message over ~4 KB — keep
lookup tables out of title.tmpl and test with -Preview before applying.
#>
param(
    [Parameter(Mandatory)] [string] $Topic,
    [switch] $Preview,
    [string] $SshTarget = 'kraken'
)
$ErrorActionPreference = 'Stop'
$enc = { param($s) [uri]::EscapeDataString($s) }
# CRLF checkouts (core.autocrlf) would put `r into the rendered notification.
$read = { param($f) (Get-Content -Raw -Encoding utf8 (Join-Path $PSScriptRoot $f)) -replace "`r", '' }
$title = (& $read 'title.tmpl').TrimEnd("`n")
$message = & $read 'message.tmpl'
$priority = (& $read 'priority.tmpl').Trim()
$url = "https://ntfy.sh/$Topic`?tpl=yes&t=$(& $enc $title)&m=$(& $enc $message)&p=$(& $enc $priority)"

if ($Preview) {
    $sample = @{
        receiver = 'ntfy'; status = 'firing'; truncatedAlerts = 0; version = '4'; groupKey = 'preview'
        commonLabels = @{ alertname = 'KubePodCrashLooping'; severity = 'warning'; namespace = 'preview' }
        alerts = @(@{ status = 'firing'; startsAt = (Get-Date).ToUniversalTime().ToString('o')
            labels = @{ alertname = 'KubePodCrashLooping'; severity = 'warning'; namespace = 'preview'; pod = 'example-7c9d8f6b54-x2kqp' }
            annotations = @{ summary = 'Pod is crash looping.' } })
    } | ConvertTo-Json -Depth 6
    Invoke-RestMethod -Method Post -Uri $url -ContentType 'application/json' -Body ([Text.Encoding]::UTF8.GetBytes($sample)) | ConvertTo-Json
    return
}

$url | ssh $SshTarget "sudo -n k3s kubectl -n monitoring create secret generic alertmanager-ntfy --from-file=url=/dev/stdin --dry-run=client -o yaml | sudo -n k3s kubectl apply -f -"
Write-Host "Secret updated. The pod sees it within ~1-2 min; Alertmanager reads url_file on every notification."
