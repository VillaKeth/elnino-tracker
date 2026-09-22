@echo off
REM Refresh the El Nino tracker and open the dashboard.
setlocal
cd /d "%~dp0"
python track.py --open
if errorlevel 1 (
  echo.
  echo Update failed. Check the messages above.
  pause
  exit /b 1
)
endlocal
