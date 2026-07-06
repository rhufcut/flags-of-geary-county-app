@echo off
setlocal
cd /d "C:\Users\rhufc\Documents\Codex\2026-04-17-files-mentioned-by-the-user-route\mobile-route-app"

powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetTCPConnection -LocalPort 8042,4040 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }"
timeout /t 1 /nobreak >nul

start "Flags of Geary County Mobile App" cmd /c "run_mobile_route_app.bat"
timeout /t 3 /nobreak >nul
start http://127.0.0.1:8042
start "Flags of Geary County Public Tunnel" "C:\Users\rhufc\AppData\Local\Microsoft\WinGet\Packages\Ngrok.Ngrok_Microsoft.Winget.Source_8wekyb3d8bbwe\ngrok.exe" http 8042
timeout /t 4 /nobreak >nul
start http://127.0.0.1:4040
