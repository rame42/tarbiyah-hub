@echo off
REM ===== Stop Tarbiyah Hub safely (Windows) =====
cd /d "%~dp0"
.venv\Scripts\python.exe -m tarbiyah stop
pause
