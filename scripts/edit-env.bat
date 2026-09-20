@echo off
cd /d "%~dp0.."
if exist ".env" goto open
>".env"  echo BOT_TOKEN=
>>".env" echo CHAT_ID=
>>".env" echo INTERVAL_MIN=60

:open
notepad ".env"
