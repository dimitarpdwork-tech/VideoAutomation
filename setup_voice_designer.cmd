@echo off
setlocal
cd /d "%~dp0"
set "PYTHON312=py -3.12"
if not "%~1"=="" set PYTHON312="%~1"
%PYTHON312% setup_voice_designer.py
if errorlevel 1 (
  echo Voice designer setup did not finish. Everything else still works; run setup_voice_designer.cmd again later.
  pause
  exit /b 1
)
pause
