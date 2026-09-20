@echo off
title export latest
cd /d "%~dp0.."
set PY=py
py --version >nul 2>nul || set PY=python
set PYTHONIOENCODING=utf-8
echo Sobirayu data/latest.json. Eto zanimaet okolo minuty.
echo.
%PY% -m tools.export_latest
echo.
pause
