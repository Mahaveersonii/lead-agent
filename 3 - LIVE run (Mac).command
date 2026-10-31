#!/bin/bash
# Live run: adds leads to the newest Draft (New-mails) campaign and to the master sheet.
cd "$(dirname "$0")" || exit 1
echo "LIVE RUN: leads will be added to Instantly and to the master sheet."
read -r -p "Type YES to continue: " answer
[ "$answer" = "YES" ] || { echo "Cancelled."; read -r; exit 0; }
.venv/bin/python -W ignore run.py --live
read -r -p "Press Enter to close."
