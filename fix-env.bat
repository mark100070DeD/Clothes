@echo off
cd /d "%~dp0"
set PY=py
py --version >nul 2>nul || set PY=python
set PYTHONIOENCODING=utf-8
%PY% -u fix_env.py > fix_env_result.txt 2>&1
type fix_env_result.txt
pause
