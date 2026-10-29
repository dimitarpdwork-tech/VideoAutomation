@echo off
cd /d "%~dp0"
echo Publishes videos only for channels with the local schedule enabled.
echo Keep this window open. Press Ctrl+C to stop.
call .venv\Scripts\python.exe scheduler.py
pause
