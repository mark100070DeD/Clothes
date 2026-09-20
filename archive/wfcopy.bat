@echo off
title wfcopy
cd /d "%~dp0"
if not exist ".github\workflows" mkdir ".github\workflows"
copy /y "start-workflow.yml" ".github\workflows\start.yml" > wfcopy_log.txt 2>&1
(
  git add -A
  git commit -m "add fast start workflow"
  echo PUSH
  git push
  echo FILES
  git ls-files .github
) >> wfcopy_log.txt 2>&1
exit
