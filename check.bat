@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=py
py --version >nul 2>nul || set PY=python
set PYTHONIOENCODING=utf-8
> check_result.txt 2>&1 (
  %PY% --version
  %PY% -m pip install -q -r requirements.txt
  %PY% -u check.py
)
type check_result.txt
pause
