@echo off
REM Refresh the El Nino tracker, then publish its pages as the site on GitHub
REM Pages: see publish.py, and "Publishing the site" in the README.
REM
REM   publish.bat              run, publish, then wait for a key to close
REM   publish.bat /scheduled   the same, never waiting: for Task Scheduler
REM
REM A run is published when track.py says it ran: 0 (nothing above WATCH open),
REM 1 (WARNING or CRITICAL alerts open) or 3 (some feeds failed), which its pages
REM say. Any other exit publishes nothing. publish.bat then exits with the run's
REM own code once it is published, 2 when the tracker did not run, and 4 when it
REM ran but publishing failed.
setlocal
cd /d "%~dp0"
python track.py --brief
set "code=%errorlevel%"
set "ran="
if "%code%"=="0" set "ran=yes"
if "%code%"=="1" set "ran=yes"
if "%code%"=="3" set "ran=yes"
if not defined ran (
  echo.
  echo The tracker did not run, so nothing was published. Check the messages above.
  if /i not "%~1"=="/scheduled" pause
  exit /b 2
)
python publish.py
set "published=%errorlevel%"
if not "%published%"=="0" (
  echo.
  echo The tracker ran, but publishing failed. Check the messages above.
  if /i not "%~1"=="/scheduled" pause
  exit /b 4
)
if /i not "%~1"=="/scheduled" pause
endlocal & exit /b %code%
