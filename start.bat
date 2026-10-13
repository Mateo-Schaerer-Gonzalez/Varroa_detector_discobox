@echo off
title Varroa discobox - keep this window open
cd /d "%~dp0"
call conda activate discobox_env
rem An environment that is missing, or lacks a package the app needs, is made or
rem brought up to discobox_env.yaml before starting.
python -c "import cv2, dotenv, fastapi, matplotlib, numpy, openpyxl, pandas, serial, uvicorn, yaml; from scipy.stats import logrank" 2>nul
if errorlevel 1 (
    echo Updating the Python environment, this can take a few minutes...
    call conda env update -n discobox_env -f discobox_env.yaml
    call conda activate discobox_env
)
start "" http://127.0.0.1:8000
rem The server stops by itself once the last browser tab is closed.
set DISCOBOX_AUTO_STOP=1
python -m uvicorn web.server:app --host 127.0.0.1 --port 8000
rem Keep the window open only if the server failed, so the error can be read.
if errorlevel 1 pause
