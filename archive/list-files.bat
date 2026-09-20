@echo off
title list-files
cd /d "%~dp0"
git ls-files > repo_files.txt 2>&1
type repo_files.txt
pause
