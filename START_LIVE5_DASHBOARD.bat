@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist "options_dashboard_AHRAM_LIVE5.html" (
  echo LIVE5 dashboard is not built yet.
  echo Run START_LIVE5_ENGINE.bat first (it fetches data and builds the file).
  pause
  exit /b 1
)
echo Opening LIVE5 dashboard...
start "" options_dashboard_AHRAM_LIVE5.html
pause
