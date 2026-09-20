@echo off
title publish
cd /d "%~dp0.."
if not exist logs mkdir logs
set MSG=%~1
if "%MSG%"=="" set MSG=update
(
  git add -A
  git add -f data/puma.db
  git commit -m "%MSG%"
  git pull --rebase
  git push
  git log --oneline -3
) > logs\publish_log.txt 2>&1
type logs\publish_log.txt
if /i not "%~2"=="quiet" pause
