@echo off
cd /d "%~dp0server"
.venv\Scripts\python.exe connect_telegram.py
pause
