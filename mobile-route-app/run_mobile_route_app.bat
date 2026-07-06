@echo off
setlocal
cd /d "C:\Users\rhufc\Documents\Codex\2026-04-17-files-mentioned-by-the-user-route\mobile-route-app"

powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetTCPConnection -LocalPort 8042 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }"
timeout /t 1 /nobreak >nul

start "" cmd /c "timeout /t 2 /nobreak >nul && start http://127.0.0.1:8042"

"C:\Users\rhufc\AppData\Local\Python\pythoncore-3.14-64\python.exe" "server.py"
