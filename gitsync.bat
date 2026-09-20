@echo off
title gitsync
cd /d "%~dp0"
(
  echo === status ===
  git status -sb
  echo === add/commit ===
  git add -A
  git commit -m "start works in actions mode"
  echo === push ===
  git push
  echo === log ===
  git log --oneline -3
) > gitsync_log.txt 2>&1
exit
