@echo off
REM Checks the AI settings in .env and sends one test message.
cd /d "%~dp0"
.venv\Scripts\python.exe -m tarbiyah test-ai
echo.
pause
