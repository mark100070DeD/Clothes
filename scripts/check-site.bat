@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if not exist logs mkdir logs
set PY=py
py --version >nul 2>nul || set PY=python
set PYTHONIOENCODING=utf-8
> logs\check_result.txt 2>&1 (
  %PY% --version
  %PY% -m pip install -q -r requirements.txt
  %PY% -u -m tools.check_site
)
type logs\check_result.txt
if /i not "%~1"=="quiet" pause
