@echo off
title fill showcase
cd /d "%~dp0.."
set PY=py
py --version >nul 2>nul || set PY=python
set PYTHONIOENCODING=utf-8
echo Napolnyayu vitrinu dlya /start. Eto zanimaet paru minut.
echo.
%PY% -m tools.fill_showcase
echo.
pause
