@echo off
cd /d "%~dp0"
if not exist ".env" (echo BOT_TOKEN=& echo CHAT_ID=& echo INTERVAL_MIN=60)>".env"
notepad ".env"
