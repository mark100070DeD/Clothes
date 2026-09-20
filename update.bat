@echo off
title update-github
cd /d "%~dp0"
git add -A
git commit -m "start works in actions mode"
git push
echo.
echo Done. If it asks for login, finish it and run this file again.
pause
