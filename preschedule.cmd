@echo off
cd /d "%~dp0"
set /p COUNT="How many ready videos should be scheduled on YouTube? "
.venv\Scripts\python.exe preschedule.py --channel main --count %COUNT%
pause
