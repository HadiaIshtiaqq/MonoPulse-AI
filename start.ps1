# Start MonoPlus on Windows: the API on http://localhost:8000 and the web app on http://localhost:3000.
#   powershell -ExecutionPolicy Bypass -File .\start.ps1
# Anything still holding those ports from an earlier run is stopped first, and the web app is rebuilt
# when its code has changed since the last build, so you never see an old version.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

foreach ($port in 8000, 3000) {
    $owners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($id in $owners) {
        Write-Host "Stopping the old process on port $port (PID $id)"
        Stop-Process -Id $id -Force -Confirm:$false
    }
}

$web = Join-Path $root "frontend"
$built = Join-Path $web ".next\BUILD_ID"
$lastBuild = if (Test-Path $built) { (Get-Item $built).LastWriteTime } else { [datetime]::MinValue }
$changed = Get-ChildItem -Path (Join-Path $web "app"), (Join-Path $web "components"), (Join-Path $web "lib") -Recurse -File |
    Where-Object { $_.LastWriteTime -gt $lastBuild } | Select-Object -First 1
if ($changed -or -not (Test-Path $built)) {
    Write-Host "The web app changed since its last build: building it (about a minute)"
    Push-Location $web
    npx next build
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "The web app didn't build. The errors are above." }
    Pop-Location
}

$api = Join-Path $root "backend"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
Start-Process -FilePath (Join-Path $api ".venv\Scripts\python.exe") -ArgumentList "-m", "uvicorn", "app.main:app", "--port", "8000" -WorkingDirectory $api
Start-Process -FilePath "npx.cmd" -ArgumentList "next", "start", "-p", "3000" -WorkingDirectory $web
Write-Host "MonoPlus is starting: open http://localhost:3000 in a few seconds."
