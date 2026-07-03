@echo off
cd /d "%~dp0"
if not exist .venv (
    echo Creating virtual environment...
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -m venv .venv
    call .venv\Scripts\python.exe -m pip install --upgrade pip
    call .venv\Scripts\python.exe -m pip install -r requirements.txt
)
start "" http://localhost:8000
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
