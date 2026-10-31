@echo off
cd /d "%~dp0"
echo LIVE RUN: leads will be added to Instantly and to the master sheet.
set /p answer=Type YES to continue: 
if not "%answer%"=="YES" (echo Cancelled. & pause & exit /b 0)
.venv\Scripts\python -W ignore run.py --live
pause
