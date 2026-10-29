# Share MonoPlus with a public link (for a demo or the hackathon judges), from this computer.
#   powershell -ExecutionPolicy Bypass -File .\start-public.ps1
# Uses Cloudflare's free quick tunnel: no account, and the link lasts while this window is open.
# It refuses to start without MONOPLUS_ACCESS_KEY in backend\.env: anyone with the link would otherwise
# be able to use MonoPlus. Share the key with the people you send the link to.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$envFile = Join-Path $root "backend\.env"

$hasKey = $false
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile) {
        if ($line -match '^\s*MONOPLUS_ACCESS_KEY\s*=\s*(\S{12,})\s*$') { $hasKey = $true }
    }
}
if (-not $hasKey) {
    Write-Host "Set MONOPLUS_ACCESS_KEY in backend\.env first (at least 12 characters, e.g. a long random password)."
    Write-Host "Everyone you share the link with types it once to get in."
    exit 1
}

$tunnel = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $tunnel) {
    Write-Host "Install Cloudflare's tunnel tool first (free):  winget install --id Cloudflare.cloudflared"
    Write-Host "Then open a new PowerShell window and run this again."
    exit 1
}

& powershell -ExecutionPolicy Bypass -File (Join-Path $root "start.ps1")
Write-Host ""
Write-Host "Opening the public link. Look for a line with https://....trycloudflare.com below: that's your link."
Write-Host "Keep this window open while people use it; close it (Ctrl+C) to take the link down."
& $tunnel.Source tunnel --no-autoupdate --url http://localhost:3000
