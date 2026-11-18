#!/bin/bash
# Opens the Lead Agent dashboard in the browser. Keep this window open while you use it.
cd "$(dirname "$0")" || exit 1
.venv/bin/python -W ignore dashboard.py
