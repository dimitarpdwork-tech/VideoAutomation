@echo off
setlocal
cd /d "%~dp0"
set "PYTHON312=py -3.12"
if not "%~1"=="" set PYTHON312="%~1"
%PYTHON312% setup_voice.py
if errorlevel 1 (
  echo Voice setup did not finish. Kokoro narration still works; run setup_voice.cmd again later.
  pause
  exit /b 1
)
pause
