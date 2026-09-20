@echo off
title runonce
cd /d "%~dp0"
python bot.py --once > bot_log.txt 2>&1
exit
