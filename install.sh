#!/bin/bash
# Lead Agent: one-command setup for Mac. Safe to run again (it skips what is already done).
set -e
cd "$(dirname "$0")"
say() { printf "\n\033[1m== %s\033[0m\n" "$1"; }

say "1/4  Python"
if ! command -v python3 >/dev/null || ! python3 -c "import sys; sys.exit(sys.version_info < (3, 9))"; then
  echo "Python 3 is missing. A window will ask to install Apple's developer tools: click Install, wait, then run this command again."
  xcode-select --install || true
  exit 1
fi
python3 --version

say "2/4  Agent libraries"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q --prefer-binary -r requirements.txt
mkdir -p Leads/Incoming Leads/Processed output secrets
chmod +x ./*.command
echo "Installed."

say "3/4  API keys"
[ -f .env ] || cp .env.example .env
.venv/bin/python keys_vault.py unlock

say "4/4  Checking everything"
.venv/bin/python -W ignore check_setup.py || true

echo
echo "Setup finished. Daily use: double-click '0 - Open Dashboard (Mac).command'."
