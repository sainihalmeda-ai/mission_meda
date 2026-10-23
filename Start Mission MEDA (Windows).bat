@echo off
title Mission MEDA
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Opening the download page...
  echo Install it, tick "Add python.exe to PATH" on the first screen, then double-click this file again.
  start https://www.python.org/downloads/
  pause
  exit /b
)
if not exist ".venv\Scripts\python.exe" (
  echo First-time setup: installing Mission MEDA. This takes a minute or two...
  py -3 -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
)
rem Updates itself, installs anything new, then starts the crew.
".venv\Scripts\python.exe" launch.py %*
pause
