@echo off
title setup-github
cd /d "%~dp0"
set REPO=https://github.com/mark100070DeD/Clothes.git

git --version >nul 2>nul
if errorlevel 1 goto nogit

if not exist ".github\workflows" mkdir ".github\workflows"
if exist "puma-workflow.yml" move /y "puma-workflow.yml" ".github\workflows\puma.yml" >nul

if not exist ".git" git init -b main
git add -A
git commit -m "puma sale bot" >nul 2>nul
git branch -M main
git remote remove origin >nul 2>nul
git remote add origin %REPO%
git push -u origin main
echo.
echo If a login window appeared, finish signing in to GitHub and run this file again.
echo Next step: add secrets BOT_TOKEN and CHAT_ID in the repository settings.
pause
exit /b

:nogit
echo Git is not installed. Get it from https://git-scm.com/download/win and run this again.
pause
