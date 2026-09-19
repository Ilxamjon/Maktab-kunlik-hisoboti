@echo off
cd /d "%~dp0server"
py -m venv .venv
if errorlevel 1 goto :fail
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :fail
.venv\Scripts\python.exe setup_tuman.py
if errorlevel 1 goto :fail
.venv\Scripts\python.exe setup_school.py
pause
exit /b
:fail
echo Ornatishda xato. Python va internetni tekshiring.
pause
