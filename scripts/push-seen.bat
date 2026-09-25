@echo off
title push seen to worker
cd /d "%~dp0.."
set PY=py
py --version >nul 2>nul || set PY=python
set PYTHONIOENCODING=utf-8
echo Perenoshu pamyat bota (data/puma.db) v hranilishche Worker.
echo Delaetsya odin raz pri pereezde. Povtor bezopasen.
echo.
%PY% -m tools.push_seen
echo.
pause
