#!/bin/bash
# Lead Agent: one-command setup for Mac. Safe to run again (it skips what is already done).
set -e
cd "$(dirname "$0")"
say() { printf "\n\033[1m== %s\033[0m\n" "$1"; }

say "1/5  Python"
if ! command -v python3 >/dev/null || ! python3 -c "import sys; sys.exit(sys.version_info < (3, 9))"; then
  echo "Python 3 is missing. A window will ask to install Apple's developer tools: click Install, wait, then run this command again."
  xcode-select --install || true
  exit 1
fi
python3 --version

say "2/5  Agent libraries"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt
mkdir -p Leads/Incoming Leads/Processed output secrets
chmod +x ./*.command
echo "Installed."

say "3/5  Ollama (local AI)"
OLLAMA=$(command -v ollama || true)
[ -z "$OLLAMA" ] && [ -x /Applications/Ollama.app/Contents/Resources/ollama ] && OLLAMA=/Applications/Ollama.app/Contents/Resources/ollama
if [ -z "$OLLAMA" ]; then
  echo "Downloading Ollama from ollama.com..."
  TMP=$(mktemp -d)
  curl -fL --progress-bar https://ollama.com/download/Ollama-darwin.zip -o "$TMP/Ollama.zip"
  ditto -xk "$TMP/Ollama.zip" /Applications
  rm -rf "$TMP"
  OLLAMA=/Applications/Ollama.app/Contents/Resources/ollama
fi
open -a Ollama || true
for _ in $(seq 1 30); do curl -s localhost:11434/api/tags >/dev/null && break; sleep 2; done
echo "Downloading the AI model (about 5 GB, only the first time)..."
"$OLLAMA" pull qwen3:8b

say "4/5  API keys"
[ -f .env ] || cp .env.example .env
.venv/bin/python keys_vault.py unlock

say "5/5  Checking everything"
.venv/bin/python -W ignore check_setup.py || true

echo
echo "Setup finished. Daily use: double-click '2 - Test run (Mac).command', then '3 - LIVE run (Mac).command'."
