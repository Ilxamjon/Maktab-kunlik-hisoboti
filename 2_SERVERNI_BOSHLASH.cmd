@echo off
cd /d "%~dp0server"
set HOST=0.0.0.0
.venv\Scripts\python.exe app.py
pause
