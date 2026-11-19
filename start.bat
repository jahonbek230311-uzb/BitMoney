@echo off
setlocal
cd /d "%~dp0"

where docker >nul 2>nul
if errorlevel 1 (
  echo Docker not found. Install Docker Desktop and start it.
  pause
  exit /b 1
)
docker info >nul 2>nul
if errorlevel 1 (
  echo Docker is installed but not running. Start Docker Desktop, wait until it says running, then run this again.
  pause
  exit /b 1
)

set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY python --version >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python not found. Install Python 3.12 from python.org and tick Add Python to PATH, then reopen this window.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  if exist ".venv" rmdir /s /q ".venv"
  echo Creating virtual environment...
  %PY% -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
  echo Could not create the virtual environment. Send the message printed above.
  pause
  exit /b 1
)
set "VPY=.venv\Scripts\python.exe"

"%VPY%" -m pip --version >nul 2>nul
if errorlevel 1 (
  echo pip is missing in the virtual environment. Installing it...
  "%VPY%" -m ensurepip --upgrade
)
"%VPY%" -m pip --version >nul 2>nul
if errorlevel 1 (
  rmdir /s /q ".venv"
  echo.
  echo Your Python was installed without pip.
  echo Fix: open Windows Settings, Apps, find Python, Modify, Modify again, tick pip, finish.
  echo Or reinstall Python from python.org and keep the pip option ticked.
  echo Then run start.bat again.
  pause
  exit /b 1
)

echo Installing packages...
"%VPY%" -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo pip install failed. Check your internet connection.
  pause
  exit /b 1
)

docker image inspect cpjudge-sandbox:latest >nul 2>nul
if errorlevel 1 (
  echo Building sandbox image. The first time needs Docker base image and internet...
  docker build -q -t cpjudge-sandbox:latest judge
  if errorlevel 1 (
    echo Docker build failed. Connect to internet for first-time setup, then retry.
    pause
    exit /b 1
  )
) else (
  echo Sandbox image already exists; using the cached local image.
)

"%VPY%" -m app.cli has-admin
if not errorlevel 1 goto adminok
echo.
echo No admin account yet. Creating it...
:askadmin
"%VPY%" -m app.cli create-admin
if errorlevel 1 (
  echo That did not work. Try again.
  goto askadmin
)
echo Creating sample problem A + B with verified tests...
"%VPY%" -m app.cli seed-sample
:adminok

echo.
echo Automatic tests use a local Ollama model; no API key is needed.
ollama list >nul 2>nul
if errorlevel 1 (
  echo Ollama is not installed or not running. Auto-test generation will not work until Ollama is installed.
) else (
  echo Local Ollama is available. Confirm qwen2.5-coder:14b is installed with: ollama list
)
echo For first-time setup, download the model while internet is available:
echo   ollama pull qwen2.5-coder:14b
echo After setup, the site and judging work on the local Wi-Fi without internet.
echo Auto-test generation needs the model already downloaded on this computer.


set "LANIP=localhost"
for /f %%i in ('"%VPY%" -m app.cli lan-ip') do set "LANIP=%%i"
echo.
echo ================================================================
echo   This computer:               http://localhost:8000
echo   Other devices on same Wi-Fi/hotspot: http://%LANIP%:8000
echo ================================================================
echo Connect this PC and all users to the SAME Wi-Fi/hotspot.
echo If other devices cannot open it, run open_firewall.bat as administrator once.
echo Press Ctrl+C to stop the server.
"%VPY%" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
