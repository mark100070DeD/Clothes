@echo off
title gitsync
cd /d "%~dp0"
(
  git rm --cached --ignore-unmatch gitsync_log.txt update_log.txt repo_files.txt
  git add -A
  git commit -m "clean up local logs"
  echo === push ===
  git push
  echo === log ===
  git log --oneline -3
) > gitsync_log.txt 2>&1
exit
