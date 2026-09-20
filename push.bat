@echo off
title github-push
cd /d "%~dp0"
git config --global credential.helper manager
git push -u origin main
echo.
echo If a browser window opened, approve the GitHub sign-in and run this file again.
pause
