#!/bin/bash
# Opens the Lead Agent dashboard in the browser. Keep this window open while you use it.
cd "$(dirname "$0")" || exit 1
curl -s localhost:11434/api/tags >/dev/null || open /Applications/Ollama.app
.venv/bin/python -W ignore dashboard.py
