@echo off
setlocal
cd /d "%~dp0"
title India Quant - Local Research Platform
set "PY=%~dp0.venv\Scripts\python.exe"
echo.
echo INDIA QUANT - Research and manual paper trading. No live orders.
echo.
if exist "%PY%" goto CHECK_CORE
py -3.11 -c "import struct; assert struct.calcsize('P') == 8" >nul 2>&1
if errorlevel 1 (
 echo Python 3.11 64-bit with the Python Launcher is required by this launcher.
 echo Install from python.org, enable the launcher, then run this file again.
 echo No existing trading folder or journal has been removed.
 pause
 exit /b 1
)
py -3.11 -m venv .venv
if errorlevel 1 goto FAILED
:CHECK_CORE
"%PY%" -c "import fastapi,uvicorn,pydantic; print('Core libraries loaded.')" >nul 2>&1
if not errorlevel 1 goto CHECK_ML
echo Installing the core application from PyPI...
"%PY%" -m pip install --only-binary=:all: -r requirements-core.txt
if errorlevel 1 goto FAILED
:CHECK_ML
"%PY%" -c "import numpy,scipy,sklearn,joblib,threadpoolctl" >nul 2>&1
if not errorlevel 1 goto RUN
if exist ".venv\ml_install_attempted.txt" goto ML_WARNING
echo Installing the model comparison libraries...
"%PY%" -m pip install --only-binary=:all: -r requirements-ml.txt
> ".venv\ml_install_attempted.txt" echo An ML installation was attempted. Use INSTALL_ML.bat to retry.
"%PY%" -c "import numpy,scipy,sklearn,joblib,threadpoolctl" >nul 2>&1
if not errorlevel 1 goto RUN
:ML_WARNING
echo.
echo ML libraries are not currently usable. The interface and rule research can run.
echo Use INSTALL_ML.bat to retry. Run DIAGNOSE_WINDOWS.bat for details.
echo An Application Control block needs authorized administrator review.
echo Do not disable Windows security or download DLLs from unofficial websites.
echo.
:RUN
"%PY%" run.py
if errorlevel 1 goto FAILED
exit /b 0
:FAILED
echo.
echo The application did not start. Run DIAGNOSE_WINDOWS.bat and read README.md.
echo Existing data, credentials and other project folders were preserved.
pause
exit /b 1
