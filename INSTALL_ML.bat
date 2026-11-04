@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Start with START_WINDOWS.bat to create this project's environment.
 pause
 exit /b 1
)
.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-ml.txt
if errorlevel 1 goto FAILED
.venv\Scripts\python.exe -c "import numpy,scipy,sklearn; print('ML imports OK:',numpy.__version__,scipy.__version__,sklearn.__version__)"
if errorlevel 1 goto FAILED
echo Model libraries loaded. Restart START_WINDOWS.bat.
pause
exit /b 0
:FAILED
echo ML installation or loading failed. Run DIAGNOSE_WINDOWS.bat.
echo A policy-blocked binary must be reviewed by an authorized administrator.
echo The core UI does not depend on pandas, PyArrow or Streamlit.
pause
exit /b 1
