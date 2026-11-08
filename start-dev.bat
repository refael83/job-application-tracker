@echo off
rem Dev mode: the server restarts automatically when a backend file changes, and the UI is rebuilt when a file in frontend\src changes
start "" powershell -NoExit -ExecutionPolicy Bypass -File "%~dp0start.ps1" -Dev
