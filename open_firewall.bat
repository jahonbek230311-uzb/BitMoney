@echo off
net session >nul 2>nul
if errorlevel 1 (
  echo Run this file as administrator: right-click it and choose Run as administrator.
  pause
  exit /b 1
)
netsh advfirewall firewall add rule name="CPJudge 8000" dir=in action=allow protocol=TCP localport=8000 profile=private,domain
echo.
echo Done. Port 8000 is open on Private/Domain networks.
echo Make sure your Wi-Fi is set to "Private network": Settings, Network and Internet, Wi-Fi, your network, Private.
pause
