# Runs Job Tracker in this PowerShell window. Ctrl+C or closing the window stops it.
#   .\start.ps1        normal mode
#   .\start.ps1 -Dev   dev mode: the server restarts automatically when a backend .py/.env file changes,
#                      and the frontend is rebuilt automatically when files in frontend\src change
param([switch]$Dev)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$port = if ($env:TRACKER_PORT) { [int]$env:TRACKER_PORT } else { 8000 }
$Host.UI.RawUI.WindowTitle = if ($Dev) { "Job Tracker - DEV, auto-restart (Ctrl+C to stop)" } else { "Job Tracker (Ctrl+C to stop)" }

# stop an older background instance (start.vbs) so the port is free and logs show here
Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)"
    if ($proc.CommandLine -like '*run.py*') {
        Write-Host "Stopping previous background instance (PID $($proc.ProcessId))..."
        Stop-Process -Id $proc.ProcessId -Force
        Start-Sleep -Seconds 1
    }
}

$watcher = $null
if ($Dev) {
    Write-Host "Dev mode: watching frontend\src (rebuild) and backend (restart)"
    $watcher = Start-Job -ScriptBlock { Set-Location "$using:root\frontend"; npm run build -- --watch 2>&1 }
}

Set-Location "$root\backend"
try {
    if ($Dev) { & "$root\backend\.venv\Scripts\python.exe" run.py --reload }
    else { & "$root\backend\.venv\Scripts\python.exe" run.py }
}
finally {
    if ($watcher) { Stop-Job $watcher -ErrorAction SilentlyContinue; Remove-Job $watcher -Force -ErrorAction SilentlyContinue }
}
