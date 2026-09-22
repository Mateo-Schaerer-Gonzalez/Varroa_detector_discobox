@echo off
title Varroa discobox - keep this window open
cd /d "%~dp0"
call conda activate discobox_env
start "" http://127.0.0.1:8000
python -m uvicorn web.server:app --host 127.0.0.1 --port 8000
pause
