@echo off
title puma-once
cd /d "%~dp0.."
if not exist logs mkdir logs
set PY=py
py --version >nul 2>nul || set PY=python
set PYTHONIOENCODING=utf-8
%PY% bot.py --once > logs\bot_log.txt 2>&1
if /i not "%~1"=="quiet" pause
