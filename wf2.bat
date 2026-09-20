@echo off
title wf2
cd /d "%~dp0"
copy /y "start-workflow.yml" ".github\workflows\start.yml" > wf2_log.txt 2>&1
copy /y "puma-workflow.yml" ".github\workflows\puma.yml" >> wf2_log.txt 2>&1
(
  git add -A
  git commit -m "run workflows on push too"
  echo PUSH
  git push
  echo LOG
  git log --oneline -1
) >> wf2_log.txt 2>&1
exit
