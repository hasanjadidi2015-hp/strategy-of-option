@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo ============================================================
echo   AHRAM LIVE5 - self-contained engine + dashboard
echo   (collector + 6 V2 engines + sentiment + LIVE5.html)
echo ============================================================
echo.
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found on PATH.
  echo Install Python 3.10+ from https://www.python.org/ and tick "Add to PATH".
  pause
  exit /b 1
)
echo Running one cycle (collect + V2 + build LIVE5)...
python ahram_engine_v5.py --once
if errorlevel 1 (
  echo.
  echo The engine failed. Please send a screenshot of this window.
  pause
  exit /b 1
)
echo.
echo Opening LIVE5 dashboard...
start "" options_dashboard_AHRAM_LIVE5.html
echo.
echo Done.  To run continuously (every 5 minutes) use:
echo        python ahram_engine_v5.py
pause
