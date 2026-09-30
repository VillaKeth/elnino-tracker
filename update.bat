@echo off
REM Refresh the El Nino tracker and open the dashboard.
REM track.py exits 0 (ran), 1 (ran; WARNING or CRITICAL alerts are open),
REM 2 (could not run) or 3 (ran, but some feeds failed). Only 2 is a failure.
setlocal
cd /d "%~dp0"
python track.py --open
set "code=%errorlevel%"
if "%code%"=="2" (
  echo.
  echo Update failed. Check the messages above.
  pause
  exit /b 2
)
if "%code%"=="3" (
  echo.
  echo Updated, but some feeds failed and the analysis is degraded.
  echo See the messages above and the provenance panel on the dashboard.
  pause
)
if "%code%"=="1" (
  echo.
  echo Updated. WARNING or CRITICAL alerts are open: see the dashboard.
)
endlocal & exit /b %code%
