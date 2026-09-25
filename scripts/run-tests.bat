@echo off
cd /d "%~dp0.."
if not exist logs mkdir logs
set PY=py
py --version >nul 2>nul || set PY=python
set PYTHONIOENCODING=utf-8
> logs\tests_result.txt 2>&1 (
  %PY% -m tests.test_parse
  %PY% -m tests.test_pending
  %PY% -m tests.test_checker
  %PY% -m tests.test_subs_sync
  %PY% -m tests.test_klevu
  %PY% -m tests.test_audit
)
type logs\tests_result.txt
if /i not "%~1"=="quiet" pause
