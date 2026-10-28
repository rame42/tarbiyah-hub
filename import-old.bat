@echo off
REM ===== Bring your library from an OLDER Tarbiyah Hub folder into this (new) folder =====
REM  Drag the old Tarbiyah Hub folder onto this file, or double-click and paste its path.
REM  The old folder is only read: nothing in it is changed or deleted.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run install.bat in this folder first, then run this again.
  pause
  exit /b 1
)
set "OLD=%~1"
if "%OLD%"=="" (
  echo Open your OLD Tarbiyah Hub folder in File Explorer, click the address bar, copy the path,
  echo then paste it here ^(right-click^) and press Enter.
  set /p "OLD=Old folder: "
)
echo Stopping this Tarbiyah Hub if it is running...
.venv\Scripts\python.exe -m tarbiyah stop >nul 2>nul
.venv\Scripts\python.exe -m tarbiyah import-old "%OLD%"
echo.
pause
