# One-command launcher (Windows PowerShell). Sets up on first run, then just starts the app.
#   .\start.ps1            -> http://localhost:8000
#   .\start.ps1 -Port 8080
param([int]$Port = 8000)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "First run: creating virtual environment and installing backend..."
    python -m venv .venv
    .venv\Scripts\python.exe -m pip install -e "backend[dev,postgres,sample]"
}
# Local launcher: allow adding connections from the UI. (Public/server deployments keep the locked 'demo' default.)
if (-not $env:MISSYNC_MODE) { $env:MISSYNC_MODE = "self-hosted" }
if (-not (Test-Path "frontend\dist\index.html")) {
    Write-Host "First run: building the frontend..."
    Push-Location frontend
    npm install
    npm run build
    Pop-Location
}
Write-Host "Starting Missync at http://localhost:$Port (Ctrl+C to stop)"
.venv\Scripts\python.exe -m missync serve --port $Port
