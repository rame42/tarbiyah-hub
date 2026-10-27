@echo off
REM ===== Start Tarbiyah Hub: background worker + dashboard (Windows) =====
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run install.bat first.
  pause
  exit /b 1
)
start "Tarbiyah Hub - worker (keep open)" .venv\Scripts\python.exe -m tarbiyah worker
start "Tarbiyah Hub - dashboard (keep open)" .venv\Scripts\python.exe -m tarbiyah web
timeout /t 4 >nul
start "" http://127.0.0.1:8000
echo Tarbiyah Hub is running. Two windows were opened (worker and dashboard).
echo To stop safely, double-click stop.bat (running jobs finish first; nothing is lost).
