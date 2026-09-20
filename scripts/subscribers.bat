@echo off
title subscribers
cd /d "%~dp0.."
set PY=py
py --version >nul 2>nul || set PY=python
set PYTHONIOENCODING=utf-8
echo Obnovlyayu bazu s servera...
git pull --rebase
echo.
%PY% -m tools.subscribers
echo.
pause
