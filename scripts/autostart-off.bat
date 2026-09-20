@echo off
title autostart off
echo Ubirayu bota iz avtozapuska Windows.
echo Komandy /start i /who snova budut otvechat tolko cherez GitHub, s zaderzhkoy.
echo.
schtasks /Delete /TN "PumaBot" /F
echo.
pause
