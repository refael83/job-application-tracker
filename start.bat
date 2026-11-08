@echo off
rem Runs the server in a single PowerShell window (live log, stop with Ctrl+C). For background mode without a window: start.vbs
start "" powershell -NoExit -ExecutionPolicy Bypass -File "%~dp0start.ps1"
