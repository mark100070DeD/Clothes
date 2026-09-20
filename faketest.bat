@echo off
title faketest
cd /d "%~dp0"
python faketest.py > faketest_log.txt 2>&1
(
  echo IGNORED?
  git check-ignore -v puma.db
  echo STATUS
  git status --porcelain
  echo ADD
  git add -f puma.db
  git add -A
  git commit -m "test: fake price drops"
  echo PUSH
  git push
  echo LOG
  git log --oneline -1
) >> faketest_log.txt 2>&1
exit
