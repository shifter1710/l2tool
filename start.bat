@echo off
rem One-step launch for l2tool: creates .venv on first run, installs
rem dependencies and opens the web UI at http://127.0.0.1:8765.
rem Extra arguments are passed to webapp.py: start.bat --port 9000 --no-browser
setlocal
cd /d "%~dp0"

set "PYCMD="
py -3 --version >nul 2>nul
if not errorlevel 1 set "PYCMD=py -3"
if not defined PYCMD (
  python --version >nul 2>nul
  if not errorlevel 1 set "PYCMD=python"
)
if not defined PYCMD (
  echo Python not found. Install Python 3.10+ from https://www.python.org/ and run start.bat again.
  exit /b 1
)

%PYCMD% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 (
  echo Python 3.10 or newer is required.
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment .venv ...
  %PYCMD% -m venv .venv
  if errorlevel 1 goto :fail
)

".venv\Scripts\python.exe" -c "import fastapi, jinja2, openpyxl, uvicorn" >nul 2>nul
if errorlevel 1 (
  echo Installing dependencies ...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :fail
)

".venv\Scripts\python.exe" webapp.py %*
exit /b %errorlevel%

:fail
echo Failed to launch l2tool.
exit /b 1
