# Lead Agent: one-command setup for Windows. Safe to run again (it skips what is already done).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
function Say($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Refresh-Path { $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User") }

Say "1/5  Python"
if (-not (Get-Command python -ErrorAction SilentlyContinue) -or -not (python --version 2>$null)) {
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    Refresh-Path
}
python --version

Say "2/5  Agent libraries"
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python -m pip install -q --upgrade pip
.\.venv\Scripts\python -m pip install -q --prefer-binary -r requirements.txt
"Leads\Incoming", "Leads\Processed", "output", "secrets" | ForEach-Object { New-Item -ItemType Directory -Force $_ | Out-Null }
"Installed."

Say "3/5  Ollama (local AI)"
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
    Refresh-Path
}
for ($i = 0; $i -lt 30; $i++) {
    try { Invoke-WebRequest -UseBasicParsing http://localhost:11434/api/tags | Out-Null; break } catch { Start-Sleep 2 }
}
"Downloading the AI model (about 5 GB, only the first time)..."
ollama pull qwen3:8b

Say "4/5  API keys"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python keys_vault.py unlock

Say "5/5  Checking everything"
.\.venv\Scripts\python -W ignore check_setup.py

"`nSetup finished. Daily use: double-click '0 - Open Dashboard (Windows).bat'."
