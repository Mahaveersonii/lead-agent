@echo off
cd /d "%~dp0"
.venv\Scripts\python -W ignore check_setup.py
pause
