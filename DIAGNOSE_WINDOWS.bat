@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
 .venv\Scripts\python.exe diagnose.py
) else (
 py -3.11 diagnose.py
)
echo.
echo Read diagnostic_report.txt. No access tokens or environment values are collected.
pause
