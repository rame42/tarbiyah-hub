@echo off
REM ===== Update Tarbiyah Hub in place (keeps data, keys, sources and settings) =====
REM  - Double-click: downloads the latest version from GitHub (needs TH_UPDATE_REPO in .env)
REM  - Or drag a tarbiyah-hub.zip file onto this file to apply that zip
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run install.bat first.
  pause
  exit /b 1
)
echo Stopping Tarbiyah Hub (running jobs finish first)...
.venv\Scripts\python.exe -m tarbiyah stop
if "%~1"=="" (
  .venv\Scripts\python.exe -m tarbiyah update
) else (
  .venv\Scripts\python.exe -m tarbiyah update --zip "%~1"
)
if errorlevel 1 (
  echo.
  echo ===== The update did NOT complete. Nothing was lost. The message above says why. =====
  echo Starting the current version again...
) else (
  echo.
  echo ===== Update finished. In the browser press Ctrl+F5 once. =====
)
echo Starting Tarbiyah Hub...
call start.bat
echo.
echo You can close this window.
pause
