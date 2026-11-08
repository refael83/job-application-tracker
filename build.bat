@echo off
rem Rebuilds the UI (only needed after changing frontend code)
cd /d "%~dp0frontend" && call npm run build
pause
