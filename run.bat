@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
if not exist .venv (
    echo No virtual environment found - running the installer first...
    call install.bat
    if not exist .venv\Scripts\python.exe exit /b 1
)
start "" http://localhost:8000
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
