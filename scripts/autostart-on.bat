@echo off
title autostart on
cd /d "%~dp0"
echo Registriruyu bota v avtozapusk Windows (pri vhode v sistemu).
echo Posle etogo /start i /who otvechayut mgnovenno, poka komp vklyuchen.
echo.
schtasks /Create /TN "PumaBot" /TR "\"%~dp0run-local.bat\" quiet" /SC ONLOGON /RL LIMITED /F
echo.
if errorlevel 1 (
  echo Ne poluchilos. Poprobuy zapustit etot file kak administrator.
) else (
  echo Gotovo. Bot budet zapuskatsya sam pri vhode v Windows.
  echo Zapustit pryamo seychas: schtasks /Run /TN "PumaBot"
)
echo.
pause
