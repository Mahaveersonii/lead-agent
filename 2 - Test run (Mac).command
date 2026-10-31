#!/bin/bash
# Test run: nothing is sent to Instantly and nothing is written to the sheet. Uses Bouncify credits.
cd "$(dirname "$0")" || exit 1
.venv/bin/python -W ignore run.py --verify
open output
read -r -p "Press Enter to close."
