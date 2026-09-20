@echo off
title deploy2
cd /d "%~dp0"
(
  git add -A
  git add -f puma.db
  git commit -m "fast /start responder + alarm on empty parse"
  echo PUSH
  git push
  echo LOG
  git log --oneline -2
  echo FILES
  git ls-files .github
) > deploy2_log.txt 2>&1
exit
