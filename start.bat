@echo off
title Varroa discobox - keep this window open
cd /d "%~dp0"
call conda activate discobox_env
start "" http://127.0.0.1:8000
rem The server stops by itself once the last browser tab is closed.
set DISCOBOX_AUTO_STOP=1
python -m uvicorn web.server:app --host 127.0.0.1 --port 8000
rem Keep the window open only if the server failed, so the error can be read.
if errorlevel 1 pause
