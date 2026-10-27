@echo off
REM ===== Tarbiyah Hub - one-time installation (Windows) =====
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (set PY=py -3) else (set PY=python)
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo Python 3.11+ is required. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  pause
  exit /b 1
)
if not exist .venv (
  echo Creating virtual environment...
  %PY% -m venv .venv || goto :fail
)
echo Installing Python packages (this can take a few minutes)...
.venv\Scripts\python.exe -m pip install --upgrade pip >nul
.venv\Scripts\python.exe -m pip install -r requirements.txt || goto :fail
if not exist .env (
  copy .env.example .env >nul
  echo Created .env - open it with Notepad to add optional keys such as ANTHROPIC_API_KEY.
)
.venv\Scripts\python.exe -m tarbiyah init || goto :fail
echo.
echo Installation complete. Double-click start.bat to run Tarbiyah Hub.
pause
exit /b 0
:fail
echo.
echo Installation failed. Read the error above; see docs\INSTALL.md (Troubleshooting).
pause
exit /b 1
