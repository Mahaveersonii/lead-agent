@echo off
cd /d "%~dp0"
rem Test run: nothing is sent to Instantly and nothing is written to the sheet. Uses Bouncify credits.
.venv\Scripts\python -W ignore run.py --verify
start "" output
pause
