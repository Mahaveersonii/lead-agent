#!/bin/bash
cd "$(dirname "$0")" || exit 1
.venv/bin/python -W ignore check_setup.py
read -r -p "Press Enter to close."
