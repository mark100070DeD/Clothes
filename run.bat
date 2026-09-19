@echo off
title puma-bot
cd /d "%~dp0"
set PY=py
py --version >nul 2>nul || set PY=python
set PYTHONIOENCODING=utf-8
if not exist ".env" goto nofile
echo Stopping previous bot instance, if any...
wmic process where "name='python.exe' and commandline like '%%bot.py%%'" delete >nul 2>nul
%PY% -m pip install -q -r requirements.txt
echo Bot is running. Log file: bot_log.txt
echo Do not close this window.
%PY% -u bot.py > bot_log.txt 2>&1
pause
exit /b

:nofile
echo No .env file found. Run edit-env.bat, paste the token, then try again.
pause
