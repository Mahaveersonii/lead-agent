# Lead Agent: one-command setup for Windows. Safe to run again (it skips what is already done).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
function Say($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Refresh-Path { $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User") }

Say "1/4  Python"
if (-not (Get-Command python -ErrorAction SilentlyContinue) -or -not (python --version 2>$null)) {
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    Refresh-Path
}
python --version

Say "2/4  Agent libraries"
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python -m pip install -q --upgrade pip
.\.venv\Scripts\python -m pip install -q --prefer-binary -r requirements.txt
"Leads\Incoming", "Leads\Processed", "output", "secrets" | ForEach-Object { New-Item -ItemType Directory -Force $_ | Out-Null }
"Installed."

Say "3/4  API keys"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python keys_vault.py unlock

Say "4/4  Checking everything"
.\.venv\Scripts\python -W ignore check_setup.py

"`nSetup finished. Daily use: double-click '0 - Open Dashboard (Windows).bat'."
